# T12 Offline OCR Evaluation

## Scope and policy

This is **selected-crop transcription CER** for ten user-selected clear printed
rows on PDF page 17. It is not whole-page detection recall or collection-level
accuracy. The reference is `ground-truth-v1`, produced by model-assisted user
visual review rather than independent blind expert transcription.

Reference and hypothesis are independently NFC-normalized and compared as Unicode
code points. ASCII space, Khojki word separators, punctuation, combining signs
and Gujarati digits are retained. CER is `(S + D + I) / N` and is not capped at
1. Empty hypotheses count as all deletions; empty references are rejected. A
fixed substitution/deletion/insertion tie order makes alignments reproducible.

## Main OpenAI result

Formal run: `outputs/20261030T230213Z-afd44e1b89db/`.

| Metric | Result |
|---|---:|
| Rows | 10 |
| Reference code points | 253 |
| Substitutions / deletions / insertions | 0 / 0 / 1 |
| Micro CER | 1/253 = **0.003952569170** |
| Macro CER | **0.003333333333** |
| Exact rows | **9/10 = 0.90** |
| Recognition failures / empty hypotheses | 0 / 0 |

Rows 6, 7, 9, 10, 11, 12, 13, 14 and 16 are exact. Overlay row 15 has
CER 1/30: the original OpenAI hypothesis contains one extra U+11235 relative to
the confirmed reference. Therefore the evaluation operation is an **insertion**,
although the user's correction action deleted that character from the candidate.
This is the only observed main-set error, not evidence of a stable error pattern.

## Historical DeepSeek appendix

These saved diagnostics all use the same first real scan but have different
prompts and image packages. They are separate exploratory cases, not a second
model aggregate and not part of the OpenAI metrics.

| Case | Scope | Edit distance / N | CER |
|---|---|---:|---:|
| D0 | historical real-scan diagnostic | 23/25 | 0.92 |
| D1 | target-only; empty output retained | 25/25 | 1.00 |
| D2 | changed historical diagnostic | 26/25 | 1.04 |
| D1b | synthetic control only | 11/11 | 1.00 |
| D3 | cancelled before dispatch | not run | not run |

## Detection boundary and limitations

No independent manual line boxes were created, so detection recall, precision,
IoU, manual-box CER and a detection CER delta were not measured. Mechanical edit
types do not establish whether an error arose in detection, recognition or
Unicode mapping; T13 handles evidence-based attribution.

The rows were deliberately selected as clear printed examples. Nine references
accept the model candidate unchanged, which creates anchoring risk. The result
must not be generalized to the full PDF, handwriting, an independently labeled
benchmark or expert transcription accuracy. The intermediate line18/v2 experiment
is historical and excluded from this main set.

## Reproducibility and cost

`summary.json`, `lines.jsonl`, `alignments/*.json`, `deepseek-appendix.json`,
`report.md` and `manifest.json` contain the metrics and hashes. `verify-evaluation`
recomputes the OpenAI result from frozen original predictions, verifies every
artifact, and checks the T11 prediction/cache/selection/budget source guard. T12
created no API client, made **zero API calls**, and added **USD 0** cost.
