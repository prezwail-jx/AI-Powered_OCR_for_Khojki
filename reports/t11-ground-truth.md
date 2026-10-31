# T11 Human-Confirmed Ground Truth Freeze

## Final decision

The user explicitly selected **“确认，采用 B 并冻结 v1”** after viewing the native
line15 crop comparison and both full-line alternatives. This confirms:

- Restore the original selection `page17-ten-lines-v1`: overlay orders
  **6, 7, 9, 10, 11, 12, 13, 14, 15, 16**.
- Accept the nine previously user-confirmed transcriptions unchanged.
- For line15, delete **only U+11235 VIRAMA at raw interval `[21,22)`**. Keep all
  other characters, including the fourth group's II vowel and Gujarati ૧૦.
- Retain the intermediate v2/line18 experiment, but exclude it from this main
  reference version. Preserve its already-incurred cost and all sample-history
  records rather than silently hiding the replacement and restoration.

The final fifth group is **𑈙𑈡**, rather than the machine's **𑈙𑈡𑈵**. The original
machine prediction is unchanged and remains the prediction to evaluate in T12.

## Method and limits

This reference is **model-assisted, user-confirmed visual transcription**, not
blind independent expert transcription. The nine original confirmations and the
final full-line approval are recorded explicitly. The annotator is identified as
`user_in_conversation`; no personal name was provided. Actual annotation start/end
times and duration were not reported, so duration is null. Confirmation-record
and freeze timestamps describe file creation, not labeling time.

Repeated-word consistency and the cropped scan comparison helped identify the
questionable mark. Neither a 5:1 model majority nor equal crop widths constitutes
proof by itself. The final reference records the user's adjudication; it does not
claim that the images are pixel-identical or that a specific failure mechanism
has been proved. A broken BA terminal stroke being interpreted as an extra mark
remains a possible explanation for the model output.

## Frozen artifacts

| Artifact | Path |
|---|---|
| Primary UTF-8 truth JSONL | `data/annotations/ground_truth.jsonl` |
| Active pointer and digest | `data/annotations/ground_truth.manifest.json` |
| Immutable version directory | `data/annotations/versions/ground-truth-v1/` |
| Explicit per-line approval | `data/annotations/confirmations/page17-ten-lines-v1-final.json` |
| Source-preservation baseline | `data/annotations/confirmations/t11-source-guard.json` |
| Verification | `outputs/20261030T223526Z-de47b01a51d1/verification.json` |
| Human-readable A/B comparison | `outputs/20261030T221931Z-f5afa6843c01/index.html` |

The archived version includes truth JSONL, selection, human confirmation,
source-review manifest and all ten exact original prediction snapshots, with file
SHA-256 values. Each truth row records image/prediction binding, raw and NFC truth,
codepoints, confirmation metadata and an edit trace. All ten rows are confirmed;
exactly one row has a human edit, consisting of that one deletion.

Truth-file SHA-256:

```text
216a152424ef11258c1885fdd59d10899a8e4d2de44d49acb5e38008488e3a16
```

The crop-selection JSON is preserved byte-for-byte. Its old pending truth fields
are historical selection-time metadata; current confirmed truth is authoritative
in the separately frozen JSONL and manifest.

## Implementation and checks

- `freeze-truth` requires an explicit `--confirm` and strict per-line human
  approvals covering every selected row exactly once. Selection/review/image/
  prediction hash mismatches, unconfirmed/duplicate/missing rows and invalid
  Unicode are rejected. Existing truth or version files cannot be overwritten.
- `verify-truth` checks the primary truth against the archived copy and verifies
  all source/approval/file hashes. Publication writes the active manifest last;
  incomplete artifacts cannot pass verification.
- **215 offline tests pass**, including 13 truth-freeze tests covering source
  preservation, one-codepoint edits, invalid/incomplete approvals, tampering,
  no implicit freeze and refusal to overwrite. `pip check` passes; seven existing
  SWIG deprecation warnings remain.
- `scripts/check_t11.py` confirmed ten finalized rows, nine unchanged texts, the
  exact line15 deletion and **27 unchanged source/cache/budget file hashes**.
  Ledger attempts remain 16. T11 made **zero API calls** and no new cost.

## Next: T12

No CER has been computed in T11. T12 must compare the archived **original machine
predictions** with this frozen truth, using the declared NFC/codepoint policy.
Do not replace the prediction with the corrected reference. Any future reference
correction must create a new version and trigger reevaluation.
