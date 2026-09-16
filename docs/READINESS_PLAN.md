# Provider integration baseline

The preparation stage established the following controls before live evaluation:

- Database, checkpoint and document backup with isolated restoration and resumption.
- Worker, queue and failure diagnostics scoped to the selected workspace.
- Persistent call, token and cost reservations, including concurrent and retried operations.
- A separate pilot instance with dedicated storage and a worker disabled by default.
- Versioned source URLs, hashes and labels for 30 real documents, with a development/held-out split.
- Evaluator checks using known correct/incorrect cases without provider calls.

The baseline passed 96 automated tests and validated all 30 documents. Results are in [READINESS_VERIFICATION.md](READINESS_VERIFICATION.md); later model measurements are in [RELEASE_REVIEW.md](RELEASE_REVIEW.md).
