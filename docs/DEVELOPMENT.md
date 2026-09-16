# Development and maintenance

This guide collects CatalogForge development and administrative commands. See the [README](../README.md) for the product overview and local demonstration. Run the commands below from the repository root on Linux or WSL.

## Local Python and Node environment

Requirements: Python 3.12 or 3.13, uv, Node 24, npm and Docker Compose v2. PostgreSQL remains in a container; the API, worker and Vite run on the host.

```bash
[ -f .env ] || cp .env.example .env
uv sync --frozen
docker compose up -d --wait db
uv run python -m catalogforge.cli init
npm --prefix apps/web ci
uv run python scripts/dev.py start
uv run python scripts/wait_ready.py
```

Use `.env.example` in fixture mode for this workflow. `wait_ready.py` checks the default demo account and its five documents. Do not run local servers and the complete Compose services on the same ports simultaneously. If Compose is already running, stop `web`, `api` and `worker` before starting the local processes.

```bash
uv run python scripts/dev.py restart worker
uv run python scripts/dev.py stop
```

The launcher records PIDs and logs in `.local/`. Development uploads live in `data/uploads`; Compose uploads live in the `uploads` volume. When switching modes with the same database, transfer the files as well: database metadata does not contain document bytes.

## Tests and evaluation

Install the dependencies above and keep the database, API and worker running, all in `AI_MODE=fixture`. Tests and evaluators use the application's database and services; do not point this workflow at a live AI instance.

### Lint, types, tests and build

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -q
npm --prefix apps/web test
npm --prefix apps/web run build
```

### Browser journeys

Install the test Chromium browser:

```bash
(cd apps/web && npx playwright install chromium)
```

Prepare the disposable identity and clean it up even if a test fails:

```bash
(
  set -e
  uv run python scripts/prepare_browser.py
  trap 'uv run python scripts/cleanup_browser.py' EXIT
  npm --prefix apps/web run test:e2e
)
```

### Deterministic evaluations

```bash
mkdir -p .local
uv run python evals/evaluate.py --output .local/evaluation-fixture.json
uv run python evals/evaluate_workday.py --output .local/evaluation-workday.json
```

Evaluators use temporary accounts and workspaces; they do not apply decisions to examples in your account. These output paths preserve the versioned results. Fixtures exercise graphs, database, queue, retrieval and review rules, but **do not measure live-model quality**.

The [CI workflow](../.github/workflows/ci.yml) describes the verification sequence. Recorded local results are in the [evaluation report](RELEASE_REVIEW.md).

## API contract

Frontend types are generated from OpenAPI rather than maintained by hand:

```bash
uv run python -m catalogforge.cli openapi
npm --prefix apps/web run generate:api
```

Review changes in `apps/web/openapi.json` and `apps/web/src/api/schema.d.ts`. The interactive reference is available at [localhost:8188/api/docs](http://localhost:8188/api/docs) while the local API is running.

## Live AI configuration

The [isolated pilot guide](AI_READINESS.md#isolated-pilot) and [.env.pilot.example](../.env.pilot.example) describe credentials, limits, pricing and setup for the separate instance. Use that environment for live evaluation while keeping the everyday demonstration in fixture mode.

Selection variables are `AI_MODE`, `CHAT_MODEL`, `EMBEDDING_MODEL` and `EMBEDDING_DIMENSION`; `OPENAI_API_KEY` is supplied only to the backend. Real mode uses ChatOpenAI and OpenAIEmbeddings without silent fallback. Monetary limits also require all three prices, matching model names and a configuration date.

See the [evaluation report](RELEASE_REVIEW.md) for model measurements and known errors.

## Administrative reindexing

After changing the mode or embedding space, stop the API and worker and request reindexing. The commands below target the main Compose project; use the matching file and project name for the pilot.

```bash
docker compose stop api worker
docker compose run --rm init uv run --no-sync python -m catalogforge.cli reindex
docker compose up -d api worker
```

Chunk IDs and text are preserved; vectors are replaced in the configured space during ingestion. Pending proposals become stale and require revalidation. This operation does not provide maintenance without a write interruption. In real mode, generating new embeddings uses the provider and configured limits.

## Reset synthetic data

Reset is restricted to the fixed UUID of **ForgeWorks · Synthetic demo**. Other workspaces and users are preserved. Old files are retained; this version has no automatic orphan-file cleanup.

```bash
docker compose stop api worker
docker compose run --rm init uv run --no-sync python -m catalogforge.cli demo-reset
docker compose up -d api worker
```

Regenerate the Northstar examples with:

```bash
uv run python fixtures/generate_workday.py
```

The generated PDF and ZIP use deterministic metadata.

## Restart and recovery checks

The restart test requires a freshly reset demo and temporarily interrupts the worker:

```bash
uv run python scripts/smoke.py --compose
```

Without `--compose`, the script uses the local launcher.

The abrupt-termination test uses a temporary workspace, waits for the active queue to drain, blocks an approval and terminates only the CatalogForge worker with SIGKILL. Run it while nobody is operating the environment:

```bash
uv run python scripts/verify_recovery.py
```

It does not require a catalog reset and checks resumption with a single product change. Recovery considers heartbeats missing for more than 40 seconds and sweeps every 30 seconds. After three attempts, incomplete work receives an error for manual retry; completed results are preserved.

## Backup and restore

Follow the [recovery procedure](AI_READINESS.md#recovery), which includes the database, checkpoints, queue, documents and image identifiers. Database and files must belong to the same recovery point. Credentials, backups and external evaluation documents stay outside the code package.
