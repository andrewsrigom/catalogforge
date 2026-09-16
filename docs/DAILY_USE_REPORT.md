# CatalogForge — everyday-use improvements

Update verified on 2026-09-16. WSL project: `<project>`, distribution `Ubuntu-20.04`, branch `improve-daily-use`.

The application remained available at http://localhost:5288. The new collection is at http://localhost:5288/examples, under **Guided examples**. Existing workspaces and decisions were preserved; tests in this round used their own temporary accounts and workspaces.

## Reliability

- **Acknowledge after writing:** the API completes its transaction before returning success. This fixes the possibility of acknowledging an approval before it can be queried and ensures an error response when commit fails.
- **Concurrent approval:** two simultaneous decisions do not duplicate reviews or product changes. Resubmitting a decision preserves its idempotency key, including after communication failure.
- **Queue priority:** approvals awaiting application take priority over ingestion and new enrichment. Tasks already running are not interrupted.
- **Recovery:** the worker resumes jobs after heartbeat loss; after three abruptly interrupted attempts, it records an actionable failure instead of leaving the operation processing indefinitely. Completed results are preserved.
- **Cancellation and revalidation:** consistent lock ordering prevents deadlocks with approvals. Revalidation preserves the history of completed runs.
- **Session and navigation:** expired sessions return to login with an explanation; an old error response does not end a new session. Switching workspaces resets page state.
- **Startup and validation:** Compose waits for API health; non-finite numbers are rejected; the declared FastAPI minimum supports the transaction scope used.

## More practical review

The page supports filtering proposals by status, navigating evidence with controls or Alt + Up/Down, and closing unsupported fields through **Keep N unknown**, with explicit confirmation. These values remain unknown in the catalog.

Save state distinguishes a received decision from a change still being applied. A review completed without approvals states that no value was added. Queue errors and loading are also distinct from the empty state.

## Northstar examples

There are **12 fictional products** and **five sources**: a five-page PDF, a supplier CSV spreadsheet and three TXT bulletins. The kit includes a catalog, category schema, expected results and instructions. The PDF and ZIP have deterministic metadata and can be regenerated.

| Example | Decision practiced |
| --- | --- |
| NS-001 | Approve attributes directly supported by the datasheet |
| NS-002 | Convert 10 inches to 254 mm without changing the meaning |
| NS-003 | Compare two suppliers with material and quantity conflicts |
| NS-004 | Reject evidence for a different size/coating |
| NS-005 | Keep pairs per pack unknown when only a box count is available |
| NS-006 | Use a family statement that explicitly includes the variant |
| NS-007 | Detect a length outside the allowed range |
| NS-008 | Preserve a contradicted original value and request review |
| NS-009 | Recognize the absence of applicable evidence |
| NS-010 | Ignore malicious instructions embedded in a source |
| NS-011 | Distinguish packaging variants by their exact code |
| NS-012 | Distinguish models with nearly identical names |

Setup creates a separate workspace per account. Reopening the collection preserves previous decisions without resetting or replacing the user's catalog. Setup and new example runs require fixture mode to prevent paid calls.

## Checks performed

| Check | Result |
| --- | --- |
| Ruff lint and format | Passed; 42 files correctly formatted |
| mypy | Passed across 18 modules |
| OpenAPI → TypeScript | Types regenerated |
| Vue/TypeScript + Vite build | Passed |
| Vitest | **4 tests passed** |
| pytest with a running PostgreSQL, API and worker | **51 tests passed**, 86.49 s |
| Playwright against the running application | **4 journeys passed**, 44.8 s |
| Original dataset | **300/300 attribute cases**, 229/229 evidence checks and 76/76 correct abstentions |
| New Northstar collection | **19/19 checks** across 12 products; 17 evidence links verified |
| Actual worker termination during approval | **Recovered from SIGKILL**, change applied once, product revision equal to 2, two queue attempts |

Browser journeys cover import, ingestion, conflict, approval and export; tablet layout without overflow; new examples and keeping unknown fields empty; and session expiry with reauthentication. The final browser run took place alongside evaluation of a 50-product batch. This exercises the workflow under concurrent work but is not a load benchmark.

In the crash exercise, a transaction was blocked while applying an approval and the worker was terminated with SIGKILL. After restart, the checkpoint and proposal were preserved, with one audited change. Recovery took **70.87 seconds** in this exercise, including heartbeat expiry and the sweep window.

Raw results are in `docs/verification/daily/`, `evals/results-fixture-daily.json` and `evals/results-workday-v1.json`. Captures are in `docs/screenshots/`. Reproduction commands are available through the [development guide](DEVELOPMENT.md) and verification scripts. CI was extended to include examples and the abrupt-termination test.

## Getting started

1. Sign in at http://localhost:5288 using the provided local demonstration account.
2. Open **Guided examples**, then **Open example workspace**. For a new account, use **Set up guided examples** and wait for the five sources.
3. Start with NS-001, compare suppliers in NS-003 and practice keeping unknown fields empty in NS-005. Cards explain the expected behavior; previous decisions remain recorded.
4. Use **Download example kit** to download all files or **Read sample datasheets** to open the PDF.

## Limits of this verification

Both evaluations use deterministic synthetic data. They measure integration and recovery, not live-model quality or production-scale performance.

Validation focused on everyday local use. OCR, enterprise user management, large-catalog pagination and automatic file cleanup remained outside this version; see `docs/LIMITATIONS.md`.

A backup of the database before these changes was preserved at `.local/backups/before-daily-use.dump`, outside the code ZIP. It contains the database but not uploaded file bytes; it does not replace a combined database/storage backup. Temporary test accounts and workspaces were removed after execution.
