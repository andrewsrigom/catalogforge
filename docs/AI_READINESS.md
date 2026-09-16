# AI operations

Configuration, usage accounting and backup/restore for local installations. Measured model results are in the [evaluation report](RELEASE_REVIEW.md).

## Recovery

Run from the repository root in WSL:

```sh
uv run python scripts/backup.py create --output .local/backups/full-YYYYMMDD
uv run python scripts/backup.py restore --source .local/backups/full-YYYYMMDD --project catalogforge-restore-check-YYYYMMDD --port 8288
```

The create command stops web, API and worker, then restores only services that were previously running. No other process should write to the database or storage during that window. The private package includes a PostgreSQL dump, checkpoints, queue, documents, hashes, counts and exact API/worker image IDs. It contains installation data and sessions: keep it in private storage. It does not include `.env`, a provider key or a configuration password file.

Restore requires a new Docker project, verifies hashes, rejects unsafe paths and restores the database and files into dedicated volumes. It compares the inventory before exposing the API. The worker remains stopped for inspection; start that restored project's service only when you intend to resume its jobs. The copy is forced to fixture mode and receives no API key, so it makes no paid calls. Restarting originally live extractions in that copy requires an explicit configuration decision; persisted reviews can be inspected without a provider.

Preserve the images identified in the manifest. To recover on another machine, transfer them with `docker save`/`docker load` alongside the backup directory. The script fails if the exact images are unavailable; it does not silently substitute the latest version. In an installation using the prepared isolated Docker configuration, use `DOCKER_CONFIG=.local/docker`.

## Diagnostics and usage

Settings shows the worker heartbeat, queues and failures for the selected workspace. Pending-item age starts at creation; after manual retry, it does not represent only the latest attempt's waiting time. Per-run history remains available.

Each live identification, extraction or embedding call reserves tokens and, when configured, cost before contacting the provider. Two reservations are applied atomically: one for the workspace and one for the enrichment batch or ingestion document. Row locks serialize concurrency; job retries retain the same limits. Calls with confirmed usage reconcile their reservations; failures, interruptions and crashes without a response retain conservative accounting. Attempts count even when they fail.

Limits are frozen when each budget is created. Changing `.env` does not erase reservations or silently increase an existing budget. The application provides no usage-reset button. When a pilot exhausts its limits, review the report and authorize a new round separately.

Input estimates use UTF-8 bytes plus a chat-framing allowance; they are deliberately conservative, not measurements of billed tokens. Output has an explicit provider limit. Internal SDK retries are disabled: each application-controlled attempt receives its own reservation. Per-call and per-delivery duration remains bounded. Cancellation does not undo a remote request already sent.

For USD costs, configure all three per-million-token prices, exact model names and the pricing date. Without prices, monetary cost is unavailable; token and call limits still apply. The local counter does not replace provider limits or invoices and does not promise an absolute billing cap. Do not send keys through chat or record raw provider error responses; the interface receives sanitized codes.

## Isolated pilot

```sh
cp .env.pilot.example .env.pilot
docker compose -f compose.pilot.yaml up -d --wait db init api web
```

This instance uses its own database and files, API at `http://localhost:8388` and web at `http://localhost:5388`. The everyday instance remains on 5288/8188. The initializer creates only an empty workspace and `pilot@catalogforge.local`, using `DEMO_PASSWORD` from `.env.pilot`. It imports no examples and creates no jobs. The worker belongs to the `live` profile and stays off by default.

Before starting the `live` profile, configure the key locally, check models/prices and set the call, token and cost limits. There is no silent fallback from real to fixture. Separation is by instance because `AI_MODE` is application configuration. Follow the [administrative reindexing procedure](DEVELOPMENT.md#administrative-reindexing) when changing the model or dimension; do not mix vector spaces.

## Evaluation datasets

The versioned real dataset is in `evals/real/dataset-v1.json`: 30 Portwest glove models, 30 original datasheets and 150 checks. It contains 20 development models and 10 held-out validation models, keeping related families on the same side. Cached PDFs live in `.local/real-corpus`; original third-party files are not included in the code package. The dataset records URLs and hashes.

Labels were checked against source text and rendered pages. They were not derived from provider outputs and have not received specialist human review. An unlabeled number remains unknown; carton dimensions and cuff extension are not equivalent to overall glove length. Material composition can vary in order, but missing components are not accepted. When a liner has multiple layers, each permitted gauge requires its own citation.

```sh
uv run python evals/real.py validate
uv run python evals/fetch_real_sources.py
uv run python evals/real.py validate --dataset evals/real/adversarial-v1.json --corpus evals/real/adversarial-sources --output .local/adversarial-validation.json
```

The downloader preserves existing versions and verifies hashes. The manufacturer generates datasheets dynamically and includes the date; future downloads may differ. If this happens, preserve the pinned cache or review/version a new dataset. Never accept different bytes as the same version.

The `adversarial-v1.json` supplement contains 12 fictional products and 60 checks: direct support, conflict, unknown values, wrong variants, unit conversion and malicious instructions. Its results must be reported separately from real documents.

The `evals/real.py run` executor requires `--allow-paid-usd` and local login credentials in `CATALOGFORGE_EVAL_EMAIL`/`CATALOGFORGE_EVAL_PASSWORD`. It accepts only the isolated API on 8388, requires real mode, configured prices and budgets, and an empty evaluation workspace. Start with `--split development --limit 1`; the held-out set should run only after configuration is frozen. Do not tune prompts on held-out validation and then present it as independent.

For a separate evaluation round, preserve results and stop the previous pilot with `docker compose -f compose.pilot.yaml down` (without `--volumes`). Start a newly named project with `docker compose -p catalogforge-pilot-round2 -f compose.pilot.yaml up -d --wait db init api web`; the different name creates separate volumes. Review the key, prices and budget before starting that new project's worker. Final validation should use another empty project with frozen configuration.

The executor preserves observations and a report without automatically approving values. The `score --observations ...` command works offline. Precision, coverage, evidence, abstention, conflicts, recovery and failures remain separate and include numerators/denominators. Metrics without examples are unevaluated. Perfect fixture results, or abstaining from every proposal, do not establish AI quality.

References: [PostgreSQL logical backup](https://www.postgresql.org/docs/16/backup-dump.html), [ChatOpenAI integration](https://docs.langchain.com/oss/python/integrations/chat/openai), [LangChain evaluation](https://docs.langchain.com/langsmith/evaluation-concepts), [public Portwest documentation](https://portwest.com/declarations).
