import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from catalogforge.contracts import CategoryDefinition

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("real_evaluation", ROOT / "evals/real.py")
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


def sample():
    pages = {"one": ["Material: Nylon\nGauge: 13"], "two": ["Material: Cotton"]}
    dataset = {
        "version": "test",
        "acceptance": {
            "precision": 0.95,
            "answerable_coverage": 0.8,
            "traceability": 1,
            "abstention": 0.9,
            "conflict_detection": 0.9,
            "ready_rate": 1,
        },
        "cases": [
            {
                "id": "P1",
                "source_ids": ["one", "two"],
                "expected": {
                    "material": {
                        "values": ["Nylon", "Cotton"],
                        "conflict": True,
                        "evidence": [
                            {
                                "source_id": "one",
                                "page": 1,
                                "quote": "Material: Nylon",
                                "value": "Nylon",
                            },
                            {
                                "source_id": "two",
                                "page": 1,
                                "quote": "Material: Cotton",
                                "value": "Cotton",
                            },
                        ],
                    },
                    "length_mm": {"values": [], "evidence": []},
                },
            }
        ],
    }
    observations = {
        "evaluation_kind": "controlled_evaluator_test",
        "cases": [
            {
                "id": "P1",
                "status": "waiting_review",
                "retrieved_source_ids": ["one", "two"],
                "candidates": [
                    {
                        "attribute_key": "material",
                        "normalized_value": value,
                        "status": "conflicting",
                        "evidence": [{"source_id": sid, "page": 1, "quote": f"Material: {value}"}],
                    }
                    for value, sid in [("Nylon", "one"), ("Cotton", "two")]
                ],
            }
        ],
    }
    return dataset, observations, pages


def test_known_correct_outputs_pass_and_report_denominators():
    result = evaluation.score(*sample())
    assert result["passed"]
    assert result["metrics"]["precision"] == {"numerator": 2, "denominator": 2, "value": 1}
    assert result["metrics"]["conflict_detection"]["denominator"] == 1
    assert result["evaluation_kind"] == "controlled_evaluator_test"


@pytest.mark.parametrize(
    "defect",
    [
        "wrong_value",
        "invented_quote",
        "wrong_product",
        "wrong_quote_for_value",
        "missed_conflict",
        "invented_unknown",
        "failed_run",
        "empty",
    ],
)
def test_bad_outputs_do_not_pass(defect):
    dataset, observations, pages = sample()
    case = observations["cases"][0]
    candidate = case["candidates"][0]
    if defect == "wrong_value":
        candidate["normalized_value"] = "Leather"
    elif defect == "invented_quote":
        candidate["evidence"][0]["quote"] = "An invented passage"
    elif defect == "wrong_product":
        candidate["evidence"][0]["source_id"] = "another-product"
        pages["another-product"] = ["Material: Nylon"]
    elif defect == "wrong_quote_for_value":
        candidate["evidence"] = [{"source_id": "two", "page": 1, "quote": "Material: Cotton"}]
    elif defect == "missed_conflict":
        case["candidates"] = [candidate]
        candidate["status"] = "supported"
    elif defect == "invented_unknown":
        case["candidates"].append(
            {**copy.deepcopy(candidate), "attribute_key": "length_mm", "normalized_value": 250}
        )
    elif defect == "failed_run":
        case["status"] = "failed"
    elif defect == "empty":
        case["candidates"] = []
    result = evaluation.score(dataset, observations, pages)
    assert not result["passed"], result


def test_unmeasured_conflicts_are_not_an_automatic_pass():
    dataset, observations, pages = sample()
    dataset["cases"][0]["expected"]["material"]["conflict"] = False
    result = evaluation.score(dataset, observations, pages)
    assert result["metrics"]["conflict_detection"]["value"] is None
    assert result["gates"]["conflict_detection"] is None
    assert not result["passed"]


def test_material_components_are_order_independent_but_not_optional():
    assert evaluation.equivalent("material", "Nylon, Cotton", "Cotton, Nylon")
    assert not evaluation.equivalent("material", "Nylon", "Cotton, Nylon")


def test_dataset_has_frozen_split_and_supported_schema():
    dataset = json.loads((ROOT / "evals/real/dataset-v1.json").read_text())
    CategoryDefinition.model_validate(dataset["category"])
    assert len(dataset["sources"]) == 30
    assert len(dataset["cases"]) == 30
    held = [c for c in dataset["cases"] if c["split"] == "holdout"]
    dev = [c for c in dataset["cases"] if c["split"] == "development"]
    assert len(held) == 10 and len(dev) == 20
    assert sum(len(c["expected"]) for c in dataset["cases"]) == 150
    assert not {c["family"] for c in held}.intersection(c["family"] for c in dev)
    assert all(
        s["url"].startswith("https://documents.portwest.com/") and len(s["sha256"]) == 64
        for s in dataset["sources"]
    )


def test_adversarial_sources_and_labels_validate_offline():
    dataset = json.loads((ROOT / "evals/real/adversarial-v1.json").read_text())
    CategoryDefinition.model_validate(dataset["category"])
    result = evaluation.validate(dataset, ROOT / "evals/real/adversarial-sources")
    assert (
        result["products"] == 12 and result["attribute_checks"] == 60 and result["paid_calls"] == 0
    )


def test_live_runner_rejects_main_instance_before_any_request(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network must not be reached")

    monkeypatch.setattr(evaluation.httpx, "Client", forbidden)
    with pytest.raises(ValueError, match="isolated local pilot"):
        evaluation.run_live({}, ROOT, "http://127.0.0.1:8188/api", 1)


def test_reordered_composition_is_scored_as_correct_with_bound_evidence():
    dataset, observations, pages = sample()
    label = dataset["cases"][0]["expected"]["material"]
    label["values"][0] = "Nylon, Cotton"
    label["evidence"][0]["value"] = "Nylon, Cotton"
    label["evidence"][0]["quote"] = "Material: Nylon, Cotton"
    pages["one"][0] = "Material: Nylon, Cotton"
    candidate = observations["cases"][0]["candidates"][0]
    candidate["normalized_value"] = "Cotton, Nylon"
    candidate["evidence"][0]["quote"] = "Material: Nylon, Cotton"
    assert evaluation.score(dataset, observations, pages)["passed"]
    candidate["normalized_value"] = "Nylon"
    assert not evaluation.score(dataset, observations, pages)["passed"]


def test_live_protocol_collects_nested_source_and_run_without_external_calls(monkeypatch, tmp_path):
    import httpx

    source = tmp_path / "one.txt"
    source.write_text("Material: Nylon")
    dataset = {
        "version": "protocol-test",
        "category": {},
        "sources": [
            {
                "id": "one",
                "filename": "one.txt",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        ],
        "cases": [
            {
                "id": "P1",
                "name": "Test",
                "identity": {"manufacturer": "Test", "model": "T1", "mpn": ""},
            }
        ],
    }
    imported = False
    requests = []

    def handler(request):
        nonlocal imported
        route = request.url.path.removeprefix("/api")
        requests.append((request.method, route))
        if route == "/auth/login":
            result = {
                "csrf": "test",
                "workspaces": [{"id": "workspace", "name": "AI pilot · isolated evaluation"}],
            }
        elif route == "/settings":
            result = {
                "mode": "real",
                "provider_ready": True,
                "ai_limits": {"workspace_budget_usd": 1, "pricing_configured": True},
            }
        elif route == "/products":
            result = [{"id": "product"}] if imported else []
        elif route == "/sources" and request.method == "GET":
            result = []
        elif route == "/categories":
            result = {"id": "category"}
        elif route == "/imports/preview":
            result = {"id": "import"}
        elif route == "/imports/import/confirm":
            imported = True
            result = {}
        elif route == "/sources" and request.method == "POST":
            result = {"id": "document"}
        elif route == "/sources/document":
            result = {
                "document": {"id": "document", "status": "ready"},
                "chunks": [{"id": "chunk"}],
            }
        elif route == "/batches":
            result = {"runs": [{"id": "run"}]}
        elif route == "/runs/run":
            result = {
                "run": {
                    "status": "waiting_review",
                    "available_chunks": ["chunk"],
                    "metrics": {"latency_seconds": 2},
                },
                "product": {"sku": "P1"},
                "candidates": [
                    {
                        "attribute_key": "material",
                        "normalized_value": "Nylon",
                        "status": "supported",
                        "evidence": [
                            {
                                "document_id": "document",
                                "location": {"page": 1},
                                "quote": "Material: Nylon",
                            }
                        ],
                    }
                ],
            }
        elif route == "/operations":
            result = {"provider_usage": []}
        else:
            raise AssertionError(f"Unexpected request {request.method} {route}")
        return httpx.Response(200, json=result)

    transport = httpx.MockTransport(handler)
    original = httpx.Client
    monkeypatch.setattr(
        evaluation.httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs)
    )
    monkeypatch.setenv("CATALOGFORGE_EVAL_EMAIL", "test")
    monkeypatch.setenv("CATALOGFORGE_EVAL_PASSWORD", "test-only")
    result = evaluation.run_live(dataset, tmp_path, "http://127.0.0.1:8388/api", 1)
    outcome = result["cases"][0]
    assert outcome["retrieved_source_ids"] == ["one"]
    assert outcome["candidates"][0]["evidence"][0]["source_id"] == "one"
    assert outcome["candidates"][0]["evidence"][0]["page"] == 1
    assert outcome["latency_seconds"] == 2
    assert not any(
        route.endswith("/review") or route.startswith("/review-decisions") for _, route in requests
    )


def test_live_preflight_rejects_unreadable_sources_before_http(monkeypatch, tmp_path):
    import httpx
    import pytest

    content = b"This is not a PDF"
    (tmp_path / "bad.pdf").write_bytes(content)
    dataset = {
        "sources": [
            {"id": "bad", "filename": "bad.pdf", "sha256": hashlib.sha256(content).hexdigest()}
        ]
    }

    def no_http(**kwargs):
        raise AssertionError("Preflight must complete before API calls")

    monkeypatch.setattr(httpx, "Client", no_http)
    with pytest.raises(ValueError, match="PDF header"):
        evaluation.run_live(dataset, tmp_path, "http://127.0.0.1:8388/api", 0.20)
