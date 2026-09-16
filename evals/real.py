"""Validate, run and score a labeled real-document evaluation. No calls by default."""

import argparse
import csv
import hashlib
import io
import json
import os
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx
from catalogforge.domain import pdf_header_present
from catalogforge.ingestion import extract_sections
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]


def canonical(value):
    if isinstance(value, str):
        return " ".join(value.casefold().split())
    return value


def equivalent(attribute, left, right):
    if attribute == "material" and isinstance(left, str) and isinstance(right, str):
        return {canonical(v) for v in left.split(",")} == {canonical(v) for v in right.split(",")}
    return canonical(left) == canonical(right)


def read_pages(path):
    if path.suffix == ".pdf":
        return [page.extract_text() or "" for page in PdfReader(path).pages]
    return [path.read_text()]


def validate(dataset, corpus):
    sources = {source["id"]: source for source in dataset["sources"]}
    assert len(sources) == len(dataset["sources"]), "Duplicate source IDs"
    pages = {}
    for source in sources.values():
        path = (corpus / source["filename"]).resolve()
        assert path.is_relative_to(corpus.resolve()), "Source escapes corpus directory"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == source["sha256"], (
            f"Source changed: {source['id']}"
        )
        pages[source["id"]] = read_pages(path)
    families = {}
    ids = set()
    checks = Counter()
    for case in dataset["cases"]:
        assert case["id"] not in ids, "Duplicate case ID"
        ids.add(case["id"])
        family = case["family"]
        assert families.get(family, case["split"]) == case["split"], (
            "Product family crosses development/holdout"
        )
        families[family] = case["split"]
        for attribute, label in case["expected"].items():
            checks[case["split"]] += 1
            assert label["values"] or label.get("absence_reason"), (
                f"Missing absence annotation: {case['id']}/{attribute}"
            )
            for proof in label["evidence"]:
                assert proof["source_id"] in case["source_ids"]
                passage = pages[proof["source_id"]][proof["page"] - 1]
                assert canonical(proof["quote"]) in canonical(passage), (
                    f"Quote not found: {case['id']}/{attribute}"
                )
            assert not label["values"] or label["evidence"], "Answerable label needs evidence"
    return {
        "sources": len(sources),
        "products": len(ids),
        "attribute_checks": sum(checks.values()),
        "checks_by_split": dict(checks),
        "paid_calls": 0,
    }


def score(dataset, observations, pages):
    expected_ids = {case["id"] for case in dataset["cases"]}
    actual = {case["id"]: case for case in observations["cases"]}
    assert set(actual) == expected_ids and len(actual) == len(observations["cases"]), (
        "Every selected case must have exactly one outcome"
    )
    counts = Counter()
    per_case = []
    for case in dataset["cases"]:
        result = actual[case["id"]]
        eligible = [
            c
            for c in result["candidates"]
            if c["status"] in {"supported", "conflicting", "approved"}
            and not c.get("manual", False)
        ]
        counts["excluded_candidates"] += len(result["candidates"]) - len(eligible)
        counts["proposals"] += len(eligible)
        counts["runs"] += 1
        counts["ready_runs"] += result["status"] in {"waiting_review", "completed"}
        counts["failed_runs"] += result["status"] == "failed"
        matched = {}
        for index, candidate in enumerate(eligible):
            label = case["expected"].get(candidate["attribute_key"])
            value_ok = bool(
                label
                and any(
                    equivalent(candidate["attribute_key"], candidate["normalized_value"], value)
                    for value in label["values"]
                )
            )
            proofs = candidate.get("evidence", [])
            identity_ok = bool(proofs) and all(
                p.get("source_id") in case.get("applicable_source_ids", case["source_ids"])
                for p in proofs
            )
            traceable = bool(proofs) and all(
                p.get("source_id") in pages
                and 1 <= p.get("page", 0) <= len(pages[p["source_id"]])
                and bool(p.get("quote"))
                and canonical(p["quote"]) in canonical(pages[p["source_id"]][p["page"] - 1])
                for p in proofs
            )
            supports = bool(label) and any(
                expected["source_id"] == proof.get("source_id")
                and expected["page"] == proof.get("page")
                and canonical(expected["quote"]) in canonical(proof.get("quote", ""))
                for expected in label["evidence"]
                if equivalent(
                    candidate["attribute_key"], candidate["normalized_value"], expected["value"]
                )
                for proof in proofs
            )
            correct = bool(value_ok and identity_ok and traceable and supports)
            matched[index] = correct
            counts["correct_proposals"] += correct
            counts["wrong_identity"] += not identity_ok
            counts["traceable_proposals"] += traceable
            counts["correct_evidence"] += bool(identity_ok and traceable and supports)
            counts["unsupported_proposals"] += not (
                identity_ok and traceable and supports and value_ok
            )
        for attribute, label in case["expected"].items():
            indexes = [i for i, c in enumerate(eligible) if c["attribute_key"] == attribute]
            counts["attribute_checks"] += 1
            if label["values"]:
                counts["answerable_fields"] += 1
                counts["correctly_covered_fields"] += any(matched[i] for i in indexes)
            else:
                counts["unknown_fields"] += 1
                counts["correct_abstentions"] += not indexes
            if label.get("conflict"):
                counts["expected_conflicts"] += 1
                values = {
                    str(canonical(eligible[i]["normalized_value"]))
                    for i in indexes
                    if eligible[i]["status"] == "conflicting" and matched[i]
                }
                counts["detected_conflicts"] += len(values) >= len(label["values"])
        relevant = {
            proof["source_id"] for label in case["expected"].values() for proof in label["evidence"]
        }
        counts["retrieval_expected"] += len(relevant)
        counts["retrieval_found"] += len(
            relevant.intersection(result.get("retrieved_source_ids", []))
        )
        per_case.append(
            {
                "id": case["id"],
                "status": result["status"],
                "proposals": len(eligible),
                "correct": sum(matched.values()),
                "error": result.get("error"),
            }
        )

    def metric(num, den):
        return {
            "numerator": counts[num],
            "denominator": counts[den],
            "value": counts[num] / counts[den] if counts[den] else None,
        }

    metrics = {
        "precision": metric("correct_proposals", "proposals"),
        "answerable_coverage": metric("correctly_covered_fields", "answerable_fields"),
        "evidence_correctness": metric("correct_evidence", "proposals"),
        "traceability": metric("traceable_proposals", "proposals"),
        "unsupported_proposal_rate": metric("unsupported_proposals", "proposals"),
        "abstention": metric("correct_abstentions", "unknown_fields"),
        "conflict_detection": metric("detected_conflicts", "expected_conflicts"),
        "retrieval_recall": metric("retrieval_found", "retrieval_expected"),
        "ready_rate": metric("ready_runs", "runs"),
        "failure_rate": metric("failed_runs", "runs"),
    }
    gates = {
        key: None if metrics[key]["value"] is None else metrics[key]["value"] >= target
        for key, target in dataset["acceptance"].items()
    }
    gates["identity"] = counts["wrong_identity"] == 0 and counts["proposals"] > 0
    latency = [
        c["latency_seconds"] for c in observations["cases"] if c.get("latency_seconds") is not None
    ]
    return {
        "evaluation_kind": observations["evaluation_kind"],
        "dataset_version": dataset["version"],
        "metrics": metrics,
        "counts": dict(counts),
        "gates": gates,
        "passed": all(value is True for value in gates.values()),
        "unmeasured": [key for key, value in gates.items() if value is None],
        "cases": per_case,
        "configuration": observations.get("configuration"),
        "usage": observations.get("usage"),
        "latency_median_seconds": statistics.median(latency) if latency else None,
        "note": "Scores are measured before human review. Null metrics are not passes. A small single-manufacturer corpus does not establish general model quality.",
    }


def selected_dataset(dataset, split, limit):
    cases = [case for case in dataset["cases"] if case["split"] == split]
    if limit:
        cases = cases[:limit]
    assert cases, "No selected cases"
    ids = {source for case in cases for source in case["source_ids"]}
    return {**dataset, "cases": cases, "sources": [s for s in dataset["sources"] if s["id"] in ids]}


def preflight_sources(dataset, corpus):
    for source in dataset["sources"]:
        path = (corpus / source["filename"]).resolve()
        if not path.is_relative_to(corpus.resolve()):
            raise ValueError("Source escapes corpus directory")
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != source["sha256"]:
            raise ValueError("Source content changed: " + source["id"])
        kind = path.suffix.lstrip(".")
        if kind not in {"pdf", "csv", "txt"} or len(content) > 20 * 1024 * 1024:
            raise ValueError("Unsupported evaluation source: " + source["id"])
        if kind == "pdf" and not pdf_header_present(content):
            raise ValueError("Invalid PDF header: " + source["id"])
        # Match the ingestion parser, including encrypted/scanned and page limits.
        sections = extract_sections(content, kind)
        if len(sections) > 300 or sum(len(s["text"]) for s in sections) > 1_000_000:
            raise ValueError("Evaluation source exceeds ingestion limits: " + source["id"])


def run_live(dataset, corpus, base_url, allowed_usd):
    if base_url.rstrip("/") != "http://127.0.0.1:8388/api":
        raise ValueError("This runner targets only the isolated local pilot on port 8388")
    preflight_sources(dataset, corpus)
    client = httpx.Client(base_url=base_url, timeout=45)

    def checked(response):
        response.raise_for_status()
        return response.json()

    def wait(path, document=False):
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            result = checked(client.get(path))
            status = result["document"]["status"] if document else result["run"]["status"]
            if status in (
                {"ready", "failed"}
                if document
                else {"waiting_review", "completed", "failed", "cancelled"}
            ):
                return result
            time.sleep(0.5)
        raise TimeoutError(
            "Pilot did not settle within 600 seconds; inspect its queue before retrying"
        )

    try:
        session = checked(
            client.post(
                "/auth/login",
                json={
                    "email": os.environ["CATALOGFORGE_EVAL_EMAIL"],
                    "password": os.environ["CATALOGFORGE_EVAL_PASSWORD"],
                },
            )
        )
        workspace = next(
            w for w in session["workspaces"] if w["name"] == "AI pilot · isolated evaluation"
        )
        client.headers.update({"x-workspace-id": workspace["id"], "x-csrf-token": session["csrf"]})
        config = checked(client.get("/settings"))
        if config["mode"] != "real" or not config["provider_ready"]:
            raise ValueError("Configure the real provider in the isolated pilot")
        limit = config["ai_limits"]["workspace_budget_usd"]
        if not limit or not config["ai_limits"]["pricing_configured"] or float(limit) > allowed_usd:
            raise ValueError(
                "The configured, priced workspace budget must not exceed the explicitly authorized amount"
            )
        if checked(client.get("/products")) or checked(client.get("/sources")):
            raise ValueError(
                "Use an empty isolated evaluation workspace; do not overwrite prior evaluation data"
            )
        category = checked(client.post("/categories", json=dataset["category"]))
        stream = io.StringIO()
        writer = csv.DictWriter(stream, fieldnames=["sku", "name", "manufacturer", "model", "mpn"])
        writer.writeheader()
        for case in dataset["cases"]:
            writer.writerow({"sku": case["id"], "name": case["name"], **case["identity"]})
        preview = checked(
            client.post(
                "/imports/preview",
                files={"file": ("real-evaluation.csv", stream.getvalue().encode())},
            )
        )
        checked(
            client.post(
                f"/imports/{preview['id']}/confirm",
                json={
                    "category_id": category["id"],
                    "mapping": {name: name for name in writer.fieldnames},
                },
            )
        )
        documents = {}
        chunk_sources = {}
        for source in dataset["sources"]:
            uploaded = checked(
                client.post(
                    "/sources",
                    files={
                        "file": (source["filename"], (corpus / source["filename"]).read_bytes())
                    },
                )
            )
            detail = wait("/sources/" + uploaded["id"], document=True)
            if detail["document"]["status"] != "ready":
                raise ValueError("Source ingestion failed: " + str(detail["document"].get("error")))
            documents[uploaded["id"]] = source["id"]
            for chunk in detail["chunks"]:
                chunk_sources[chunk["id"]] = source["id"]
        products = checked(client.get("/products"))
        batch = checked(
            client.post(
                "/batches",
                json={
                    "product_ids": [p["id"] for p in products],
                    "title": "Real document evaluation " + dataset["version"],
                },
            )
        )
        outcomes = []
        for run in batch["runs"]:
            detail = wait("/runs/" + run["id"])
            current = detail["run"]
            candidates = []
            for candidate in detail["candidates"]:
                candidates.append(
                    {
                        **candidate,
                        "evidence": [
                            {
                                **proof,
                                "source_id": documents.get(proof["document_id"]),
                                "page": proof["location"].get("page", 1),
                            }
                            for proof in candidate["evidence"]
                        ],
                    }
                )
            outcomes.append(
                {
                    "id": detail["product"]["sku"],
                    "status": current["status"],
                    "error": current.get("error"),
                    "candidates": candidates,
                    "retrieved_source_ids": sorted(
                        {
                            chunk_sources[c]
                            for c in current["available_chunks"]
                            if c in chunk_sources
                        }
                    ),
                    "latency_seconds": current["metrics"].get("latency_seconds"),
                }
            )
        return {
            "evaluation_kind": "live_provider_quality",
            "created_at": datetime.now(UTC).isoformat(),
            "configuration": config,
            "cases": outcomes,
            "usage": checked(client.get("/operations")),
        }
    finally:
        client.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["validate", "score", "run"])
    parser.add_argument("--dataset", type=Path, default=ROOT / "evals/real/dataset-v1.json")
    parser.add_argument("--corpus", type=Path, default=ROOT / ".local/real-corpus")
    parser.add_argument("--split", choices=["development", "holdout"], default="development")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--observations", type=Path)
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".local/readiness/real-validation.json"
    )
    parser.add_argument("--allow-paid-usd", type=float)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text())
    validation = validate(dataset, args.corpus)
    if args.command == "validate":
        result = validation
    else:
        dataset = selected_dataset(dataset, args.split, args.limit)
        pages = {s["id"]: read_pages(args.corpus / s["filename"]) for s in dataset["sources"]}
        if args.command == "run":
            if args.allow_paid_usd is None or not 0 < args.allow_paid_usd < float("inf"):
                parser.error("Live execution requires an explicit positive --allow-paid-usd budget")
            observations = run_live(
                dataset, args.corpus, "http://127.0.0.1:8388/api", args.allow_paid_usd
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.with_suffix(".observations.json").write_text(
                json.dumps(observations, indent=2)
            )
        else:
            if not args.observations:
                parser.error("Scoring requires --observations")
            observations = json.loads(args.observations.read_text())
        result = score(dataset, observations, pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            result
            if args.command == "validate"
            else {
                "output": str(args.output),
                "passed": result["passed"],
                "evaluation_kind": result["evaluation_kind"],
            }
        )
    )


if __name__ == "__main__":
    main()
