# Experience verification — 2026-09-16

## Delivered

- Product presentation at `/product-story`, available without a session, with workflow, architecture, technical decisions, actual captures and a downloadable verification summary.
- Walkthrough at `/walkthrough`, with idempotent setup of a dedicated workspace per user, two conflicting fictional sources and a comparison of imported and approved values.
- Source inspector in review: original PDF, cited page, zoom, literal highlighting, identity context, extracted passage and download. TXT/CSV provide the original extracted passage.
- Visual history with persisted events, read-only checkpoint selection, human-interrupt state and decision reasons.
- Return to the requested route after login, including reauthentication after session expiry.

## Observed results

| Check | Result |
| --- | --- |
| pytest with a running database, API and worker | 54 passed; 100.80 s |
| Vitest | 6 passed |
| Playwright against Compose | 6 journeys passed; 44.1 s |
| Ruff lint/format | Passed; 47 files |
| mypy | Passed; 20 modules |
| Vue/TypeScript, Vite and Docker build | Passed |
| OpenAPI/TypeScript generation | Executed |
| Mobile public page | 390 px, navigation available, no horizontal overflow |
| PDF resources | Worker served as JavaScript, local maps/fonts, quotation highlighted in the actual document |

The walkthrough test covered setup, ingestion of both sources, generation of five proposals, opening the PDF, quotation matching, zoom, switching to a page without the passage, resolving two conflicts with reasons, approving length, querying events/checkpoints and preserving the before/after state across reloads.

API tests checked concurrent idempotent setup, preservation of the previous catalog, rejection of setup by a read-only user, rejection of starts in the wrong workspace, authorized checkpoint access, rejection of cross-workspace access and prevention of real mode for the demonstration.

Quotation text is not located through approximation. The interface reports when it cannot highlight a quote and when multiple occurrences exist. A dedicated test protects evidence context while the dialog is open and page shortcuts are suspended.

The presentation received an additional check after captures were added: both images loaded, navigation worked and the 390 px layout passed in 2.5 s. The separate result is in `docs/verification/experience/public-presentation.json`.

Raw records: `docs/verification/experience/pytest-experience.xml` and `playwright-results.json`. Captures: `docs/screenshots/product-story.png`, `product-story-mobile.png`, `walkthrough.png`, `pdf-evidence.png` and `execution-timeline.png`.

## Scope of public metrics

The public summary at this stage contained only aggregate results. The test total was 66: 54 backend, six unit and six browser tests. The 319 attribute cases and SIGKILL exercise were previously documented results, reused with their scope stated explicitly; they were not presented as a new model evaluation.

This verification used fixture mode. Live-model quality, production load and OCR were outside its scope. History responses are limited to the most recent 200 events and 100 checkpoints, with truncation indicated.

Existing user workspaces were preserved. Tests use their own temporary identities, removed after verification. Reopening an existing walkthrough preserves previous decisions; there is no automatic reset.
