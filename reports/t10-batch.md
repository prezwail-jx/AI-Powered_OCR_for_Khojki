# T10 OpenAI Ten-Line Batch

## Outcome and authorization

T10 is complete. The user first approved the fixed ten-row OpenAI-only batch in
Q05. Before execution, the assistant clarified that official API calls normally
have separate API billing and should not be assumed to consume a ChatGPT/Codex
weekly allowance. The user then explicitly replied “同意” (agreed).

Only the frozen page-17 selection was processed, using unchanged
`configs/openai.yaml`, prompts, eight reference charts and `gpt-6.1-sol` Responses
requests. Overlay orders: **6, 7, 9, 10, 11, 12, 13, 14, 15, 16**.

- First row: verified T08 cache hit, zero new calls.
- Remaining rows: **9 actual requests**, one attempt each, sequential.
- **10 candidates**, all `needs_review`; zero failed/unexecuted rows.
- **26 model uncertainty spans**; these are not calibrated error probabilities.
- All human review states remain pending and Ground Truth remains null.
- No CER or real-scan accuracy is reported before independent human confirmation.

## Artifacts

| Artifact | Path |
|---|---|
| Offline request preparation | `outputs/20261030T210314Z-2847774f902d/` |
| Provenance/budget baseline | `outputs/20261030T210401Z-967e07b306eb/preflight.json` |
| First-row cache-only precheck | `outputs/20261030T210402Z-62f7a3649687/` |
| Real recognition run | `outputs/20261030T210414Z-23bc6581d98c/` |
| Ten-row cache-only replay | `outputs/20261030T211103Z-eaf17206b7b3/` |
| Complete review bundle | `outputs/20261030T211104Z-ac77dcd92108/index.html` |
| Offline verification | `outputs/20261030T211109Z-c9b147dbddae/verification.json` |

The recognition run contains exact raw responses in `results/`, dispatch records
in `attempts.jsonl`, ten machine records in `predictions.jsonl`, original UTF-8
candidate files and separate NFC files in `transcriptions/`, and
`cost-summary.json`. The original text files have no added terminal newline or
whitespace correction. Exports include per-source hashes and never set confirmed
human labels. The review bundle freezes source snapshots and copies all ten native
crop images with local reference charts and embedded licensed fonts.

## Usage and budget

| Item | Value |
|---|---:|
| New input tokens | 172,980 |
| New output tokens (including reasoning subset) | 16,078 |
| New dispatch elapsed time, summed | 394.82 seconds |
| New conservative usage estimate | USD 0.933090 |
| New unknown/reserved attempts | 0 |
| Prior budget occupation | USD 3.8561532 |
| Current budget occupation | USD 4.7892432 |
| Historical unknown reservation, still held | USD 3.74944 |
| All known historical usage estimates, combined | USD 1.0398032 |
| Remaining local budget under USD 15 cap | USD 10.2107568 |

These are configured conservative rates and local budget accounting, **not a
confirmed invoice or cloud balance**. The old HTTP-401 reservation was neither
deleted nor declared an actual charge. Reasoning tokens are already included in
output tokens, not charged twice. No DeepSeek calls or additional diagnostics ran.

## Implementation and failure policy

- `--cache-only` does not construct API adapters/clients or a budget ledger; cache
  missing/corrupt results are explicit errors and never fall back to paid calls.
- `--require-first-cache-hit` checks the first cache before dispatch and requires
  OpenAI with one configured attempt. The verified first prediction is directly
  reused rather than paid again if the cache later disappears.
- Authentication/model/parameter errors, transport/timeout/rate-limit errors,
  budget/cache problems and unexpected or unknown billing stop the batch. Cache
  or accounting write failures also stop further calls.
- A content-level refusal, empty output, truncation or invalid Schema with normal
  usage is retained as a failure and processing continues without retry.
- All requests are prepared up front. Stopped rows are explicitly unexecuted,
  distinct from missing results; the review builder preserves that distinction.

## Verification

- **194 offline tests pass**, including 23 batch-policy/cache-only/export cases
  and 25 review tests. `pip check` reports no conflicts. Seven existing SWIG
  deprecation warnings remain.
- Dry-run and first-row precheck used zero API calls. The preflight validated all
  frozen crops and references, request identities and the T08 prediction binding.
- All ten replayed candidates matched machine-prediction hashes, with **zero new
  calls**. Unit tests also verify byte-identical ledger preservation in cache-only
  mode and forbid client/ledger construction, including on missing/corrupt caches.
- Offline verification confirmed unchanged selection/config/pilot/reference
  hashes, intact historical ledger entries, nine new OpenAI attempt records,
  source/export hashes, correct budget occupation and all-pending human states.
- Opened the complete bundle in Chrome via `file://`: both fonts loaded, all ten
  images and candidate sections loaded, zero scripts/external HTTP(S) resources,
  no console errors/warnings. Visually checked the final row, continuous glyph
  shaping and alternative word contexts. No scan-character alignment is claimed.

## Next step

T11: manually inspect **all text**, not only flagged spans, and record proposed
corrections as drafts. Confirm and freeze the ten-row Ground Truth independently
before T12 CER. Keep original machine predictions unchanged. Do not automatically
request further recognition for an ambiguous character.
