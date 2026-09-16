import io
import json
import time
import zipfile
from uuid import uuid4

import pytest
from conftest import ROOT, SYNC_ENGINE, checked, review_body, start_run, wait_for
from sqlalchemy import text


def test_import_mapping_and_duplicate_confirmation(workspace):
    ws = workspace
    assert len(ws["products"]) == 50
    product = ws["products"]["CF-0007"]
    assert product["attributes"]["material"] == "Leather"
    assert product["original"]["Legacy note"] == "Synthetic demo · not a real product"
    duplicate = checked(
        ws["client"].post(
            "/imports/preview",
            files={"file": ("same.csv", (ROOT / "fixtures/catalog.csv").read_bytes())},
        )
    )
    assert duplicate["id"] == ws["preview"]["id"]
    checked(
        ws["client"].post(
            f"/imports/{duplicate['id']}/confirm",
            json={"category_id": ws["category"]["id"], "mapping": ws["mapping"]},
        )
    )
    assert len(checked(ws["client"].get("/products"))) == 50


def test_ingestion_idempotent_and_structural_metadata(workspace):
    ws = workspace
    before = checked(ws["client"].get("/sources"))
    path = ROOT / "fixtures/sources/03-datasheets.pdf"
    duplicate = checked(
        ws["client"].post("/sources", files={"file": (path.name, path.read_bytes())})
    )
    assert len(checked(ws["client"].get("/sources"))) == len(before)
    detail = checked(ws["client"].get("/sources/" + duplicate["id"]))
    assert len(detail["chunks"]) == 5 and detail["chunks"][0]["location"]["page"] == 1
    csvdoc = next(doc for doc in before if doc["filename"].endswith(".csv"))
    csvdetail = checked(ws["client"].get("/sources/" + csvdoc["id"]))
    assert csvdetail["chunks"][0]["location"]["row"] == 2


def test_workspace_isolation_files_search_events_resume(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0001")
    client = ws["client"]
    client.headers["x-workspace-id"] = ws["other_id"]
    try:
        assert checked(client.get("/products")) == []
        assert checked(client.get("/products?q=ForgeWorks")) == []
        assert checked(client.get("/sources")) == []
        for path in [
            "/products/" + detail["product"]["id"],
            "/sources/" + ws["docs"][0]["id"],
            "/sources/" + ws["docs"][0]["id"] + "/file",
            "/runs/" + detail["run"]["id"],
            "/runs/" + detail["run"]["id"] + "/events",
        ]:
            assert client.get(path).status_code == 404
        candidate = next(c for c in detail["candidates"] if c["status"] == "supported")
        body = review_body(
            detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
        )
        assert client.post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 404
    finally:
        client.headers["x-workspace-id"] = ws["id"]


def test_review_permissions_and_csrf(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0002", ["material"])
    candidate = detail["candidates"][0]
    body = review_body(
        detail, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
    )
    assert (
        ws["viewer"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 403
    )
    csrf = ws["client"].headers.pop("x-csrf-token")
    try:
        assert (
            ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code
            == 403
        )
    finally:
        ws["client"].headers["x-csrf-token"] = csrf
    assert (
        ws["client"]
        .post(
            "/batches",
            json={"product_ids": [detail["product"]["id"]]},
            headers={"Origin": "https://attacker.invalid"},
        )
        .status_code
        == 403
    )


def test_approval_idempotent_and_export_only_approved(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0004", ["material", "length_mm"])
    material = next(c for c in detail["candidates"] if c["attribute_key"] == "material")
    length = next(c for c in detail["candidates"] if c["attribute_key"] == "length_mm")
    body = review_body(
        detail,
        [{"candidate_id": material["id"], "version": material["version"], "action": "approve"}],
    )
    first = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body))
    second = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body))
    assert first["id"] == second["id"]
    wait_for(ws["client"], "/review-decisions/" + first["id"], "applied")
    product = checked(ws["client"].get("/products/" + detail["product"]["id"]))
    assert product["revision"] == 2 and product["approved"] == {"material": "Nylon"}
    export_body = {"idempotency_key": str(uuid4())}
    exported = checked(ws["client"].post("/exports", json=export_body))
    assert checked(ws["client"].post("/exports", json=export_body))["id"] == exported["id"]
    archive = zipfile.ZipFile(
        io.BytesIO(ws["client"].get("/exports/" + exported["id"] + "/file").content)
    )
    import csv

    rows = list(csv.DictReader(io.StringIO(archive.read("catalog.csv").decode("utf-8-sig"))))
    row = next(row for row in rows if row["SKU"] == "CF-0004")
    assert row["Material"] == "Nylon" and row["Length"] == ""
    assert row["Legacy note"] == detail["product"]["original"]["Legacy note"]
    report = json.loads(archive.read("evidence.json"))
    assert any(entry["candidate_id"] == material["id"] for entry in report)
    assert not any(entry["candidate_id"] == length["id"] for entry in report)
    changed = {
        **body,
        "decisions": [{"candidate_id": material["id"], "version": 1, "action": "reject"}],
    }
    assert (
        ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=changed).status_code
        == 409
    )


def test_conflicts_and_populated_contradictions(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0003", ["material"])
    candidates = [c for c in detail["candidates"] if c["attribute_key"] == "material"]
    assert {c["normalized_value"] for c in candidates} == {"Nylon", "Leather"}
    assert {c["status"] for c in candidates} == {"conflicting"}
    choice = next(c for c in candidates if c["normalized_value"] == "Nylon")
    body = review_body(detail, [{"candidate_id": choice["id"], "version": 1, "action": "approve"}])
    assert (
        ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 422
    )
    body["decisions"][0]["reason"] = "Primary technical record chosen after evidence comparison"
    review = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body))
    wait_for(ws["client"], "/review-decisions/" + review["id"], "applied")
    final = wait_for(ws["client"], "/runs/" + detail["run"]["id"], "completed")
    assert sorted(c["status"] for c in final["candidates"]) == ["approved", "rejected"]
    contradicted = start_run(ws, "CF-0007", ["material"])
    candidate = next(c for c in contradicted["candidates"] if c["attribute_key"] == "material")
    assert candidate["status"] == "needs_review"
    body = review_body(
        contradicted, [{"candidate_id": candidate["id"], "version": 1, "action": "approve"}]
    )
    assert (
        ws["client"].post("/runs/" + contradicted["run"]["id"] + "/review", json=body).status_code
        == 409
    )
    assert contradicted["product"]["attributes"]["material"] == "Leather"


def test_unknowns_similar_identity_and_prompt_injection(workspace):
    ws = workspace
    unknown = start_run(ws, "CF-0036")
    assert all(
        c["status"] == "insufficient_evidence" and c["normalized_value"] is None
        for c in unknown["candidates"]
    )
    packaging = start_run(ws, "CF-0006", ["pack_quantity"])
    assert packaging["candidates"][0]["status"] == "insufficient_evidence"
    injected = start_run(ws, "CF-0010", ["certification"])
    assert injected["candidates"][0]["normalized_value"] is None
    exact = start_run(ws, "CF-0005", ["pack_quantity"])
    assert exact["candidates"][0]["normalized_value"] == 12
    assert all(
        e["identity_basis"]["kind"] == "exact" for c in exact["candidates"] for e in c["evidence"]
    )
    assert exact["run"]["metrics"]["rejected_identity_passages"] > 0


def test_manual_edit_is_validated_and_labeled(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0011", ["length_mm"])
    candidate = detail["candidates"][0]
    body = review_body(
        detail,
        [
            {
                "candidate_id": candidate["id"],
                "version": 1,
                "action": "edit",
                "value": "900 cm",
                "reason": "Manual inspection",
            }
        ],
    )
    assert (
        ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 422
    )
    body["decisions"][0]["value"] = "24 cm"
    review = checked(ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body))
    wait_for(ws["client"], "/review-decisions/" + review["id"], "applied")
    final = wait_for(ws["client"], "/runs/" + detail["run"]["id"], "completed")
    assert final["candidates"][0]["manual"] and final["candidates"][0]["normalized_value"] == 240
    assert final["product"]["evidence_coverage"] == 0


def test_duplicate_job_delivery_keeps_candidates_stable(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0012", ["material"])
    before = [c["id"] for c in detail["candidates"]]
    with SYNC_ENGINE.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO outbox (id,created_at,workspace_id,kind,entity_id,dedupe_key,payload,delivered) VALUES (:id,now(),:wid,'enrich',:run,:key,'{}',false)"
            ),
            {"id": str(uuid4()), "wid": ws["id"], "run": detail["run"]["id"], "key": str(uuid4())},
        )
    time.sleep(3)
    final = wait_for(ws["client"], "/runs/" + detail["run"]["id"])
    assert [c["id"] for c in final["candidates"]] == before
    assert final["run"]["interrupt_id"] == detail["run"]["interrupt_id"]


def test_wrong_proposal_version_and_interrupt(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0013", ["material"])
    body = review_body(
        detail, [{"candidate_id": detail["candidates"][0]["id"], "version": 2, "action": "approve"}]
    )
    assert (
        ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 409
    )
    body["decisions"][0]["version"] = 1
    body["interrupt_id"] = "wrong-interrupt"
    assert (
        ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 409
    )


def test_schema_and_source_changes_stale_proposals(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0014", ["material"])
    schema = ws["category"]["definition"]
    checked(ws["client"].put("/categories/" + ws["category"]["id"], json=schema))
    body = review_body(
        detail, [{"candidate_id": detail["candidates"][0]["id"], "version": 1, "action": "approve"}]
    )
    assert (
        ws["client"].post("/runs/" + detail["run"]["id"] + "/review", json=body).status_code == 409
    )
    fresh = start_run(ws, "CF-0015", ["material"])
    checked(
        ws["client"].post(
            "/sources",
            files={"file": ("new-evidence.txt", b"New unrelated document; no product evidence")},
        )
    )
    body = review_body(
        fresh, [{"candidate_id": fresh["candidates"][0]["id"], "version": 1, "action": "approve"}]
    )
    assert (
        ws["client"].post("/runs/" + fresh["run"]["id"] + "/review", json=body).status_code == 409
    )
    time.sleep(3)


def test_failure_retry_limits_and_cancel(workspace):
    ws = workspace
    bad = checked(
        ws["client"].post("/sources", files={"file": ("unsupported.txt", b"\x00\x00binary")})
    )
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        with SYNC_ENGINE.connect() as conn:
            state = conn.execute(
                text("SELECT status,attempts FROM procrastinate_jobs WHERE args->>'entity_id'=:id"),
                {"id": bad["id"]},
            ).one_or_none()
        if state is not None and state.status == "failed":
            break
        time.sleep(0.2)
    detail = checked(ws["client"].get("/sources/" + bad["id"]))
    assert detail["document"]["status"] == "failed" and "Binary" in detail["document"]["error"]
    with SYNC_ENGINE.connect() as conn:
        attempts = conn.execute(
            text("SELECT attempts FROM procrastinate_jobs WHERE args->>'entity_id'=:id"),
            {"id": bad["id"]},
        ).scalar_one()
        failures = conn.execute(
            text(
                "SELECT count(*) FROM workflow_events WHERE document_id=:id AND step='Processing failed'"
            ),
            {"id": bad["id"]},
        ).scalar_one()
        # Retry strategy observes prior attempts; database stores total executions.
        assert attempts == 3 and failures == 3
    run = start_run(ws, "CF-0016", ["material"])
    checked(ws["client"].post("/runs/" + run["run"]["id"] + "/cancel"))
    final = checked(ws["client"].get("/runs/" + run["run"]["id"]))
    assert final["run"]["status"] == "cancelled"


def test_composite_workspace_foreign_key(workspace):
    from sqlalchemy.exc import IntegrityError

    ws = workspace
    with pytest.raises(IntegrityError), SYNC_ENGINE.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO product_revisions (id,created_at,workspace_id,product_id,revision,values,actor_id) VALUES (:id,now(),:wid,:product,99,'{}',:actor)"
            ),
            {
                "id": str(uuid4()),
                "wid": ws["other_id"],
                "product": ws["products"]["CF-0001"]["id"],
                "actor": checked(ws["client"].get("/auth/me"))["id"],
            },
        )
