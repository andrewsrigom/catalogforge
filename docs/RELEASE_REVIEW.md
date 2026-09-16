# CatalogForge — evaluation and verification report

Recorded on 2026-09-16. Scope: local glove catalog enrichment, evidence, review and export.

## Live evaluation

The real corpus contains 30 unique products and 150 attribute checks, split into 20 development products and 10 held-out products. Twelve separate synthetic adversarial cases provide another 60 checks.

| Stage | Products | Precision | Answerable coverage | Correct abstention | Gates |
| --- | ---: | --- | --- | --- | --- |
| Initial development | 20 | 64/67 (95.5%) | 64/71 (90.1%) | 26/29 (89.7%) | Failed |
| Development confirmation | 20 | 66/67 (98.5%) | 66/71 (93.0%) | 28/29 (96.6%) | Passed |
| Adversarial development | 6 | 6/6 (100.0%) | 5/6 (83.3%) | 24/24 (100.0%) | Passed |
| Held-out real validation | 10 | 37/38 (97.4%) | 37/39 (94.9%) | 10/11 (90.9%) | Passed |
| Held-out adversarial validation | 6 | 6/6 (100.0%) | 5/6 (83.3%) | 24/24 (100.0%) | Passed |

Acceptance gates: precision ≥95%, coverage ≥80%, traceability 100%, abstention ≥90%, review-ready runs 100%, no identity errors and adversarial conflict detection ≥90%. Metrics without examples are not counted as passed. The real corpus contains no conflicts; that behavior was measured separately.

### Development and frozen validation

Initial development exposed carton dimensions proposed as glove length. The first fix required measurement context. Confirmation passed its gates but still included a quotation that omitted the table heading. The final guard also checks preceding source context.

Revalidating the **same saved responses**, without new calls, produced 66/66 (100.0%) precision and 66/71 (93.0%) coverage. This offline result does not replace the earlier live measurement.

Inference code, prompts and datasets were then frozen. The ten held-out real products and six held-out adversarial products ran once, with no subsequent tuning on their results. Code reference: `390d864`; identity prompt `catalogforge-identity-v3`; extraction prompt `catalogforge-extraction-v2`; models `gpt-4.1-mini` and `text-embedding-3-small`.

### Observed errors

- **A637:** proposed `inner_pack_count = 12` from the ambiguous quotation `Dipping: : 12`, without an explicit inner-pack quantity label. The proposal is incorrect against the versioned labels. Literal citation and correct identity alone do not establish the meaning of a number.
- **EV-105 and EV-205:** both adversarial sources used `length_mm: 9.5 in`. The conservative measurement guard did not recognize the underscore-separated label and left the field unknown. Domain unit conversion was tested; live extraction of this format produced no proposal.

These outcomes remain in the recorded scores. The sample covers one manufacturer and category; labels have no independent specialist review.

## Functional verification

**129 automated tests passed:** 117 backend, six component/utility tests and six browser journeys. Ruff, formatting, mypy, generated types, web build and locked installation with `uv sync --frozen`/`npm ci` also passed. Additional fixture evaluations covered 50 products/300 checks and 12 guided examples/19 checks.

The SIGKILL exercise resumed an approval in **47.36 seconds** and applied the product change once. The live acceptance journey approved 66 fields after comparison with labels, rejected unsupported proposals and exported only original/approved data. An adversarial exercise resolved a conflict with a recorded reason. These were automated acceptance exercises, not independent human reviews.

After database/API restart, decisions and ZIP bytes remained identical. Review and export added no provider calls. The everyday environment preserved 73 products, 22 sources, 166 passages, 78 candidates, 66 evidence records, ten reviews and 29 runs. All 22 document hashes matched the preceding backup.

Verification also covered isolated backup/restore, restart recovery, clean installation and credential auditing. The product presentation and downloadable summary were checked on desktop and mobile. Test XML hostnames were normalized for distribution without changing results or counts.

## Recorded cost

| Stage | Calls | Recorded cost |
| --- | ---: | ---: |
| Initial development | 118 | USD 0.037460 |
| Development confirmation | 121 | USD 0.038018 |
| Adversarial development | 24 | USD 0.002695 |
| Held-out real validation | 60 | USD 0.020334 |
| Held-out adversarial validation | 24 | USD 0.002699 |
| Earlier pilots | — | USD 0.005477 |
| **Cumulative total** | — | **USD 0.106683** |

Costs use provider-reported tokens and configured prices, rounded conservatively per call. The provider invoice was not inspected. No calls had unknown usage at the end of the run, and paid workers were stopped. Pricing references: [GPT-4.1 mini](https://developers.openai.com/api/docs/models/gpt-4.1-mini) and [embeddings](https://developers.openai.com/api/docs/models/text-embedding-3-small).

## Interpretation

These results establish the measured local integration, recovery and model behavior within this corpus. They do not establish general extraction quality, production-load performance or a hosted service guarantee. Fixture checks do not measure model quality. OCR, other categories and external catalog integrations are outside the evaluated scope.

Machine-readable results: [verification/release/results.json](verification/release/results.json). Earlier reports retain their stage-specific measurements. Credentials, database files, backups, uploads and original third-party PDFs are excluded from the code package.
