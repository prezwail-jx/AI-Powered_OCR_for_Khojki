# User-Directed Replacement: Line15 → Line18

**Historical experiment:** the user subsequently accepted line15 option B and
explicitly restored the original v1 set for the final ten-row reference. T11 is
complete; see [t11-ground-truth.md](t11-ground-truth.md). The v2 records and its
additional cost below are preserved, not part of the main frozen truth set.

## Reason and scope

The user had confirmed nine original rows and left line15's Virama-like mark
unresolved. After inspecting the output, the user explicitly requested line18
instead. The new crop was shown and the user confirmed “完整，可以识别” (complete;
recognition approved), including the approximately USD 0.10 extra-call estimate.

This is a **post-inspection sample change**, not a random evaluation set. Report
any eventual CER as conditional on this user-selected subset; do not infer
whole-page or collection accuracy. Line15 remains an unresolved qualitative case,
not a proved OCR error. Its original crop, prediction and review records remain
available. No original selection or result was overwritten.

## Active selection

- New selection: `data/evaluation/v2/selection.json`, `page17-ten-lines-v2`.
- Detection orders: **6, 7, 9, 10, 11, 12, 13, 14, 16, 18**.
- Line18: `p0017-l018-3fac6e9e7454`, page 17, 300 DPI; right-hand Gujarati number
  **૧૩ (13)**. Number 13 is preserved, not inferred from evaluation order 10.
- The nine retained images/line identities are unchanged; line16 is now review
  row 9 and line18 is review row 10.
- The v1 selection at `data/evaluation/selection.json` is historical. CLI defaults
  still name that historical file; use **explicit `--selection
  data/evaluation/v2/selection.json`** for the active set.

## Execution and artifacts

| Artifact | Path |
|---|---|
| Offline request preparation | `outputs/20261030T215853Z-40802aa5b58b/` |
| Nine-hit/one-miss preflight | `outputs/20261030T215952Z-e870a8d4d783/preflight.json` |
| Recognition run | `outputs/20261030T220010Z-5f33329394a2/` |
| Zero-call replay | `outputs/20261030T220108Z-a349a6682bdc/` |
| New ten-row review bundle | `outputs/20261030T220108Z-b62819583332/index.html` |
| Provenance/budget verification | `outputs/20261030T220303Z-79e55fe77922/verification.json` |
| Nine-confirmation transfer | `data/annotations/page17-ten-lines-v2/confirmation-checkpoint.json` |

Exactly **one new OpenAI call** was made, for line18, using unchanged model,
prompt, eight reference charts and pricing configuration. The other nine rows
were cache hits. No retries, DeepSeek calls or other diagnostics were dispatched.

Line18's raw candidate (not Ground Truth):

> 𑈤𑈲𑈂𑈺𑈞𑈯𑈦𑈈𑈬𑈺𑈩𑈙𑈊𑈯𑈦𑈺𑈪𑈯𑈁𑈺 ૧૩

It remains `needs_review`, with two model uncertainty spans:

- `[2,3)`: current U+11202, alternative U+11240 U+11238; uncertain boundary near
  thick upper strokes. Alternatives are model suggestions, not accepted edits.
- `[10,11)`: current U+11229 (SA), alternative U+1121A (THA).

Replacing an unresolved row did **not** automatically resolve uncertainty. The
user must inspect all of line18, not only these two spans.

## Cost

- New usage: **19,165 input / 1,712 output tokens**; reasoning is included in
  output, not counted twice.
- New conservative usage estimate: **USD 0.10234**; no new unknown fees.
- Dispatch duration: **42.36 seconds**.
- Total local occupation: **USD 4.8915832**, including historical unknown
  reservation **USD 3.74944**, still held.
- Remaining local budget under the USD 15 cap: **USD 10.1084168**.

These are configured-rate estimates/reservations, not final invoices or cloud
balances. Previous attempts and fees were retained even though the sample changed.

## Verification and human status

- **202 offline tests pass**, including three replacement tests and five
  confirmation-transfer tests; `pip check` passes.
- Offline verification confirmed exactly one new attempt, unchanged historical
  ledger entries, export hashes, the frozen sources and zero-call cache replay.
- The confirmation-transfer tool independently verifies both old/new review
  bundles and matches stable line ID, image hash, machine-prediction hash and text
  before carrying forward each of the **nine explicit user confirmations**.
  Changed images/predictions/text fail rather than inherit confirmation.
- The original human checkpoint was copied with its SHA-256. The added line stays
  **pending** with no accepted human text. No complete Ground Truth was frozen.
- The generic T09 HTML labels remain pending until a final truth workflow; the
  separate transfer checkpoint is the record of the nine user confirmations.
  This does not ask the user to redo those nine rows.
- Browser: ten image/candidate sections loaded, both embedded fonts loaded, no
  scripts/external HTTP(S) resources or console errors/warnings. Open directly at
  `index.html#p0017-l018-3fac6e9e7454` to inspect the replacement.

## Next action

T11 remains in progress: obtain the user's final line18 transcription, then
freeze the new ten-row truth version and calculate T12 CER against the unchanged
machine predictions for this new selection. Preserve line15's unresolved case in
the limitations/error-analysis discussion.
