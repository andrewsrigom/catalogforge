# CatalogForge documentation

Start with the [main README](../README.md) for setup and usage. The documents below cover implementation, operations and measured results.

## Product and implementation

| Document | Contents |
| --- | --- |
| [Product decisions](PRODUCT_DESIGN.md) | Problem, review experience and implementation tradeoffs |
| [Architecture](ARCHITECTURE.md) | Components, graphs, transactions, authorization and delivery semantics |
| [Development and maintenance](DEVELOPMENT.md) | Local setup, tests, generated types, reindexing and reset |
| [AI operations](AI_READINESS.md) | Isolated pilot, usage limits, diagnostics, backup and restore |
| [Limitations](LIMITATIONS.md) | Product, evaluation, document and operational constraints |
| [Visual identity](BRAND.md) | Logo, palette, usage and asset origin |

## Release results

- [Evaluation report](RELEASE_REVIEW.md): live results, functional tests, known errors, usage and measurement scope.
- [Machine-readable results](verification/release/results.json): metrics and checks supporting the report.
- [Final fixture evaluation](verification/release/fixture-final.json) and [guided examples](verification/release/guided-evaluation.json): deterministic checks, separate from AI quality.
- [Changelog](../CHANGELOG.md): changes recorded for the release.

## Historical records

These documents preserve plans and results from earlier stages. Read their numbers in the context of each stage's date and scope; they do not replace the evaluation report.

- [Engineering decisions](PLAN.md) and [initial verification](VERIFICATION.md).
- [Everyday-use scope](DAILY_USE_PLAN.md) and [results](DAILY_USE_REPORT.md).
- [Experience verification](EXPERIENCE_VERIFICATION.md).
- [Provider integration baseline](READINESS_PLAN.md) and [readiness verification](READINESS_VERIFICATION.md).
- [Initial live AI pilot](LIVE_PILOT_REPORT.md).
