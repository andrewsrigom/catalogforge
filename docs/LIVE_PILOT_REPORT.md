# CatalogForge — three-product live pilot

Historical development measurement from 2026-09-16. See [RELEASE_REVIEW.md](RELEASE_REVIEW.md) for the larger evaluation and held-out results.

## Results

| Measure | Result |
| --- | ---: |
| Products ready for review | 3/3 |
| Correct proposals | 7/7 |
| Proposals with correct, traceable quotations | 7/7 |
| Documented attributes recovered | 7/8 (87.5%) |
| Unanswerable fields kept unknown | 7/7 |
| Relevant documents retrieved | 3/3 |
| Conflicts | Not measured: no cases in the sample |

The sample used A040, A060 and A106 from the development set. A040's `gauge` of 18 had no accepted proposal. Coverage exceeded the configured 80% gate but was not complete. No value was automatically approved or exported.

This small sample covered one category and manufacturer and was used during system adjustments. It is not an independent evaluation. The ten held-out products and adversarial supplement did not run in this pilot. Labels and pinned PDFs were unchanged.

## Recorded cost

| Operation | Calls | Input tokens | Output tokens | Recorded cost (USD) |
| --- | ---: | ---: | ---: | ---: |
| identify | 6 | 4156 | 238 | 0.002046 |
| embedding_documents | 3 | 1778 | 0 | 0.000037 |
| embedding_query | 6 | 30 | 0 | 0.000006 |
| extract | 3 | 4988 | 557 | 0.002888 |

**Pilot total: USD 0.004977 across 18 calls.** This includes an interrupted import and its continuation under the same persistent budget, without resetting counters. The exact provider-token × price total is USD 0.00496576; the application rounds each call up to a microdollar. No usage was unknown.

Including an earlier USD 0.000500 exercise, cumulative recorded usage was **USD 0.005477**. The worker stopped at 18/20 calls. Configuration changes do not increase an existing persisted budget.

Prices per million tokens used for this measurement: [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini), USD 0.40 input / USD 1.60 output; [text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small), USD 0.02 input. The provider invoice was not inspected; taxes and currency conversion are excluded. These historical prices are not a current pricing reference.

## Fixes verified

- Identification separates brand and code from titles while preserving exact document/product/variant matching. Similar codes and different suffixes are not interchangeable.
- Proposed identifiers must exist as complete tokens in the source. Ambiguous passages cannot authorize evidence.
- Explicit `code - description` titles are split without stripping internal code suffixes. The original form is preserved in `model_label`.
- PDFs with a short prefix before the header use the existing parser while preserving bytes/hash. Unreadable, encrypted and image-only documents remain rejected. [pypdf's tolerant mode](https://pypdf.readthedocs.io/en/latest/user/robustness.html) performs best-effort recovery.
- Structured numbers such as `12.0` are checked against complete numeric tokens; `120`, `12.5` and `-12` do not support `12`.
- PDF whitespace may vary in a quotation; stored evidence is the exact recovered source passage. Cropped quotations cannot turn one value into another.
- A second retrieval without new evidence does not repeat extraction. Exactly three extractions were observed, one per product.
- The evaluator checks hashes and parser compatibility before creating paid jobs. `.env` and `.env.*` are excluded from Docker context.

**106 backend tests passed**, including identity, evidence, PDF, preflight and budget regressions. Lint and types passed. The review interface and original A106 PDF opened without JavaScript errors in the checked session. No frontend code changed in this pilot.

## Configuration history

A040/A060 initially used identity v2. A060 still returned a title in its model field; before creating any run or evidence, the same v3 normalizer was applied to the saved identifier, with an audit event and no new paid call. A106 used identity v3, and all three extractions used the corrected image. This makes the pilot an iterative development test rather than a clean frozen benchmark.

The pilot ran as `catalogforge-pilot-round2` with separate database/API services and image `catalogforge-api:identity-v3`. The earlier pilot was preserved, the everyday instance remained in fixture mode, and the pilot worker was stopped after measurement. Subsequent development and held-out validation are recorded in the [evaluation report](RELEASE_REVIEW.md).
