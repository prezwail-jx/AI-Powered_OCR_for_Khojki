# Khojki OCR Evaluation

## Scope and method

Ten deliberately selected, clear printed crops from PDF page 17 were recognized
independently by OpenAI `gpt-6.1-sol` using the official Responses endpoint,
strict JSON output and one target plus eight character-reference images. Model
parameters are in `configs/openai.yaml`; source hashes and actual response model
identities are retained in the per-line records. No human reference, other-model
answer or expected line-number answer was sent to the model.

The user reviewed the chart and scans, accepted nine candidates and removed only
raw `[21,22)` U+11235 from line15. `ground-truth-v1` is **model-assisted user visual
review**, not blind expert annotation. Human review duration is unknown/null.
Its SHA-256 is `216a152424ef11258c1885fdd59d10899a8e4d2de44d49acb5e38008488e3a16`.

Both strings are NFC-normalized with Unicode 17.0.0 and compared as codepoints.
Spaces, Khojki separators, marks, punctuation and Gujarati digits are retained.
CER = (S+D+I)/reference length; no cap at 1. Empty hypotheses are all deletions;
empty references are rejected. Deterministic alignment uses fixed tie-breaking.

## Results

| Overlay row | Reference codepoints | S | D | I | CER |
|---:|---:|---:|---:|---:|---:|
| 6 | 25 | 0 | 0 | 0 | 0 |
| 7 | 23 | 0 | 0 | 0 | 0 |
| 9 | 24 | 0 | 0 | 0 | 0 |
| 10 | 20 | 0 | 0 | 0 | 0 |
| 11 | 30 | 0 | 0 | 0 | 0 |
| 12 | 21 | 0 | 0 | 0 | 0 |
| 13 | 23 | 0 | 0 | 0 | 0 |
| 14 | 29 | 0 | 0 | 0 | 0 |
| 15 | 30 | 0 | 0 | 1 | 0.033333333333 |
| 16 | 28 | 0 | 0 | 0 | 0 |
| Total | 253 | 0 | 0 | 1 | **0.003952569170** |

Micro CER **1/253**, macro CER **0.003333333333**, exact lines **9/10**.
All ten have candidates; none was silently excluded for recognition failure.
The sole insertion is U+11235 at hypothesis index 21. It is not a recurring
"most common pattern" inferred from a sufficient error distribution.

Formal evaluation: `outputs/20261030T230213Z-afd44e1b89db/`.
Formal attribution: `outputs/20261030T233828Z-bdf49aab235d/`.
These original paths and hashes are preserved in the private evidence package.

## Stage attribution and challenge examples

The user confirmed the line15 error as **character recognition**: its crop was
approved complete and the model marked the small lower mark uncertain. No
evidence supports a correct visual identity encoded to a wrong scalar. Main-set
attribution counts are detection 0, recognition 1, confirmed mapping 0; these are
supported human judgments, not controlled causal attribution or model internals.

Page-9 400 DPI candidates 10 (border-fragment false positive) and 9 (overwide,
overlapping candidate) demonstrate detection failures. Complete independent manual
boxes were not produced, so precision, recall, IoU and detection CER delta remain
unmeasured. Main selected-crop CER must not be generalized as detection accuracy.

Two manuscript examples from pages 1 and 5 are qualitative only. Page 1 has
visible left clipping despite no flag; the user accepted retaining it as a failure
example. Page 5 has ambiguous-mark/overlap flags. No manuscript recognition,
reference or CER exists. See [T13 evidence](t13-error-analysis.md).

## Failed experiments and selection history

| Historical case | Real first-row CER | Note |
|---|---:|---|
| DeepSeek D0 | 23/25 = 0.92 | Original reference-package diagnostic |
| DeepSeek D1 | 25/25 = 1.00 | Empty candidate retained as all deletions |
| DeepSeek D2 | 26/25 = 1.04 | Changed diagnostic prompt/image settings |
| D1b | not real-scan CER | Synthetic-only 11/11 = 1.00 |
| D3 | not run | Cancelled before dispatch |

These settings differ; no second-model aggregate is reported. DeepSeek is retired
and replay reads historical files only. The intermediate v2 selection replaced
line15 with line18, incurred one additional OpenAI call, then was abandoned when
the user restored v1. Line18 does not enter this reference or CER. This post-output
selection history, clear-print selection and candidate-anchored review limit
generalization. See [T11](t11-ground-truth.md) and [replacement history](t10-line18-replacement.md).

## Timing, cost and scaling assumptions

The ten original main predictions (including the original pilot rather than its
zero-time cached replay) sum to **442.3611 seconds**, estimated **USD 1.036664**.
The measured average is **44.2361 s / USD 0.1036664 per line**. This is summed
observed request time, not end-to-end annotation or whole-pipeline wall time.

| Ledger category | USD |
|---|---:|
| All recorded usage-based estimates | 1.1421432 |
| Unknown historical reservation | 3.74944 |
| Local accounted total | 4.8915832 |
| Remaining against USD 15 local cap | 10.1084168 |

There are 16 historical attempts. Estimates are not confirmed vendor invoices;
unknown reservations are retained rather than assumed free. The extra line18
call is included in all-history cost, not main ten-row cost. T12-T14 offline
reproduction makes no additional inference request.

For an **assumed 15 similarly sized rows per page**, serial inference alone is
663.54 s (11.06 min), USD 1.5550/page. For **47 such pages**, it is 8.66 hours and
USD 73.08. This deliberately simple scenario is not the actual mixed collection:
line counts, token sizes and handwriting differ. Segmentation, manual review and
unreadable-region handling add time; concurrency changes throughput, not total
token cost or reliability. Handwriting has not been timed or priced by inference.

Recompute the measurements from saved records:
`.venv/bin/python -m khojki_ocr.delivery metrics`.

## Reproducibility and assets

See [reviewer reproduction](../docs/reproduction.md) for the split delivery,
exact dependency inventory, new-directory `.venv` installation, network-blocked
replay and crop-hash verification. Frozen references and predictions remain
unchanged. No real-call rerun is needed to reproduce the saved metrics.

Unicode/font choices and distribution restrictions are documented in
[data and licenses](../docs/data-and-licenses.md). Noto Serif Khojki v2.005 replaces
the incomplete bundled Sans for full reference coverage. Gujarati digits use
Noto Sans Gujarati. Legal encoding alone cannot establish recognition correctness.

T14's new-directory/new-`.venv` verification passed **240 tests**, reproduced
T12/T13 core outputs byte-for-byte with original-workspace/network reads blocked,
and regenerated all ten selected image hashes and geometry from the supplied PDF.
See [clean verification](t14-reproduction.md) for the actual environment and records.
