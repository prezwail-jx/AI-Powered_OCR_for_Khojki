# AI-Powered Khojki OCR — Implementation History

Historical notes retained for provenance. Commands and relative links below were
originally written from the repository root. Use the current root README for
installation and reviewer reproduction; earlier pending states are historical.

## Current status

Tasks T01–T13 provide an isolated Python environment, validated configuration,
an offline input-preparation CLI, run manifests, redacted diagnostics, Unicode
validation, shaped character/combination reference charts, and full-page
rendering/preprocessing with reversible coordinate transforms, and geometric line
detection with high-resolution crops and reading order, and a frozen user-approved
ten-line evaluation subset, plus independent visual-model adapters, strict output
validation, caching and conservative budget accounting tested offline.
**Active route: OpenAI `gpt-6.1-sol` only, with Unicode checks and human verification.**
The user abandoned DeepSeek after three diagnostic cases; D3 was cancelled before
dispatch. The authorized ten-row batch is complete: the first row reused its
cache, nine new OpenAI calls returned candidates, and all ten rows initially needed
human review (26 uncertainty spans). The batch's conservative usage estimate is USD 0.933090,
not a confirmed invoice. A cache-only replay made zero calls and preserved every
machine prediction. **T11 is complete:** the user explicitly accepted line15
option B (delete only U+11235), confirmed the other nine rows and restored the
original selection `data/evaluation/selection.json`. Ten-row Ground Truth is
frozen as `ground-truth-v1` in `data/annotations/ground_truth.jsonl`. **T12 is
complete:** offline selected-crop transcription CER is 1/253 (`0.003952569170`)
micro and `0.003333333333` macro, with 9/10 exact rows and one U+11235 insertion
on line15. Original machine predictions are unchanged.
The intermediate line18/v2 replacement experiment is preserved, but is not the
main truth set. Its additional USD 0.10234 estimate remains in the shared ledger.
See [reports/t11-ground-truth.md](reports/t11-ground-truth.md) for final approval,
method, version and hashes. This is model-assisted user review, not blind expert
transcription.
**T13 is complete:** the sole main error is attributed to character recognition;
two page-9 detection failures and two offline manuscript challenge crops are
reported separately. See [reports/t13-error-analysis.md](reports/t13-error-analysis.md).
The earlier T09 example retains one candidate and nine unrecognized rows as a
historical verification artifact. See [reports/t10-batch.md](reports/t10-batch.md).
See [task.md](task.md), [plan.md](plan.md) and [PRD.md](PRD.md).

## Environment

Use [uv](https://docs.astral.sh/uv/) to manage Python 3.11 and a project-local
virtual environment. Do not install project dependencies into system Python.

```bash
uv python install 3.11
uv venv --python 3.11 --seed .venv
.venv/bin/python -m pip install -e '.[dev]'
```

If `uv` is not on PATH, use `$HOME/.local/bin/uv`. An existing compatible `.venv`
can be reused; inspect it before recreating it. `.venv` isolates dependencies but
still runs on your local machine. It is separate from `.env`, which is local API
configuration. Neither is committed. Optional activation: `source .venv/bin/activate`.

## Offline usage

Run commands from the project root:

```bash
.venv/bin/python -m khojki_ocr --help
.venv/bin/python -m khojki_ocr prepare --config configs/default.yaml --pages 8,16-17 --dpi 300
.venv/bin/python -m pytest
```

The installed `.venv/bin/khojki-ocr` command provides the same interface.
`prepare` validates the PDF and selected 1-based pages, then writes
`outputs/<UTC-timestamp>-<unique-id>/manifest.json` and `run.log`.
It does not render pages or recognize text. Runtime failures produce `error.json`
inside the run directory. Configuration failures return exit code 2 without
printing raw configuration; input failures return 1. Successful preparation returns 0.

CLI flags `--pdf`, `--pages`, `--output-dir`, and `--dpi` override YAML settings.
Relative paths are resolved against the working directory. YAML may configure
each provider's `model`, `base_url`, `timeout_seconds`, and `max_output_tokens`.
Unknown fields are rejected. Keep credentials out of YAML.

## Unicode checks and reference charts (offline)

```bash
.venv/bin/python -m khojki_ocr unicode-check --text-file transcription.txt --output outputs/unicode-report.json
.venv/bin/python -m khojki_ocr build-reference --output-dir outputs/references-v1
```

`unicode-check` accepts one UTF-8 transcription line. A single terminal LF or
CRLF is treated as a file delimiter, not text; the original file content and
delimiter are retained in the report. Internal line breaks and tabs are flagged.
JSON includes raw/NFC text, normalization edits, per-code-point names and scripts,
issues and suggested atomic encodings. Indices are **zero-based Unicode code
points in raw text**, not glyph or byte positions. Invalid characters are never
silently deleted or replaced. Exit codes: 0 for encoding-valid input (inspect
`needs_review` for warnings), 1 for invalid input, 2 for I/O/generation failure.

The policy allows all 65 assigned Khojki characters in Unicode 17.0.0, ten
Gujarati digits, ASCII space, and `. , : ; ! ? ( ) - ' "`. ASCII digits, other
scripts, undeclared punctuation and invisible controls require review. This
whitelist is project policy, not a claim that other punctuation never occurs in
historical documents. Isolated marks generate warnings; no full grammar checker
is claimed. NFC does **not** compose visually decomposed Khojki vowel sequences;
the separate atomic-character checks follow Unicode Table 15-4. Encoding validity
does not establish OCR accuracy or make a transcription Ground Truth.

`build-reference` creates eight PNG sheets and a manifest in a **new** directory:
vowels, consonants, marks, punctuation, digits and three consonant × vowel/sign
matrices. It covers 75 individual characters and 540 matrix cells (36 consonants
× inherent form/nine vowel signs/five other signs). These are mechanically
rendered sequences, not a vocabulary or a list of attested words. Dotted circles
help display isolated combining marks and must not enter transcription text.
Existing output directories are rejected to protect previous results.

### Sources, fonts and reproducibility

- Data: [Unicode 17.0.0 UCD](https://www.unicode.org/Public/17.0.0/ucd/) and
  [Khojki section/Table 15-4](https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-15/#G81423).
- Normalization: `unicodedata2==17.0.0`, rather than Python 3.11's older built-in
  Unicode database. Khojki KA is U+11208; GA is U+1120A.
- Rendering: `uharfbuzz` + `freetype-py`; Pillow assembles the images. RAQM/system
  font installation is not required.
- Complete Khojki reference font: official
  [Noto Serif Khojki v2.005](https://github.com/notofonts/khojki/releases/tag/NotoSerifKhojki-v2.005).
  The retained Google Fonts Noto Sans Khojki lacks U+11241 and is **not** used for
  rendering. The manifest records its missing glyph explicitly.
- Digits: Noto Sans Gujarati from Google Fonts, repository commit
  `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`.
- Fonts, OFL licenses, Unicode license, character table, policy and source
  hashes are bundled under `src/khojki_ocr/assets/` and included in built wheels.
  Sources and font hashes are recorded in `assets/unicode/sources.json`; each
  generated manifest also records cell codepoints/names, renderer versions,
  policy hash and PNG hashes. Modern reference fonts may differ from historical
  handwriting and printing.

Source refresh is separate from normal offline commands:

```bash
.venv/bin/python scripts/prepare_unicode_assets.py
# Explicitly re-download and verify against recorded hashes:
.venv/bin/python scripts/prepare_unicode_assets.py --fetch
```

The preparation script downloads missing sources to `.cache/unicode-17.0.0`,
verifies known hashes and regenerates bundled assets. Hash mismatches stop the
process for review. Ordinary Unicode checking/chart generation never downloads
fonts or data. To reproduce exact pixels, retain the same font, renderer and
Pillow versions recorded in the generated manifest.

## Page preprocessing (offline)

```bash
.venv/bin/python -m khojki_ocr preprocess --config configs/default.yaml --pages 9,17 --dpi 300
# Optional explicit correction, positive counterclockwise (OpenCV convention):
.venv/bin/python -m khojki_ocr preprocess --config configs/default.yaml --pages 9 --angle -1.5
```

Each run writes `manifest.json`, `run.log`, and `pages/page-NNNN/` containing:

- `raw.png`: unmodified full-page RGB rendering.
- `gray-original.png`: grayscale before any rotation.
- `gray.png`: OCR grayscale with at most one expanded-canvas deskew rotation.
- `enhanced.png`: detection-only CLAHE output (optional Gaussian denoising).
- `binary.png`: detection-only adaptive threshold, 0 ink / 255 background.
- `comparison.png`: whole-page side-by-side preview.
- `detail-comparison.png`: three native-pixel regions with inverse-aligned
  OCR/detection previews; extra alignment interpolation is for display only.
- `metadata.json`: source hash, DPI, sizes, transforms, parameters, decisions,
  image hashes, embedded scan sizes and library versions.

The `preprocess` YAML section controls deskew, angle override, optional denoise,
CLAHE and adaptive threshold settings; see `configs/default.yaml` for defaults.
Denoising is disabled by default and confined to the detection branch. The OCR
grayscale never receives CLAHE, Gaussian filtering or binarization. Adaptive
block size is specified at 300 DPI and scaled to an odd value for the actual DPI.
No automatic small-component deletion is performed: dots can be genuine marks.

Deskew uses a <=1400-pixel-wide estimation image, a central region and coarse/fine
horizontal-projection searches. Near-horizontal pages remain unchanged. Sparse,
dense, ambiguous, low-gain and search-boundary results fall back to no rotation
and carry a review flag as appropriate. Angles are heuristic estimates, not
calibrated confidence probabilities. Manual `--angle` takes precedence.

Rotations expand the canvas with white borders. The default 40-million-pixel
per-page cap is checked before rendering and before allocating an expanded
rotation; exceeding it fails explicitly rather than silently changing DPI.
Pages are processed sequentially. Completed page outputs remain in a failed run
manifest if a later page fails; `error.json` records runtime failures.

### Coordinate convention

Page coordinates are **unrotated, crop-relative PyMuPDF top-left points**, not raw
PDF bottom-left MediaBox coordinates. Image coordinates are top-left pixels.
Matrices use homogeneous column vectors:

```text
processed_point = page_to_processed @ [page_x, page_y, 1]
page_point      = processed_to_page @ [pixel_x, pixel_y, 1]
```

Metadata also includes page↔raw and raw↔processed matrices. `map_box` transforms
all four corners before computing an enclosing box. Tests validate 0/90/180/270°
page rotations, nonzero crop origins, actual rendered marker positions and
forward/inverse round trips.

### Verified sample pages and limitations

Pages 9 (1896 printed text) and 17 (1903 printed contents/list page) were checked
at both 300 and 400 DPI. Pages 8 and 16, initially proposed from source captions,
turned out to be a cover reverse and binding-repair page; they are not body-text
evaluation candidates. The final user-approved selection uses ten rows on page 17.

The embedded scans are much smaller than the rendered pages. Increasing DPI
upsamples existing detail; it does not recover missing strokes. Detection binary
images retain paper noise and can fragment faint strokes. Always use raw or OCR
grayscale for transcription. The user approved the completeness of the selected
ten crops; broader candidate-line quality remains unmeasured.

## Line detection (offline)

```bash
.venv/bin/python -m khojki_ocr detect-lines \
  --input-run outputs/20261030T145327Z-77d40c12625b \
  --config configs/default.yaml
# Restrict to available input pages, optionally choose an output root:
.venv/bin/python -m khojki_ocr detect-lines \
  --input-run outputs/20261030T145327Z-77d40c12625b \
  --pages 17 --output-dir outputs
```

Use your own T04 run directory when reproducing on another machine. Input page
metadata, grayscale/binary file hashes, dimensions and forward/inverse matrices
are checked before detection. The command does not rerender the PDF. If the
original PDF is available and its hash matches, bottom Latin source-caption
blocks outside the embedded scan are excluded using their actual PDF positions.
If unavailable, captions are retained and `source_caption_unverified` is reported;
no hardcoded bottom-page crop is used.

### Method and configuration

`line_detection` settings in `configs/default.yaml` control the work image
(maximum width 1600; no upsampling), background normalization, component limits,
row grouping, gutters, mark recovery and crop padding. Work-image Otsu thresholding
is recomputed from background-normalized grayscale rather than reusing the noisy
high-DPI binary as the primary mask. This is detection-only processing.

Character-body components establish line bands. Horizontal morphology and
projection checks support grouping/splitting; nearby small components are then
recovered. Conservative straight-border/repeated-margin suppression is recorded.
Single and two-column layouts are supported, including staggered column baselines
and spanning headings. Persistent gutters require substantial text on both sides;
narrow aligned trailing groups are merged into the text row instead of creating
a numeric column. Three or more substantial groups generate a complex-layout
review warning; automatic reading order is not verified for arbitrary layouts.

The output is a **candidate set**, including `body`, `suspected_heading`,
`suspected_header`, `isolated_page_number_candidate` and `uncertain` classes.
Classes are geometric guesses, not OCR recognition. Ambiguous marks, possible
merges, overlapping content, border intersections and truncation are flagged.
Unsure decorative candidates are retained for review rather than silently
discarded. Low-contrast/unreliable pages may yield zero candidates plus a warning;
`min_intensity_range` is configurable for subsequent faint-page investigation.

### Outputs

Each new detection run contains `manifest.json`, `run.log`, and a per-page folder:

```text
pages/page-NNNN/
  detection-mask.png
  layout-overlay.png
  lines-overlay.png
  detection.json
  excluded-regions.json
  lines.jsonl
  crops/<line_id>.png
```

`lines.jsonl` records reading order, category, content/crop boxes, mapped PDF
four-corner polygons, source provenance, geometry, flags, crop paths and hashes.
Coordinates use the T04 processed grayscale; crops are copied **pixel-for-pixel
from the original-resolution gray.png**, not from the work mask. Padding is
bounded by page edges and neighboring non-overlapping line content.

IDs are deterministic for the same source grayscale, page, algorithm version,
configuration and box; output run names do not enter the identity. IDs and
candidate counts are not guaranteed stable across DPI/parameter changes. The
manifest records source-run provenance. Geometry is not a calibrated confidence.

### Current verification

- Full suite: 86 passing tests, including 15 T05 tests using rendered Khojki/Gujarati
  and controlled geometry for columns, numbering, marks, borders and failures.
- At 300 DPI, sample pages 9/17 produced 16/22 candidates; at 400 DPI, 18/23.
  Counts include uncertain/extra decorative and page-number candidates.
- Page 17's 15 numbered text rows remain joined to their trailing number groups
  at both DPIs. The class is still a geometric candidate, not verified OCR.
- Native grayscale crop pixels, hashes and PDF polygon mappings were checked;
  identical input/settings retained identical line IDs on repeat runs.
- Real overlays/crops were inspected. Some border/shadow candidates and ambiguous
  symbol assignments remain flagged. **Real recall, precision and CER are not
  established**. T06 completed selected-crop approval only; independent full-region
  line-box annotation and recall/precision measurement were not performed.

No cloud models, extra model downloads or paid requests are used by this step.

## Approved evaluation selection

**Final main selection:** `data/evaluation/selection.json`, original v1, detection
orders **6, 7, 9, 10, 11, 12, 13, 14, 15, 16**. After an intermediate line18/v2
replacement, the user inspected the line15 A/B comparison and explicitly restored
v1, accepting deletion of only U+11235. The intermediate set, its extra call and
the sample-change history remain available; do not present the selection as
random or general collection evaluation. See
[reports/t10-line18-replacement.md](reports/t10-line18-replacement.md).

The following describes the preserved original v1, now the final main selection:

`data/evaluation/selection.json` freezes ten user-approved crops from **PDF page
17, 300 DPI**, detection run `20261030T154139Z-8f9c0c0bcbcb`. Detection reading
orders are **6, 7, 9, 10, 11, 12, 13, 14, 15, 16**. Order 8 is an ornament and
excluded. Trailing Gujarati numbers (values 2–11) stay inside each transcription.

Images are copied to `data/evaluation/crops/`, with per-image SHA-256, original
line IDs, source hashes and boxes in the selection file. Image paths are relative
to `selection.json`, so later OCR should read this frozen selection instead of
reselecting numeric orders from a newer detection run. The freeze script is
`scripts/freeze_evaluation_selection.py` and refuses to overwrite an existing
selection directory.

The original selection file records **crop completeness**. Its transcription
fields remain null/pending to preserve the frozen source bytes. Current confirmed
Ground Truth is stored separately in `data/annotations/ground_truth.jsonl`, with
its own version and manifest; those are authoritative for T12.
Main CER will be limited to this selected clear subset; it must not be described
as whole-page detection recall or full-collection accuracy. Page 9 remains a
qualitative false-positive case. Complete manual line-box evaluation is optional
and was not performed. T07 implementation is documented in plan.md §8.1; the
first real smoke attempt and its failure are recorded in reports/t08-smoke.md.

## Visual transcription adapters (T07)

Prepare active-route requests offline, without API keys:

```bash
.venv/bin/python -m khojki_ocr recognize \
  --selection data/evaluation/selection.json \
  --provider openai --limit 10 --config configs/openai.yaml --dry-run
```

Generate `outputs/references-v1` first if needed using `build-reference`; it must
match the current Unicode/policy hashes. `recognition.reference_dir` can point to
another explicitly generated reference package. Each of the ten rows is prepared
for OpenAI: one TARGET LINE image followed by eight labeled
REFERENCE CHARTS. The manifest contains image sizes/hashes, request identities,
cache keys and budget-readiness status, not Base64 images or credentials. Expected
number values and Ground Truth fields in the selection never enter model prompts.

Use `--limit 1` to prepare the same single row as the completed OpenAI smoke test.
The historical CLI also supports `deepseek`/`both` for reproduction, but these are
not the active route and must not be automatically dispatched. There is **no implicit paid
mode**: one of `--dry-run`, `--cache-only` or `--execute` is required. The first live DeepSeek attempt is
recorded in reports/t08-smoke.md and needs review before further paid requests.
Paid calls require user approval after smoke-test output and cost review; T10's
fixed batch has received and used that approval. Further experiments need their
own explicit scope and authorization.

### Contracts and failure handling

- OpenAI: Responses API, `gpt-6.1-sol`, image detail `original`, strict JSON Schema,
  `store=false`. Actual model/parameter support remains a T08 check.
- DeepSeek: official Chat Completions, `deepseek-flash`, image detail `original`,
  JSON mode, `thinking=disabled`, followed by strict local validation.
- Model JSON contains `text`, `uncertain_spans` and `unreadable`. Span offsets
  index raw Unicode code points, end exclusive. Codepoints are computed locally;
  the result preserves raw response text, raw transcription, NFC and T03 issues.
- Refusal, truncation, whitespace-only output, invalid/duplicate-key JSON, unknown
  fields and invalid spans never become successful transcriptions. Invalid-script
  candidates and explicit uncertainty require review. `succeeded` describes a
  nonempty, contract-valid, encoding-valid response, **not established accuracy**.
- Raw SDK error bodies/headers and reasoning content are not persisted. Request
  IDs, usage totals/details, elapsed time and safe error types are tracked.

The official SDK is constructed lazily with `max_retries=0`. The project handles
at most two attempts by default for eligible 429/5xx responses, using Retry-After
or bounded backoff. A longer server-requested delay is not shortened. Timeouts,
auth failures, 404/model errors and invalid requests do not trigger blind retries
or model substitutions.

### Caching and output provenance

`recognition.cache_dir` defaults to `.cache/recognition`. A key covers provider,
endpoint/protocol, model, image bytes/hashes/order, image detail, prompt/Schema and
Unicode-policy versions, and relevant parameters. Pricing and API keys are not
part of answer identity. Successful/needs-review complete candidates are cached;
temporary failures are not cached as successes. Cache reads verify identity and
integrity; corruption blocks that request for explicit review. Per-key locks
prevent concurrent duplicate requests and writes are atomic.

An execution run records per-line/provider JSON under `results/`, `attempts.jsonl`,
and an incrementally saved manifest. Completed results survive a later failure.
A resumed request can reuse the prior cache even with a new run name. Cache hits
retain original response/usage provenance while recording zero new call cost.
Manifest `api_calls` counts adapter dispatch attempts, not confirmed billing.

### Budget and pricing required before T08

Both providers have `pricing: null` in the default configuration. Dry-run reports
`budget_ready=false` and no invented dollar estimate. Real dispatch is blocked
until each requested provider has a pricing object with:

| Field | Meaning |
|---|---|
| `model` | Exact requested model ID |
| `input_per_million_usd` | Verified conservative input rate as a decimal |
| `output_per_million_usd` | Verified output rate as a decimal |
| `source_url`, `checked_on` | Public pricing source and verification date |
| `max_input_tokens` | Verified upper bound for the complete request |
| `input_bound_basis` | How that bound covers images, reference charts, instructions and Schema |

Do not copy fictitious unit-test prices into real configuration. Tokenization
rules and model prices must be checked for the actual model/protocol before T08.
The configured output limit includes billable generated tokens. Cached-input and
reasoning usage are recorded as subsets, not billed twice; input is conservatively
estimated at the cache-miss rate.

The shared Decimal ledger is `.cache/api-budget.json`, capped at USD 15. Every
attempt reserves its upper-bound cost before dispatch. Missing/invalid usage,
timeouts, interrupted requests and unknown fees keep the reservation occupied;
they are not automatically refunded. Usage-based estimates settle known calls.
If a token bound is exceeded, the estimate is retained and further reservations
are blocked pending reconciliation. Per-ledger locks prevent concurrent overspend
against configured bounds. This is a conservative local estimate, **not a cloud
balance or final invoice**; its guarantee depends on correct rates/bounds.

Reuse the same ledger across providers and subsequent stages. Do not delete it or
switch its path to hide historical/unknown charges when resuming. A changed cap or
invalid ledger stops execution for review. Unknown fees must be reconciled against
provider evidence, not assumed free.

### Offline verification

All 215 tests pass, including 47 T07 tests, six smoke-policy/redaction checks, seven diagnostic tests, 23 batch tests, 25 offline-review tests, three replacement tests, five confirmation-transfer tests and 13 truth-freeze tests. The suite blocks real socket/DNS
network access. Actual SDK serialization is checked using `httpx.MockTransport`,
not paid services. Tests cover both protocols, strict parsing, Unicode, caching,
concurrent deduplication, retry limits, shared budget reservations, unknown costs,
accounting failure, and partial-batch resume. The frozen ten-line/two-provider
dry-run prepares 20 requests with **zero real model calls**. Ground Truth and CER
are now separated: Ground Truth is frozen by T11, while CER remains pending T12.

API contract references:
[OpenAI structured outputs](https://developers.openai.com/api/docs/guides/structured-outputs),
[DeepSeek vision](https://api-docs.deepseek.com/guides/vision), and
[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion).

### T08 live status

Current strategy supersedes the original two-provider plan: use
`configs/openai.yaml` and `--provider openai`. DeepSeek's adapter and results are
retained for failed-experiment documentation, not as a runtime prerequisite.
Its key is not required for the active workflow. D3 was cancelled immediately when
the user decided to stop.

`configs/smoke.yaml` limits each separately invoked provider to one attempt,
180 seconds and 4096 output tokens, using the shared USD 15 ledger. OpenAI
explicitly requests Standard (`service_tier=default`) and explicit-only cloud
caching with no breakpoints, to avoid automatic cache-write fees; local result
caching stays enabled. These parameters are part of request identity. This is
distinct from the unpriced generic default configuration. Cloud cache-write
fees must not be estimated using only the ordinary uncached-input rate.

Both local credentials were detected using `uv run --no-project --env-file .env`.
One DeepSeek call succeeded at transport/JSON level but returned a signs-only
sequence, strongly suggesting reference-chart confusion. Conservative usage-based
cost estimate: USD 0.0021081, not a confirmed invoice. After user approval, one
OpenAI control returned HTTP 401 / invalid_api_key with no usage. Its USD 3.74944
reservation stays held as unknown, NOT a confirmed charge. Neither provider was
automatically retried. The user later authorized one extra OpenAI attempt, which
returned a target-line candidate with three uncertain spans and no Unicode errors.
Its conservative configured-rate estimate is USD 0.103574, with 19,316 input and
1,754 output tokens. The response confirmed Standard/default and zero cloud cache
writes. The old 401 reservation remains; the current local remaining allowance is
USD 11.1448779 at that point. Subsequent D1/D1b/D2 diagnostics added USD 0.0010311
in conservative estimates. The pre-T10 remaining local allowance was USD 11.1438468;
the old unresolved reservation is still preserved.
The user has accepted the candidate/cost review and authorized the frozen ten
rows for OpenAI only. Reuse the first-row cache where identity matches, keep the
shared USD 15 budget, and do not treat model candidates as Ground Truth. Batch
execution is complete; see T10 below for the new costs and complete review bundle.

Diagnosis report: [reports/t08-deepseek-diagnosis.md](reports/t08-deepseek-diagnosis.md).
Target-only real/synthetic tests returned unreadable; a marks-only reference led
to repetitive output without the visible number. This supports discontinuing
DeepSeek under these settings, not a universal statement about model capability.
The synthetic control's CER 1.0 applies only to its eleven known rendered
codepoints, never the real scan. The suite has 146 passing offline tests.

The next active steps are manual Ground Truth confirmation and CER.
Freeze original machine predictions before human edits; corrected human output
must not be substituted for machine predictions when measuring OCR accuracy.

## Offline human-review bundle (T09)

The generated example can be opened directly in a browser:
`outputs/20261030T203951Z-a1a8e2919faa/index.html`. No web server, API key or network
font is required. Keep its folder together when copying it to another location.

```bash
.venv/bin/python -m khojki_ocr build-review \
  --selection data/evaluation/selection.json \
  --recognition-run outputs/20261030T185807Z-806667a839b0 \
  --output-dir outputs
```

The command reads an executed **OpenAI-only** recognition run, validates selection,
request identity, target image and result bindings, then freezes source bytes and
copies selected crops/reference images. It does not call models, load `.env`,
modify inference caches/fee ledgers or write confirmed Ground Truth. Use the T10
batch run as `--recognition-run` after that stage completes to fill all ten rows.

Each package contains:

```text
index.html                  read-only image/candidate/codepoint/uncertainty view
manifest.json               provenance and immutable artifact hashes
entries.jsonl               frozen review records, human status pending/draft
review-template.jsonl       intentionally editable proposed-text template
snapshots/                  exact source result, selection and run-manifest bytes
assets/crops/               all selected native-resolution grayscale crops
assets/references/          reference charts and their manifest
assets/licenses/            font and Unicode licenses
```

Both glyph fonts are embedded in HTML; the page has no JavaScript. Model text,
uncertainty explanations and draft notes are escaped. Candidate runs remain
continuous so combining marks shape correctly. Raw indices are zero-based Unicode
codepoints, not bytes, UTF-16 units, visible glyph counts or positions in the scan.
The uncertainty table shows the whole affected word and alternative context; it
does not invent image-character boxes. Dotted circles in codepoint tables are
display-only.

The historical T09 example displays the first row's candidate and three uncertain spans.
The remaining nine rows are `not_run`; requested-but-missing results are separately
`result_missing`, while failed API/model results remain `recognition_failed`.
`succeeded` from a model never upgrades human verification to confirmed.
The complete T10 bundle at `outputs/20261030T211104Z-ac77dcd92108/index.html`
now has all ten candidates, with every human status still pending.

### Import proposed edits as drafts

Fill `human_text` with the complete proposed line in one or more rows of
`review-template.jsonl`, optionally add `notes`, and leave untouched rows null.
Do not change line IDs, prediction hashes or base revisions. Rows with no frozen
machine result cannot be edited through this prediction-bound draft importer yet.
You may instead tell the assistant the overlay row and correction to prepare it.

```bash
.venv/bin/python -m khojki_ocr review-import \
  --bundle outputs/<review_run_id> \
  --edits outputs/<review_run_id>/review-template.jsonl \
  --reviewer "Your name"
```

Only the template is mutable; editing snapshots, entries or HTML causes integrity
checks to fail. Imported edits are always **DRAFTS**, even when Unicode-valid;
invalid Unicode drafts keep their issues. No T09 command accepts a confirmation
flag or creates Ground Truth. Machine predictions and their recognition states
are unchanged.

Revisions are atomically appended under
`data/annotations/reviews/<selection_id>/revision-000001.json`, etc., with reviewer,
time, prior-file hash, source prediction and bundle hashes. Locking and base/head
checks reject concurrent or stale imports. Rebuild the review package after an
import before submitting another revision. Runtime cache-hit/cost/timing changes
do not orphan a draft bound to identical machine content; changed prediction text
does not inherit an old correction automatically.

T09 tests use only temporary synthetic human edits. No real human draft has been
imported yet; all ten actual review statuses remain pending. See
[reports/t09-review.md](reports/t09-review.md) for tests and browser checks.

## Fixed ten-line batch (T10)

T10 used the unchanged active OpenAI configuration and fixed selection. Before any
calls the user confirmed separate API billing after clarification: an API key
does not imply that calls consume a ChatGPT/Codex weekly allowance, and the local
USD 15 budget is not prepaid credit or a cloud balance.

Offline checks (no credentials or API calls):

```bash
.venv/bin/python scripts/check_t10.py preflight
.venv/bin/khojki-ocr recognize --config configs/openai.yaml \
  --provider openai --limit 10 --require-first-cache-hit --dry-run
```

The already-authorized batch was executed once using:

```bash
"$HOME/.local/bin/uv" run --no-project --env-file .env .venv/bin/khojki-ocr recognize \
  --config configs/openai.yaml --provider openai --limit 10 \
  --require-first-cache-hit --execute
```

The first cache must be valid before dispatch; this guard requires `openai` and
`max_attempts: 1`. Requests run sequentially. System/transport/budget/billing or
cache/accounting persistence errors stop the batch; remaining requests are
explicitly unexecuted. Content-level failures with normal usage are saved and
processing continues without retry. **Do not use `--execute` to verify replay**:
failed/noncached requests could incur new charges. Use the offline mode instead:

```bash
.venv/bin/khojki-ocr recognize --config configs/openai.yaml \
  --provider openai --limit 10 --cache-only
```

Cache-only mode constructs no API adapters/clients or budget ledger, uses no API
key, and never falls back to network on cache misses/corruption. It reports every
row's cache status and writes a new local output run with zero dispatches.

Actual batch: `outputs/20261030T210414Z-23bc6581d98c/`. It contains `results/`,
`attempts.jsonl`, ten `predictions.jsonl` records, exact original candidate `.txt`
and separate `.nfc.txt` files in `transcriptions/`, export hashes and
`cost-summary.json`. Raw candidate files have no added terminal newline. Failed
or unexecuted rows are retained, not fabricated as empty answers. Machine records
and review drafts remain separate from confirmed human truth.

Nine new calls took 394.82 seconds in aggregate and used 172,980 input / 16,078
output tokens. The conservative usage estimate is USD 0.933090 with no new unknown
charges. Total local occupation is USD 4.7892432, including the unchanged historic
unknown reservation USD 3.74944; remaining local budget is USD 10.2107568. These
figures are not invoices or evidence of a subscription quota deduction.

The actual zero-call replay is `outputs/20261030T211103Z-eaf17206b7b3/`. Reproduce
the offline provenance, budget and prediction checks with:

```bash
.venv/bin/python scripts/check_t10.py verify \
  --baseline outputs/20261030T210401Z-967e07b306eb/preflight.json \
  --batch outputs/20261030T210414Z-23bc6581d98c \
  --replay outputs/20261030T211103Z-eaf17206b7b3 \
  --bundle outputs/20261030T211104Z-ac77dcd92108
```

See [reports/t10-batch.md](reports/t10-batch.md). These T10 outputs were initially
pending human confirmation; T11 subsequently froze the user-approved references.
Model-flagged uncertainty alone was not the confirmation criterion.

## Intermediate replacement experiment: line18 instead of line15 (historical v2)

This intermediate set contains ten lines, with nine previously confirmed rows retained.
`data/evaluation/selection.json` is still the original v1 and was not overwritten.
The user later restored v1 for final truth. The commands below reproduce only the
historical v2 experiment, using an explicit selection:

```bash
.venv/bin/khojki-ocr recognize --selection data/evaluation/v2/selection.json \
  --config configs/openai.yaml --provider openai --limit 10 --cache-only
.venv/bin/khojki-ocr build-review --selection data/evaluation/v2/selection.json \
  --recognition-run outputs/20261030T220010Z-5f33329394a2
```

The approved replacement was created with `scripts/replace_evaluation_line.py`,
which refuses to overwrite selections, verifies detection/crop hashes and retains
the old/new selection relationship. Its explicit trailing-number parameter avoids
assigning number 11 just because line18 is the tenth evaluation row. Three tests
cover identity/copy preservation, provenance checks and approval/overwrite guards.

The replacement run is `outputs/20261030T220010Z-5f33329394a2/`: nine cache hits,
exactly one new line18 call, 19,165 input / 1,712 output tokens, USD 0.10234 in
conservative usage estimates. Current occupation is USD 4.8915832 including the
same USD 3.74944 historical unknown reservation; remaining **local** budget is
USD 10.1084168, not a cloud balance. Replay
`outputs/20261030T220108Z-a349a6682bdc/` made zero calls.

Open `outputs/20261030T220108Z-b62819583332/index.html#p0017-l018-3fac6e9e7454`
to review **row 10 / overlay 18**. Line18 has two model-declared uncertainty spans
and remains unconfirmed. Changing the sample does not automatically remove OCR
uncertainty or complete T11.

`scripts/transfer_review_confirmations.py` verifies old/new bundles and image,
prediction and text identity before carrying forward the nine explicit user
confirmations. The record is
`data/annotations/page17-ten-lines-v2/confirmation-checkpoint.json`, with a hashed
snapshot of the original human confirmation notes. New line18 has no accepted
human text and cannot inherit confirmation. The generic T09 HTML still labels
human status pending; the separate checkpoint preserves the nine prior user
confirmations. This v2/line18 set was not fully confirmed. Final T11 truth instead
uses restored v1 as described below; T12 evaluates only that restored set.

## Frozen human reference (T11 complete)

The user explicitly chose “确认，采用 B 并冻结 v1”: restore line15 instead of
line18, accept the complete proposed line15 text with only raw `[21,22)` U+11235
deleted, keep the fourth group's II and all other characters unchanged, and
retain the prior nine user confirmations. No model inference created these
confirmations. The recorded method is model-assisted user visual review;
annotation duration is unknown/null, not inferred from freeze timestamps.

Artifacts:

```text
data/annotations/ground_truth.jsonl              ten confirmed raw/NFC references
data/annotations/ground_truth.manifest.json       active version/digest pointer
data/annotations/versions/ground-truth-v1/         truth, approval, selection,
                                                 source manifest/prediction snapshots
data/annotations/confirmations/page17-ten-lines-v1-final.json
                                                 explicit per-row human decisions
```

Each row binds image/prediction hashes, stores original machine text separately
from confirmed reference text, and records the exact human edit. Nine rows are
unchanged; line15 has one deletion. Original predictions/caches, both selection
versions and the budget ledger are unchanged. T11 made zero API calls.

The already-executed freeze command was:

```bash
.venv/bin/khojki-ocr freeze-truth --selection data/evaluation/selection.json \
  --bundle outputs/20261030T211104Z-ac77dcd92108 \
  --confirmation data/annotations/confirmations/page17-ten-lines-v1-final.json \
  --version ground-truth-v1 --confirm
```

Do not rerun it to overwrite truth: existing truth/version files are rejected.
Missing, duplicate, unconfirmed, source-mismatched or invalid-Unicode approvals
also fail. To verify the existing freeze without changing it:

```bash
.venv/bin/khojki-ocr verify-truth
.venv/bin/python scripts/check_t11.py
```

The latter verifies ten rows, the unique U+11235 deletion and 27 preserved
source/cache/budget file hashes. See
[reports/t11-ground-truth.md](reports/t11-ground-truth.md). T12 compares the
**original machine predictions**, not manually corrected outputs, against this
reference under the declared NFC/codepoint policy. Future truth corrections need
a new version and reevaluation.

## Offline CER evaluation (T12 complete)

Run and independently verify the saved-source evaluation without API credentials:

```bash
.venv/bin/khojki-ocr evaluate --truth data/annotations/ground_truth.jsonl \
  --output-dir outputs --include-historical-deepseek
.venv/bin/khojki-ocr verify-evaluation \
  --evaluation outputs/20261030T230213Z-afd44e1b89db
```

The formal run is `outputs/20261030T230213Z-afd44e1b89db/`. It stores per-row
metrics, codepoint alignments, aggregate/confusion JSON, an English report and
artifact/source hashes. Main OpenAI results are S=0, D=0, I=1 over 253 reference
code points: micro CER 0.003952569170, macro CER 0.003333333333 and 9/10 exact
rows. The sole observed error is a model-extra U+11235 on line15; it is an
insertion from hypothesis to reference even though the human correction action
deleted it from the machine candidate.

Historical DeepSeek first-row diagnostics are isolated in the appendix: D0 0.92,
D1 1.00 (empty output, all deletions), and D2 1.04. Their prompts/image packages
differ, so they are not a model average. D1b remains a synthetic-only CER 1.0 and
D3 was never run. No independent manual line boxes exist, so detection recall,
precision, IoU and manual-box CER are not reported. The selected clear-print set
and model-assisted reference introduce selection and anchoring bias. See
[reports/t12-evaluation.md](reports/t12-evaluation.md).

## Evidence-based error analysis (T13 complete)

```bash
.venv/bin/khojki-ocr analyze-errors \
  --attributions data/annotations/error-attribution-v1.json \
  --challenge data/challenges/t13/frozen/manifest.json \
  --evaluation outputs/20261030T230213Z-afd44e1b89db --output-dir outputs
.venv/bin/khojki-ocr verify-error-analysis \
  --analysis outputs/20261030T233828Z-bdf49aab235d
```

The formal run `outputs/20261030T233828Z-bdf49aab235d/` contains `cases.jsonl`,
`summary.json`, `report.md`, three evidence figures and the hash manifest. The
line15 U+11235 insertion is attributed to character recognition with user
confirmation and saved evidence; no internal model reasoning or precise glyph
pixel locations are claimed. No confirmed Unicode-mapping error was observed.
The main CER remains 1/253.

The two page-9 cases are qualitative detection failures with no manual-box metric.
Two manuscript crops from pages 1 and 5 are frozen under `data/challenges/t13/`.
Visual review found page-1 left clipping despite no detector flag; the user
explicitly accepted it as a qualitative failure example. Neither manuscript has
OCR predictions, reference text or CER. All T13 commands run offline, with zero
API calls and zero added cost. See [reports/t13-error-analysis.md](reports/t13-error-analysis.md)
for selection history, stage definitions, evidence and reproduction details.

The already-executed challenge freeze is reproducible only into a new directory:

```bash
.venv/bin/khojki-ocr build-challenge-set \
  --selection data/challenges/t13/selection.json \
  --output data/challenges/t13/frozen-replay
```

Existing frozen directories are rejected; do not overwrite them.

## API configuration

No API keys are required for offline commands. The active OpenAI adapter reads
exported `OPENAI_API_KEY`; `DEEPSEEK_API_KEY` is only relevant to historical
adapter reproduction, not the main workflow. The supplied
`.env.example` contains placeholders only; `.env` is not automatically loaded.
Do not paste real keys into documentation, logs or version control.

The active model is OpenAI `gpt-6.1-sol` via its official endpoint. DeepSeek
experiments failed and the provider was retired. OpenAI initially rejected the credential, then accepted the
user-authorized retry at the official endpoint. Image input and structured output
worked on that row, but the candidate is not verified Ground Truth. Never send key
contents in chat.
Batch paid calls require user approval after the single-line smoke test.

## Input material

- `Khojki_OCR_Take_Home.pdf`: two-page assignment.
- `sample_khojki_script_vatiations.pdf`: 47 pages, including manuscripts, printed
  books, covers and blank pages. Source captions on pages 1–34 credit Harvard's
  Houghton/Widener collections; the later image-only pages need source review.

Extractable English source captions are not Khojki reference transcriptions.
At least five lines require manually verified Ground Truth; ten is an optional
extension. The user has approved including the supplied PDFs in the submission.
