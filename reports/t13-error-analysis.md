# T13 Error Attribution and Qualitative Manuscript Challenge

Formal analysis: [`outputs/20261030T233828Z-bdf49aab235d/`](../outputs/20261030T233828Z-bdf49aab235d/).
The generated [report](../outputs/20261030T233828Z-bdf49aab235d/report.md)
includes the original line15 input, the page-9 detection overlay and the
manuscript contact sheet. `cases.jsonl` records the supporting evidence paths,
hashes, stage labels, exclusions and scope.

## Attribution policy

| Stage | Interpretation |
|---|---|
| `line_detection` | Missing/merged lines, clipping, or non-text/margin regions emitted as lines. |
| `character_recognition` | The visual identity or presence of a character disagrees with the confirmed reference. |
| `unicode_mapping` | Evidence supports a correct visual identity but an incorrect scalar/encoding sequence. |
| `unknown_or_mixed` | The saved evidence does not distinguish the contributing stages. |

Labels are evidence-based human-reviewed interpretations, not access to internal
model reasoning. Model uncertainty explanations provide supporting observations,
not causal proof.

## Main printed-set error

The ten-line OpenAI evaluation has one insertion: line15 hypothesis index 21 is
U+11235 KHOJKI SIGN VIRAMA, absent from the user-confirmed reference. The user
confirmed the primary stage as **character recognition**.

The crop was approved as complete; its detector record is `body` with no flags.
The original model response marks `[21,22)` uncertain because the small lower
mark is indistinct. The frozen prediction, user reference, image and deterministic
T12 alignment are cross-checked. There is no evidence that the model first
identified a correct visible symbol and then merely encoded it incorrectly,
so the error is not labeled `unicode_mapping`. No character-level pixel box is
claimed from a text offset.

| Main-set attribution | Count |
|---|---:|
| Line detection | 0 |
| Character recognition | 1 |
| Unicode mapping | 0 |
| Unknown/mixed | 0 |

This is the **only observed main-set error**, not a stable frequency distribution.
Zero confirmed Unicode-mapping errors does not mean the risk is absent. The
reference is model-assisted user review, not independent blind expert labeling;
selection and anchoring bias still apply.

## Qualitative detection cases

Both are bound to the existing 400 DPI page-9 detection run
`outputs/20261030T154140Z-29d2de257bd5/`:

| Candidate | Observation |
|---|---|
| `p0009-l010-9eee9db3825d` | A narrow right-border fragment is emitted as an independent line candidate; one anchor and decoration/few-anchor/overlap flags support the failure interpretation. |
| `p0009-l009-99b5a8f5d214` | A body candidate overextends into the right margin and carries overlapping-content and possible-truncation flags. |

These are qualitative detection examples, not additional OCR edit events. No OCR
was requested for them. Without complete independent manual boxes, page-level
precision, recall, IoU, false-positive rate and a detection CER delta are unmeasured.

## Two manuscript challenge samples

Pages 1–6 were processed offline at 300 DPI, producing 194 geometric candidates.
Preprocessing: `outputs/20261030T230939Z-421e14dcddd6/`.
Detection: `outputs/20261030T230955Z-e8f041782050/`.

Frozen selection and images:
[`data/challenges/t13/`](../data/challenges/t13/), including
[`frozen/contact-sheet.png`](../data/challenges/t13/frozen/contact-sheet.png).

| Sample | Source | Qualitative difficulty |
|---|---|---|
| `manuscript-01` | Page 1, `p0001-l004-014fbcd3a4da` | Connected strokes, uneven ink and a visually incomplete left boundary despite an empty detector flag list. |
| `manuscript-02` | Page 5, `p0005-l020-e9edbdd00426` | Slanted dense writing, degradation, `ambiguous_mark` and `overlapping_line_content`. |

The initial plan preferred complete crops. Visual contact-sheet review exposed
page-1 clipping, and the user explicitly accepted retaining it as a **detection
failure** example. It is not represented as a reliable complete transcription
input. Neither manuscript was recognized or manually transcribed. No manuscript
CER or recognition accuracy is reported, and neither enters the printed aggregate.

## Reproduce and verify

From the project root, without credentials:

```bash
.venv/bin/khojki-ocr analyze-errors \
  --attributions data/annotations/error-attribution-v1.json \
  --challenge data/challenges/t13/frozen/manifest.json \
  --evaluation outputs/20261030T230213Z-afd44e1b89db --output-dir outputs
.venv/bin/khojki-ocr verify-error-analysis \
  --analysis outputs/20261030T233828Z-bdf49aab235d
.venv/bin/khojki-ocr verify-evaluation \
  --evaluation outputs/20261030T230213Z-afd44e1b89db
```

The analysis verifies evidence hashes, recomputes T12 from frozen sources, and
checks the original prediction/cache/selection/budget source guard. Core JSON and
report outputs repeat identically for the same input. Challenge freezing refuses
overwrites and publishes from a temporary directory only after all files succeed.

T13 made **zero API calls** and added **USD 0**. Main CER stays **1/253 =
0.003952569170**. The ledger and all protected inference inputs remain unchanged.

Verification completed: **234 tests passed** (12 T13 tests), with seven existing
SWIG deprecation warnings; `pip check` found no broken requirements. Both
`verify-error-analysis` and `verify-evaluation` passed. Before/after SHA-256
checks matched for the budget ledger, active truth, truth pointer and frozen T12
manifest. The T12 verifier additionally checked its protected prediction, cache
and selection inputs.
