# Initial delivery verification — 2026-09-16

Historical record of the first delivery. See [DAILY_USE_REPORT.md](DAILY_USE_REPORT.md) for the state and tests following everyday-use improvements.

## Observed deployment

CatalogForge was running in WSL through Docker Compose: web, API, an independent worker and PostgreSQL 16 with pgvector. The final installation started from fresh volumes, applied the Alembic migration and initialized checkpoints and the queue. Interface: **http://localhost:5288**; API: **http://localhost:8188/api/docs**.

State left for use: **50 products, five ready sources and six products awaiting review**. The temporary workspace used by the browser test was removed after verification.

Repository: `<project>`, distribution `Ubuntu-20.04` (internally Ubuntu 24.04), branch `main`. Local ports: web 5288, API 8188 and PostgreSQL 5488.

Local demonstration credentials: `reviewer@catalogforge.local` / `CatalogForge-demo-2026!`. The `viewer@catalogforge.local` account uses the same password and has read-only access.

## Implemented

- CSV import with preview, mapping and preservation of original rows; versioned glove category and an editor for attributes, aliases, units and constraints.
- Actual LangGraph ingestion of text-based PDFs, TXT and CSV; versioned sources, hashes, pages/rows/sections and embeddings separated by space.
- LangChain retriever with MPN/manufacturer/model, lexical search and pgvector; conservative identity matching before structured extraction and citation validation.
- Per-product graphs, PostgreSQL checkpoints, Procrastinate queue, outbox, bounded retries, cancellation, resumption, partial review and revalidation of stale proposals.
- Review with conflict comparison, field-level evidence, individual/bulk approval, rejection and explicitly labeled manual editing; CSV export plus JSON report in a ZIP.
- Local authentication, server-side sessions, Argon2id, CSRF, workspace authorization and review permissions; ten Vue pages reflecting actual work states.
- Configurable live OpenAI provider and explicitly identified fixture mode, with no silent fallback between modes.

## Checks performed

| Check | Observed result |
| --- | --- |
| Ruff lint and format | Passed |
| mypy | Passed; 17 backend modules |
| OpenAPI → TypeScript generation | Completed successfully |
| Strict TypeScript + Vite production build | Passed |
| Vitest | 1 test passed |
| pytest with running PostgreSQL + pgvector, API and worker | **40 passed**, 56.89 s |
| Playwright against Compose | **2 passed**, 16.2 s |
| Compose smoke test | 6 products completed; conflict resolved, review idempotent, export downloaded |
| Worker restart while awaiting review | PID changed; interrupt ID and proposal count preserved; approval resumed and completed |
| Browser | Import → ingestion → enrichment → evidence → conflict → approval → export; schema update and source navigation verified |
| Tablet | 820 px viewport; navigation available with no horizontal overflow |
| Maintenance | Idempotent seed; reindex preserved chunk IDs; reset preserved the other workspace and its data |
| Docker images / fresh volumes | Build, migrations, seed, ingestion and running services |

The suite covers search/file/event/resumption isolation, permissions, CSRF, versions and stale proposals, duplicate uploads and jobs, normalization, field preservation, rejection of another product's evidence, unknown packaging, manual editing, failures and attempt limits, malicious instructions in sources and export of original/approved values only. Live-provider failure is simulated in the test; no paid call occurred.

Reproduction commands are available through the [development guide](DEVELOPMENT.md), `scripts/smoke.py`, `scripts/verify_maintenance.py`, the pytest suite and `apps/web/tests/journey.spec.ts`. Maintenance verification resets the synthetic workspace and must run while no user operations are in progress.

## Deterministic evaluation performed

Versioned dataset `1.0`: **50 products, 300 attribute cases**. Prompt `catalogforge-extraction-v1`; chat `deterministic-v1`; embeddings `fixture:hash-v1:64`.

| Metric | Result |
| --- | --- |
| Correct identity of proposed evidence | 229/229 |
| Retrieval of expected sources/locations | 46/46 |
| Correct attributes or expected abstentions | 300/300 |
| Evidence with the correct source/location/passage | 229/229 |
| Proposals without expected support | 0/225 |
| Abstention when information was missing | 76/76 |
| Expected conflicts detected | 1/1 |
| Workflows available for review | 50/50 |
| Failures in this evaluation | 0/50 |

Batch processing time measured by the evaluator: **13.083 s**; median per product: **0.283 s**; maximum: **0.484 s**. These are local measurements, not a load benchmark. Dataset preparation and ingestion happen before the batch timer starts.

Average required-field completeness before review: **33.634%**, counted separately from correctness. Completion after a human decision was verified in the six-product smoke test and browser journey; the 50-product evaluation stops at review and records that completion rate as unavailable.

**These results demonstrate deterministic integration; they do not demonstrate live-model quality.** There were no model calls, token usage or configured prices. Tokens and cost are unavailable in the JSON, without an invented cost estimate. Full results are in `evals/results-fixture-v1.json`.

## Not performed and limitations

- Live-model quality and live OpenAI calls were not evaluated; no paid key was used.
- No production-load exercise, OCR, large-scale evaluation of real documents or external publication.
- Identity matching and table reading are conservative; the fixture provider extracts only explicitly recognized synthetic records. Arbitrary text does not receive fabricated enrichment.
- No enterprise identity management, large-catalog pagination or automatic orphan-file cleanup. See `docs/LIMITATIONS.md`.

## Actual captures

- `docs/screenshots/review-conflict.png`: Nylon/Leather conflict, proposal comparison and quoted passage.
- `docs/screenshots/overview.png`: indicators calculated from persisted synthetic workspace state.
- `docs/screenshots/tablet.png`: catalog at tablet viewport size.

Absolute paths in historical reports were normalized to `<project>` and `<home>` during distribution preparation. Results and counts were preserved.
