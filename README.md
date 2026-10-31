# AI-Powered Khojki OCR

A small, evidence-preserving pipeline for historical Khojki: PDF rendering,
geometric line detection, OpenAI visual transcription, Unicode validation,
human-confirmed references, codepoint CER and stage-level error analysis.

Repository: https://github.com/prezwail-jx/AI-Powered_OCR_for_Khojki

## Measured result

| Printed evaluation (PDF page 17) | Result |
|---|---:|
| Selected, user-confirmed rows | 10 |
| Reference Unicode code points | 253 |
| Substitutions / deletions / insertions | 0 / 0 / 1 |
| Micro CER | **1/253 = 0.003952569170** |
| Macro CER | **0.003333333333** |
| Exact rows | **9/10** |

The sole error is a model-extra U+11235 on line15, attributed to character
recognition. This is **selected-crop transcription CER**, not whole-page or
collection accuracy. Ground truth is **model-assisted user visual review**, not
independent blind expert transcription. Nine references accept model candidates
unchanged, creating anchoring risk. Annotation duration is unknown.

- [Evaluation and cost](reports/evaluation.md)
- [One-page technical retro](reports/reflection.pdf) ([text](reports/reflection.md))
- [Error analysis](reports/t13-error-analysis.md)
- [Reviewer reproduction](docs/reproduction.md)
- [Clean-environment verification: 240 tests](reports/t14-reproduction.md)
- [Final local acceptance and requirements matrix](reports/acceptance.md)
- [Sources, licenses and distribution](docs/data-and-licenses.md)
- [Historical implementation notes](docs/implementation-history.md)

## Install (Python 3.11)

Use a project-local virtual environment; never install into system Python.
Tested baseline: CPython **3.11.18**, macOS arm64. Other platforms are not claimed
as tested; native-wheel availability and image bytes may differ.

```bash
uv python install 3.11
uv venv --python 3.11 --seed .venv
.venv/bin/python -m pip install -r requirements-repro.txt
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pip check
.venv/bin/python -m khojki_ocr --help
```

Reuse a compatible existing `.venv`; do not overwrite it. If `uv` is absent from
PATH, use `$HOME/.local/bin/uv`. Package installation needs internet or a local
wheel cache. Offline inference/reproduction requires no API credentials.

## Reviewer quick start: reproduce saved evidence

The **code package** contains source, tests and textual reports. The separate
**private review-evidence package** supplies the hashed crops, raw predictions,
frozen references and diagnostic records. Neither includes the full input PDF.
Overlay both zip files into a new project directory, then install as above.
Do not publish the scan-derived evidence package without separate permission.

Alternatively, clone this repository (which includes `code-index.json`), then
extract only the privately supplied `review-evidence.zip` into its root before
installing and running the replay. The evidence archive is not hosted publicly.

```bash
.venv/bin/python scripts/reproduce_offline.py --output outputs/reviewer-replay
.venv/bin/python -m pytest -q
```

The replay verifies both package indexes, remaps historical paths only within
the reviewer tree, blocks network and access to the author's original workspace,
recomputes T12/T13, and compares core outputs byte-for-byte. It never calls a
model or rewrites the budget/reference. Tests need the private evidence overlay;
code alone is not the full benchmark dataset.

For full image-flow replay, privately obtain the exact original PDF and add:

```bash
.venv/bin/python scripts/reproduce_offline.py \
  --pdf sample_khojki_script_vatiations.pdf --output outputs/reviewer-full
```

This also renders pages 9 and 17 at 300 DPI, detects their lines and checks the
ten selected crop hashes, IDs and geometry against the frozen selection. All
outputs are new; existing replay directories are rejected. See
[reproduction details](docs/reproduction.md) for packaging and diagnostics.

## Run the image pipeline on a supplied PDF

Run commands from the project root. These steps are offline:

```bash
.venv/bin/python -m khojki_ocr preprocess --config configs/default.yaml \
  --pdf sample_khojki_script_vatiations.pdf --pages 9,17 --dpi 300
.venv/bin/python -m khojki_ocr detect-lines --config configs/default.yaml \
  --input-run outputs/<preprocess-run-id>
```

The detector uses geometric connected components, projection and morphology;
classes and flags are not OCR confidence. Recognition receives high-resolution
grayscale crops, not the aggressively enhanced detection image. The frozen
selection is `data/evaluation/selection.json`; its original crop-approval fields
are historical. The active reference pointer is
`data/annotations/ground_truth.manifest.json` (`ground-truth-v1`).

## Optional live recognition (paid; not part of offline reproduction)

The active route is OpenAI **`gpt-6.1-sol`** at the official endpoint using
`configs/openai.yaml`. Set `OPENAI_API_KEY` in the shell; `.env.example` contains
placeholders and `.env` is not loaded automatically. Never place credentials in
arguments, config, reports or version control. DeepSeek was retired after the
saved failed diagnostics; do not dispatch new DeepSeek requests for this study.

Prepare requests offline before choosing to spend money:

```bash
.venv/bin/python -m khojki_ocr recognize --selection data/evaluation/selection.json \
  --provider openai --config configs/openai.yaml --limit 10 --dry-run
```

Only after explicitly accepting cost and checking current model access/pricing,
replace `--dry-run` with `--execute`. A verified cache hit avoids a paid request;
a fresh request can cost money and return different text. Retain the historical
ledger, including unknown reservations; do not reset it to obtain budget headroom.
API use is not assumed to consume ChatGPT/Codex subscription allowance.

Human reference freezing is a separate, explicit confirmation operation. New
transcription corrections require a new truth version; no machine prediction is
automatically accepted as truth. See [T11 methodology](reports/t11-ground-truth.md).

## Outputs and validation

- `outputs/<run-id>/manifest.json`: model/config/source identity and hashes.
- `predictions.jsonl`, per-line `.txt` and result JSON: original machine output.
- `data/annotations/versions/ground-truth-v1/`: immutable reference and original
  prediction snapshots.
- T12: `summary.json`, `lines.jsonl`, `confusion.json`, codepoint alignments and
  separate historical DeepSeek appendix.
- T13: `cases.jsonl`, summary, report and evidence figures; page-9 and manuscript
  cases are qualitative, excluded from the printed CER.
- Replay: `reproduction.json` plus newly generated runs; no hidden model calls.

Both reference and hypothesis are NFC-normalized under **Unicode 17.0.0** and
compared as code points. Spaces, Khojki separators and Gujarati digits count.
Empty hypotheses are all deletions, empty references are rejected and CER can
exceed 1. Legal encoding is not evidence of correct recognition.

## Scope and limitations

No complete manual line boxes were annotated: detection precision, recall, IoU
and detection CER delta are unmeasured. Two page-9 detection failures and two
manuscript crops are shown separately. The first manuscript crop is visibly
clipped despite no detector flag; the user accepted it as a failure example.
Manuscripts have no OCR, reference or CER results.

Ten printed predictions cost an estimated **USD 1.036664**, with **442.36 seconds**
summed observed request elapsed time. All history totals **USD 1.1421432** in
usage-based estimates plus **USD 3.74944** unknown reserved amount. These are not
confirmed invoices. T12-T14 offline work adds no API charges.

**T15 local acceptance is complete**: the user explicitly accepted the delivered
scope and limitations. The final code/private-evidence packages are under
`outputs/t15-delivery/` in the author's local workspace; the T14 package is retained
as history. The code repository is now published at the URL above; private scan
evidence is not published. The acceptance reports describe the earlier local
acceptance snapshot, before publication. Code-license selection and emailing the
evaluator remain unperformed steps; publishing this repository does not send an email.
