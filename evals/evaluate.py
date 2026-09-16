"""Actual fixture integration evaluation; never presented as live-model quality."""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps/api/tests"))
from catalogforge.config import settings  # noqa: E402
from catalogforge.models import Chunk, ProductRun, SourceDocument  # noqa: E402
from catalogforge.providers import PROMPT_VERSION  # noqa: E402
from conftest import SYNC_ENGINE, checked, wait_for, workspace  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="evals/results-fixture-v1.json")
    args = parser.parse_args()
    if settings().ai_mode != "fixture":
        raise SystemExit(
            "This labeled replay runner is fixture-only. Live model evaluation requires an explicitly configured, independently reviewed dataset and provider."
        )
    dataset = json.loads((ROOT / "evals/dataset-v1.json").read_text())
    context = workspace.__wrapped__()
    ws = next(context)
    started = time.perf_counter()
    try:
        batch = checked(
            ws["client"].post(
                "/batches",
                json={
                    "product_ids": [p["id"] for p in ws["products"].values()],
                    "title": "Dataset v1 evaluation",
                },
            )
        )
        details = [
            wait_for(ws["client"], "/runs/" + run["id"], timeout=90) for run in batch["runs"]
        ]
        details_by_sku = {detail["product"]["sku"]: detail for detail in details}
        counts = {
            "identity_correct": 0,
            "identity_total": 0,
            "retrieval_found": 0,
            "retrieval_expected": 0,
            "attribute_correct": 0,
            "attribute_total": 0,
            "evidence_correct": 0,
            "evidence_total": 0,
            "unsupported_proposals": 0,
            "proposals": 0,
            "abstention_correct": 0,
            "abstention_expected": 0,
            "conflicts_detected": 0,
            "conflicts_expected": 0,
        }
        per_case = []
        for case in dataset["cases"]:
            detail = details_by_sku[case["sku"]]
            with Session(SYNC_ENGINE) as db:
                run = db.get(ProductRun, detail["run"]["id"])
                retrieved = (
                    db.scalars(select(Chunk).where(Chunk.id.in_(run.available_chunks)))
                ).all()
                exact = [
                    chunk for chunk in retrieved if chunk.identifiers.get("mpn") == case["mpn"]
                ]
                for expected_source in case["expected_sources"]:
                    counts["retrieval_expected"] += 1
                    counts["retrieval_found"] += any(
                        db.get(SourceDocument, chunk.document_id).filename
                        == expected_source["filename"]
                        and all(
                            chunk.location.get(key) == value
                            for key, value in expected_source.items()
                            if key != "filename"
                        )
                        for chunk in exact
                    )
                for key, expected in case["expected"].items():
                    members = [c for c in detail["candidates"] if c["attribute_key"] == key]
                    proposed = [
                        c
                        for c in members
                        if c["normalized_value"] is not None and c["validation"].get("valid")
                    ]
                    counts["attribute_total"] += 1
                    alternatives = [expected]
                    if key in case["conflicts"]:
                        alternatives.append("Leather")
                        counts["conflicts_expected"] += 1
                        counts["conflicts_detected"] += (
                            len(
                                {
                                    c["normalized_value"]
                                    for c in members
                                    if c["status"] == "conflicting"
                                }
                            )
                            >= 2
                        )
                    if expected is None:
                        counts["abstention_expected"] += 1
                        correct = not proposed
                        counts["abstention_correct"] += correct
                    else:
                        correct = (
                            bool(proposed)
                            and all(c["normalized_value"] in alternatives for c in proposed)
                            and any(c["normalized_value"] == expected for c in proposed)
                        )
                    counts["attribute_correct"] += correct
                    for candidate in proposed:
                        counts["proposals"] += 1
                        counts["unsupported_proposals"] += expected is None
                        for evidence in candidate["evidence"]:
                            counts["identity_total"] += 1
                            counts["evidence_total"] += 1
                            chunk = db.get(Chunk, evidence["chunk_id"])
                            doc = db.get(SourceDocument, evidence["document_id"])
                            counts["identity_correct"] += (
                                chunk.identifiers.get("mpn") == case["mpn"]
                            )
                            matches_label = any(
                                doc.filename == source["filename"]
                                and all(
                                    chunk.location.get(key) == value
                                    for key, value in source.items()
                                    if key != "filename"
                                )
                                for source in case["expected_sources"]
                            )
                            counts["evidence_correct"] += bool(
                                matches_label
                                and chunk
                                and doc
                                and chunk.workspace_id == ws["id"]
                                and doc.workspace_id == ws["id"]
                                and evidence["quote"] in chunk.text
                                and evidence["document_version"] == doc.version
                                and chunk.document_id == doc.id
                            )
            per_case.append(
                {
                    "sku": case["sku"],
                    "scenario": case["scenario"],
                    "state": detail["run"]["status"],
                    "proposals": len(detail["candidates"]),
                    "latency_seconds": detail["run"]["metrics"]["latency_seconds"],
                }
            )

        def ratio(n, d):
            return round(counts[n] / counts[d], 6) if counts[d] else None

        result = {
            "evaluation_kind": "deterministic_fixture_integration",
            "not_a_live_model_quality_evaluation": True,
            "dataset_version": dataset["version"],
            "dataset_products": len(dataset["cases"]),
            "labeled_attribute_cases": counts["attribute_total"],
            "prompt_version": PROMPT_VERSION,
            "configuration": {
                "mode": "fixture",
                "chat": "deterministic-v1",
                "embedding_space": settings().embedding_space,
            },
            "metrics": {
                "product_identity_correctness": ratio("identity_correct", "identity_total"),
                "retrieval_recall": ratio("retrieval_found", "retrieval_expected"),
                "attribute_correctness": ratio("attribute_correct", "attribute_total"),
                "evidence_correctness": ratio("evidence_correct", "evidence_total"),
                "unsupported_proposal_rate": ratio("unsupported_proposals", "proposals"),
                "correct_abstention": ratio("abstention_correct", "abstention_expected"),
                "conflict_detection": ratio("conflicts_detected", "conflicts_expected"),
                "workflow_ready_for_review_rate": sum(
                    d["run"]["status"] == "waiting_review" for d in details
                )
                / len(details),
                "workflow_failure_rate": sum(d["run"]["status"] == "failed" for d in details)
                / len(details),
                "workflow_completed_after_approval_rate": None,
            },
            "counts": counts,
            "completeness": {
                "mean_required_fields_populated_percent": statistics.mean(
                    d["product"]["completeness"] for d in details
                ),
                "note": "Measured before review; separate from correctness.",
            },
            "latency": {
                "wall_seconds": round(time.perf_counter() - started, 3),
                "median_product_seconds": statistics.median(c["latency_seconds"] for c in per_case),
                "max_product_seconds": max(c["latency_seconds"] for c in per_case),
            },
            "token_usage": None,
            "model_calls": 0,
            "cost": None,
            "cost_note": "Unavailable: no provider calls or pricing configured.",
            "cases": per_case,
            "limitations": [
                "Fixture behavior is deterministic and tailored to explicit synthetic records.",
                "These fixture results do not measure live provider quality.",
                "Workflow completion after human decisions is verified separately by acceptance tests.",
            ],
        }
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2))
        print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))
    finally:
        try:
            next(context)
        except StopIteration:
            pass


if __name__ == "__main__":
    main()
