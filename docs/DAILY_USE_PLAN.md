# Everyday-use scope

This change set preserved existing workspaces and reviews while adding a separate, idempotent collection of guided examples.

- Recovery of stalled jobs, consistent cancellation and transaction lock ordering.
- Clear session-expiry and pending-approval states, proposal filters and keyboard evidence navigation.
- Twelve synthetic Northstar examples covering family applicability, packaging ambiguity, conflicting suppliers, wrong variants and invalid values.
- PostgreSQL integration tests, browser journeys, deterministic evaluations and abrupt worker recovery.

Measured results are in [DAILY_USE_REPORT.md](DAILY_USE_REPORT.md). The exercise used fixture mode; live-model measurements are recorded separately in [RELEASE_REVIEW.md](RELEASE_REVIEW.md).

Recovery uses Procrastinate 3.9.0: [API reference](https://procrastinate.readthedocs.io/en/stable/reference.html) and [stalled-job retries](https://procrastinate.readthedocs.io/en/stable/howto/production/retry_stalled_jobs.html).
