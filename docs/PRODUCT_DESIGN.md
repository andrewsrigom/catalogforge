# CatalogForge — product and engineering decisions

## Problem and audience

Catalog teams receive fragmented information in technical datasheets, supplier tables and bulletins. An attribute may be missing, use another unit or differ between documents. Copying an extractor's answer directly into the catalog removes the opportunity to verify identity and resolve conflicts.

CatalogForge organizes this work into attribute-level proposals, each accompanied by a quoted passage, source version and explicit decision. The product supports the catalog operations workflow: import, investigate, review and export.

## Guided walkthrough

`/walkthrough` creates a separate workspace per user with one fictional Northstar product and two sources. The technical sheet and supplier disagree about material and packaging; both support the length. The walkthrough uses the normal import, ingestion, retrieval, validation and review services.

Users open the document, compare proposals, record their reasoning and inspect the before/after result. Reopening the walkthrough preserves progress. Setup and start are idempotent and restricted to fixture mode. The walkthrough makes no paid calls and does not reset existing catalogs.

## Evidence beside the decision

The inspector opens the original PDF bytes through an authenticated, workspace-scoped route. PDF.js renders the page and a selectable text layer. Highlighting searches for the quotation while normalizing only typography and whitespace; it does not use fuzzy matching to invent a location.

When a quotation occurs more than once, the interface reports the ambiguity. When the passage cannot be found, the extracted text remains available and the interface explains the missing highlight. Zoom, page navigation, original-file download and superseded-version identification complete the comparison. TXT and CSV display the extracted passage with access to the original file.

The renderer and its worker load on demand. Fonts, character maps and supporting resources are served locally, without requiring a CDN to read documents.

## Execution history

The timeline reads events and checkpoints that were actually persisted. Workspace authorization is checked before accessing LangGraph history. The API returns only checkpoint metadata, next nodes, interrupt state and decisions; it does not expose raw graph state.

Unobserved stages appear as not reached. The interface distinguishes waiting for review, recorded failures and resumptions. The counter shows worker deliveries, including continuation after human decisions. Selecting a checkpoint is read only: it neither changes nor reruns the process.

Responses are limited to 200 events and 100 checkpoints, with an indication when the view is truncated. A partial review can revisit the same node; chronological history remains visible.

## Boundaries and tradeoffs

- Imported and approved values are stored separately. Completeness is not treated as correctness.
- Conservative identity matching reduces the chance of assigning facts from a neighboring variant, at the cost of more abstentions.
- Reviews use idempotency and version checks. HTTP success means the transaction committed.
- The durable queue runs work outside the request. Approval remains visible while application proceeds in the background.
- Checkpoints preserve continuity but do not eliminate the need for idempotent business effects.
- The public `/product-story` page presents only static content and aggregate results. Catalogs, sources and history still require authentication.

## Verification and limitations

The previous local run passed 51 backend tests, four interface unit tests and four browser journeys. Deterministic datasets checked 319 attribute cases. A SIGKILL during approval was recovered without duplicating the product change. These are integration records with synthetic data; they do not measure live-model precision.

Experience-stage results are in [EXPERIENCE_VERIFICATION.md](EXPERIENCE_VERIFICATION.md). Subsequent live evaluation is recorded separately in [RELEASE_REVIEW.md](RELEASE_REVIEW.md). Scanned PDFs remain unsupported.

## Implementation references

- PDF.js: https://mozilla.github.io/pdf.js/examples/
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/persistence
- Contracts and authorization: `apps/api/catalogforge/main.py`, `contracts.py`, `auth.py`.
- Walkthrough setup: `apps/api/catalogforge/walkthrough.py`.
- History: `apps/api/catalogforge/timeline.py` and `apps/web/src/components/RunTimeline.vue`.
- Sources: `apps/web/src/components/EvidenceViewer.vue`, `PdfPage.vue` and `lib/quote-match.ts`.
