from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from conftest import checked, review_body, start_run, wait_for
from fastapi import HTTPException


def test_walkthrough_is_isolated_idempotent_and_produces_reviewable_conflicts(workspace):
    ws = workspace
    before = checked(ws["client"].get("/products"))
    assert ws["viewer"].post("/walkthrough").status_code == 403
    with ThreadPoolExecutor(max_workers=2) as pool:
        installs = list(pool.map(lambda _: checked(ws["client"].post("/walkthrough")), range(2)))
    assert installs[0]["workspace_id"] == installs[1]["workspace_id"]
    assert checked(ws["client"].get("/products")) == before
    assert ws["client"].post("/walkthrough/start").status_code == 409
    result = installs[0]
    assert len(result["sources"]) == 2
    ws["client"].headers["x-workspace-id"] = result["workspace_id"]
    try:
        import time

        for _ in range(150):
            state = checked(ws["client"].get("/walkthrough"))
            if all(s["status"] == "ready" for s in state["sources"]):
                break
            time.sleep(0.2)
        first = checked(ws["client"].post("/walkthrough/start"))
        assert checked(ws["client"].post("/walkthrough/start"))["id"] == first["id"]
        detail = wait_for(ws["client"], "/runs/" + first["id"])
        assert len([c for c in detail["candidates"] if c["status"] == "conflicting"]) == 4
        length = next(c for c in detail["candidates"] if c["attribute_key"] == "length_mm")
        assert length["status"] == "supported" and length["normalized_value"] == 250
        pdf = next(s for s in state["sources"] if s["filename"].endswith(".pdf"))
        response = ws["client"].get("/sources/" + pdf["id"] + "/file")
        assert response.status_code == 200 and response.content.startswith(b"%PDF")
        again = checked(ws["client"].post("/walkthrough"))
        assert again["run"]["id"] == first["id"]
    finally:
        ws["client"].headers["x-workspace-id"] = ws["id"]


def test_execution_timeline_is_scoped_read_only_and_tracks_decisions(workspace):
    ws = workspace
    detail = start_run(ws, "CF-0002", ["material"])
    path = "/runs/" + detail["run"]["id"] + "/timeline"
    history = checked(ws["client"].get(path))
    assert len(history["checkpoints"]) > 2
    assert history["checkpoints"][-1]["interrupted"] is True
    assert "review" in history["checkpoints"][-1]["next_nodes"]
    assert any(e["step"] == "Waiting for review" for e in history["events"])
    assert checked(ws["viewer"].get(path))["run_id"] == detail["run"]["id"]
    ws["client"].headers["x-workspace-id"] = ws["other_id"]
    assert ws["client"].get(path).status_code == 404
    ws["client"].headers["x-workspace-id"] = ws["id"]
    candidate = detail["candidates"][0]
    result = checked(
        ws["client"].post(
            "/runs/" + detail["run"]["id"] + "/review",
            json=review_body(
                detail,
                [
                    {
                        "candidate_id": candidate["id"],
                        "version": candidate["version"],
                        "action": "approve",
                        "reason": "Verified original source",
                    }
                ],
            ),
        )
    )
    wait_for(ws["client"], "/review-decisions/" + result["id"], "applied")
    wait_for(ws["client"], "/runs/" + detail["run"]["id"], "completed")
    final = checked(ws["client"].get(path))
    assert final["reviews"][0]["decisions"][0]["attribute_key"] == "material"
    assert final["reviews"][0]["decisions"][0]["reason"] == "Verified original source"
    assert final["status"] == "completed"
    assert any(e["step"] == "Workflow completed" for e in final["events"])
    assert all("values" not in point for point in final["checkpoints"])


async def test_walkthrough_never_starts_paid_calls(monkeypatch):
    from catalogforge import walkthrough

    monkeypatch.setattr(walkthrough, "settings", lambda: SimpleNamespace(ai_mode="real"))
    with pytest.raises(HTTPException) as error:
        await walkthrough.install(None, None)
    assert error.value.status_code == 409
