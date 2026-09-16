# Known limitations

- Live evaluation covered 30 unique Portwest products and 12 separate synthetic adversarial cases. Held-out real precision: 37/38 (97.4%); answerable coverage: 37/39 (94.9%). Development included adjustments; reserved sets ran once after freezing the application. See [RELEASE_REVIEW.md](RELEASE_REVIEW.md). Labels and acceptance decisions have no independent expert review. Fixture verification requires no provider key.
- The fixture provider only extracts explicitly labeled synthetic CatalogForge records. Arbitrary uploaded text can be ingested, but fixture enrichment must abstain with a limitation message.
- Identity matching is intentionally conservative. Complex multi-product tables without separable records, implicit family membership and non-verbatim identity names may need preprocessing. Ambiguous passages are rejected rather than used to fill a neighboring variant.
- PDF support is text-only, limited to 200 pages, 20 MB uploads and bounded extracted text/chunk counts. No OCR, scanned or encrypted PDFs. A PDF with both image-only and text pages is rejected when detected.
- Physical unit conversion covers the explicitly listed length and mass units. Packaging is never converted between boxes, items and pairs without explicit counts. A bare number is interpreted in the configured attribute unit.
- Model output is schema-validated, quote-checked and identity-gated, but these checks do not prove the truth of an uploaded document. Conflicting documents require human judgment.
- No cross-encoder reranker, ANN vector index or large-catalog performance evaluation. The current pgvector search is exact within a filtered embedding space. PostgreSQL lexical indexing is present.
- The interface lists up to 10,000 products. Production-scale pagination, bulk-import streaming and storage retention/garbage collection remain future work.
- Reindex and demo reset are administrative commands, run with API and worker stopped. They are not online zero-downtime maintenance operations. Reset retains old files, so unused bytes can accumulate.
- Approval staleness uses a conservative workspace source revision. An unrelated source change can require revalidation of pending proposals. Previously approved exports remain immutable historical snapshots.
- Cancellation occurs between graph nodes. A provider request already running may finish before cancellation takes effect. Invocation timeouts do not kill synchronous Python parsing midway; document size/page/text limits bound the supported input.
- The initial local account setup is deliberately small: no account-management UI, password reset, MFA, enterprise SSO, rate limiting or malware scanner. Cookies default to non-Secure for loopback HTTP; a nonlocal deployment also needs HTTPS, `COOKIE_SECURE=true`, explicit `TRUSTED_HOSTS` and `WEB_ORIGIN` values, and private account credentials.
- There is no automatic external publication, public-web crawl, CRM, orders, pricing engine, OCR or inventory management.

- Abrupt worker recovery was exercised with one real SIGKILL during approval. Heartbeat expiry plus the sweep interval can delay recovery; this local test is not an availability or production-load guarantee. Three interrupted attempts require manual attention unless the business operation already finished.
- Guided examples are fictional, per-user training workspaces and require fixture mode for installation and new runs. Reopening preserves prior decisions. Historical database-only dumps do not include uploaded file bytes. The full backup command in scripts/backup.py includes database/checkpoints and uploads; see AI_READINESS.md.

- The real evaluation corpus covers one manufacturer and one category. Labels were checked against source text and rendered pages, but have no independent expert review. Dynamically generated manufacturer PDFs may change hashes on later downloads; source versions must be preserved or reviewed and versioned again.
- Provider usage is conservatively reserved before requests; unconfirmed usage retains the reservation. Local estimates and configured prices do not guarantee an absolute billing ceiling at the provider.

- Measurement validation rejects ambiguous dimension rows and packaging context for product attributes. It is a conservative check for common labels, not proof of arbitrary semantic claims. Technical source labels with underscores (such as `length_mm`) may abstain; both live adversarial unit-conversion cases EV-105 and EV-205 were omitted. Unknown custom quantities still need reviewer judgment.
