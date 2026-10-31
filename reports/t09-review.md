# T09 Offline Review Bundle Verification

## Result

T09 is implemented and verified without model calls. The current real-data bundle
is `outputs/20261030T203951Z-a1a8e2919faa/index.html`.

- Frozen selection: page 17, overlay orders 6, 7, 9, 10, 11, 12, 13, 14, 15, 16.
- Source recognition run: `outputs/20261030T185807Z-806667a839b0/`.
- Ten row cards and ten unchanged source-crop copies.
- One extracted OpenAI candidate (overlay 6), three model uncertainty spans.
- Nine rows explicitly marked not yet recognized, not fabricated empty answers.
- All human states pending; no real human draft or Ground Truth was created.

## Bundle

`index.html` is a read-only, script-free offline document with embedded licensed
Khojki/Gujarati fonts. Native images, word-context alternatives, raw codepoint
tables, Unicode issues and source snapshots are available locally. Text offsets
are not represented as scan coordinates. Full candidate runs stay intact to avoid
breaking combining-mark shaping; codepoint rows use display-only dotted circles.

`entries.jsonl` and snapshots are immutable facts protected by hashes in the
manifest. `review-template.jsonl` is deliberately editable and is not included in
that immutable-file map. Editing a template never changes a machine prediction.

The machine-prediction hash excludes runtime cost/cache-hit/elapsed fields, so a
later cached batch result can retain draft bindings. Full source-file hashes and
unaltered result bytes are also preserved for provenance.

## Draft workflow

`review-import` accepts full proposed text plus line ID, prediction hash, base
revision and notes, with a reviewer supplied explicitly. All proposed records are
validated before an append-only revision is created under
`data/annotations/reviews/<selection_id>/`. File locking, revision sequencing and
previous-file hashes guard against stale/overwritten edits. Rebuild the bundle to
view the newest drafts before importing another revision.

Imported records are always drafts, even if Unicode-valid. Invalid Unicode drafts
retain their issues. Failed machine predictions stay failed even if a human draft
is added. No T09 command can confirm Ground Truth. That remains T11.

## Verification

- 170 offline tests pass: previous 146 plus 24 T09 cases, including complete cached
  batch reuse and both missing-file/missing-record distinctions.
- Coverage includes selection/target/provider/source mismatches, missing results,
  source byte preservation, stale edits, snapshot/journal tampering, cache-hit
  provenance, draft versioning, invalid Unicode, forbidden confirmation fields,
  failure-state preservation, NFC/raw indices and HTML escaping.
- `pip check`: no broken requirements; seven existing PyMuPDF/SWIG deprecation
  warnings, no failures.
- Opened the real HTML directly using a local `file://` URL in Chrome.
- Both embedded fonts loaded; all ten crop images loaded at their expected native
  sizes. There were ten row cards, zero scripts and no external HTTP(S) resource
  URLs. Browser console reported no errors/warnings.
- Visually checked the first card's source crop, continuous candidate rendering,
  and model alternative word contexts. No precise image-character alignment is
  claimed.

No server, model request, fee-ledger mutation or Ground Truth update is required.
T10 batch execution is already authorized by Q05 but has not been run in T09.
