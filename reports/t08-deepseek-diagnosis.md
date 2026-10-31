# DeepSeek Diagnosis and Decision

## Decision

The user decided to stop using DeepSeek after D2. **D3 was cancelled before any
request. No more DeepSeek calls or OpenAI batch calls are authorized by this
decision.** The active project route is OpenAI `gpt-6.1-sol` plus Unicode checks
and human verification. Historical adapters/results remain for reproducibility.

## Experiments

All new experiments used `deepseek-flash`, thinking disabled, the same JSON
contract, 4096 maximum output tokens, one attempt and the shared USD 15 ledger.
No OpenAI answer or diagnostic oracle was sent to DeepSeek.

| Case | Input | Observation | Conservative USD estimate |
|---|---|---|---:|
| D0 (historical) | Real crop + eight charts, target first | Signs/punctuation only, no base letters or trailing number | 0.0021081 |
| D1 | Real crop only, reference-independent prompt | Empty text, `unreadable=true`; 756 input / 17 output tokens | 0.0002472 |
| D1b | Clean Noto-rendered control only, same prompt as D1 | Empty text, `unreadable=true`; 616 input / 17 output tokens | 0.0002052 |
| D2 | Real crop + marks.png only, D0 prompt | Repetitive 28-codepoint sequence; 14 base letters, no trailing number; 1413 input / 129 output tokens | 0.0005787 |
| D3 | Planned D0 images reordered with target last | **Cancelled by user, not run** | Not incurred |

Additional D1/D1b/D2 conservative estimates total **USD 0.0010311**. These are
usage-based estimates at configured peak/cache-miss rates, not confirmed invoices;
cache discounts are not assumed. D1b returned 256 cached input tokens and D2 640.

Run directories:

- D1: `outputs/20261030T192243Z-3082922123ed/`
- D1b: `outputs/20261030T192315Z-0737de969846/`
- D2: `outputs/20261030T192359Z-cc62c395b6fd/`

Each contains request identity, image hashes, result, structural metrics and cost
records. D1b also contains the generated image and a local post-inference oracle.

## Interpretation and limitations

- Removing charts stopped the original chart-like answer but did not produce a
  usable transcription. Chart confusion is not a sufficient explanation by itself.
- The synthetic control contains eleven known Unicode codepoints. Empty output
  yields **CER 1.0 for that synthetic control only**. This is not the scan CER.
- D2's JSON and Unicode checks pass and the application reports `succeeded`, but
  the repetitive pattern and omitted visible number make it unsuitable as a
  verified target transcription. Protocol success is not accuracy.
- The real-line edit distance to the OpenAI candidate is only agreement with an
  **unverified model answer**, never a substitute for Ground Truth.
- D1 necessarily changes reference-dependent prompt wording as well as the image
  package. D1b uses modern synthetic glyphs and a different character sequence.
  Each condition has one stochastic trial. D3 and thinking-mode comparisons were
  not performed. Do not claim a definitive universal capability limitation.

The evidence supports the practical decision that DeepSeek is not a reliable
secondary OCR provider **under the tested settings**. Further debugging is not
needed to satisfy an assignment that does not require multiple providers.

## Budget after cancellation

- Total model/API dispatch attempts so far: 6 (4 DeepSeek, 2 OpenAI).
- Known conservative usage estimates: USD 0.1067132.
- Historical OpenAI 401 unresolved reservation: USD 3.74944, not a confirmed charge.
- Local accounted/held amount: USD 3.8561532.
- Remaining local allowance: USD 11.1438468.

The old ledger entry is preserved; cancellation does not reset charges or release
unknown reservations. No real scan Ground Truth or CER has been generated.

## Reproduction

The standalone diagnostic entry is `python -m khojki_ocr.deepseek_diagnosis` with
`--variant D1|D1b|D2|D3` and an explicit `--dry-run` or `--execute`. It is retained
for historical reproduction, **not the active workflow**. Offline tests cover
variant isolation, oracle non-leakage, metrics, cache reuse and timeout handling.
The current suite has 146 passing offline tests.
