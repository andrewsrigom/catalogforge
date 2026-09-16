# Provider controls verification

Recorded on 2026-09-16 using simulated provider responses. Live-model measurements are reported separately in [RELEASE_REVIEW.md](RELEASE_REVIEW.md).

## Controls checked

- Consistent backup of PostgreSQL, checkpoints and uploads, with a manifest, hashes and pinned runtime images. Restore requires a new project, uses dedicated volumes and starts with the worker stopped in fixture mode.
- Settings displays worker heartbeat, queue, wait time, failures and usage for the authorized workspace.
- Live identification, extraction and embedding calls reserve calls/tokens/cost before execution. Budgets persist per workspace and batch/document, including under concurrency and retries. Prices are configurable and bound to model/date; unconfirmed usage retains its reservation.
- Isolated pilot on 5388/8388 with its own database and files, no examples, no key and no active worker. The everyday application remains in fixture mode on 5288/8188.
- Real dataset with 30 Portwest glove models, 30 datasheets and 150 checks: 20 products/100 checks for development; 10 products/50 checks held out. Related families stay in the same set.
- Separate adversarial supplement with 12 fictional products, 14 sources and 60 checks. It covers conflict, missing information, wrong variants, unit conversion and malicious instructions.
- Offline evaluator and an executor restricted to the isolated pilot. Live execution requires an explicit budget, prices, credentials and an empty workspace; it does not approve proposals automatically.

## Verification evidence

| Check | Result |
| --- | --- |
| Python: domain, API, concurrency, provider and evaluation | 84 tests passed |
| Interface components/utilities | 6 tests passed |
| Complete browser journeys | 6 tests passed |
| Automated total | **96 tests passed** |
| Ruff, formatting, mypy, web types/build and Docker images | Passed |
| Real corpus | 30 hashes and 150 labels/quotations validated; all PDFs read by the application parser |
| Pilot | Empty workspace, real mode without credentials, zero recorded calls, worker off |
| Final backup and restore | Matching database inventory; 22 document hashes verified |
| Restored review continuity | Checkpoint loaded, decision applied and product revision incremented once |
| Everyday-instance preservation | Original product, candidates and run unchanged before/after the exercise |

Tests cover concurrent limits and reservation persistence, idempotent reconciliation, every provider operation, authentication failure, rate limits, timeout, connection failure, HTTP 503, malformed responses and cancellation. The evaluator was exercised with known correct/incorrect cases and simulated HTTP transport, including actual source and run object formats. These tests verify controls and evaluation; they do not measure LLM quality.

The six browser journeys checked import → ingestion → conflict → review → export; tablet navigation; guided examples; session expiry; desktop/mobile presentation; and the walkthrough with original PDF and checkpoints. Diagnostics and the pilot were also inspected in the browser, with no observed page errors. Disposable browser-suite workspaces were removed; user catalogs were preserved.

## Operations and files

[AI_READINESS.md](AI_READINESS.md) contains backup, restore, pilot and evaluation commands. The baseline scope is in [READINESS_PLAN.md](READINESS_PLAN.md). Results, versions and hashes are in [verification/readiness/results.json](verification/readiness/results.json); the Python test record is `verification/readiness/pytest.xml`.

In the verified installation, the private backup is at `.local/backups/ready-final` and the restoration exercise at `.local/restores/catalogforge-restore-ready-final`. Exercise containers were stopped after inspection; their volumes were preserved. The backup was captured before the final commit and records this in its manifest alongside the exact verified image IDs. Database, sessions, uploaded files, `.env` and keys are not distributed in the code ZIP.

Original manufacturer PDFs remain in the private `.local/real-corpus` cache. Their first pages were visually inspected and each quotation checked against the original text. Some datasheets have recoverable header/xref warnings; original bytes and hashes were preserved, and the parser accepted all 30 sources. Dynamic sources may change on future downloads: the downloader rejects changes, which require review and a new version.

## Evaluation scope

The corpus covers one category and one manufacturer. Labels have not received specialist human review. The fictional supplement has separate results. Metrics without examples remain unevaluated; total abstention does not satisfy the required coverage. The local counter uses conservative reservations and configured prices; it does not guarantee an absolute provider billing cap.
