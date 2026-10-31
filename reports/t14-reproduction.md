# T14 Delivery and Clean-Environment Verification

## Completed work

- Replaced the long chronological README with a reviewer-facing installation,
  result and reproduction guide; history remains in `docs/implementation-history.md`.
- Added the formal evaluation, one-page technical retro, source/license guide
  and relocation-aware reviewer instructions.
- Added `requirements-repro.txt`, explicit evidence export, archive hash/credential
  checking and an offline replay entry point. Original frozen files are unchanged.
- The user selected separate delivery: full PDFs privately supplied by the reviewer;
  scan-derived evidence privately provided, not assumed cleared for public release.

## Clean environment

A new reviewer directory was populated solely from the exported code/evidence
archives plus a separate copy of the original PDF. A new local `.venv` was created
with uv and CPython 3.11.18; no system site-packages or original project package
were reused. Dependencies were freshly installed into this environment from
`requirements-repro.txt` (pip reused its download cache). The package was installed
editable against the **reviewer copy**, not the original workspace.

Actual platform: **macOS 26.6 arm64**. Other platforms are not claimed as tested.
API credential environment variables were unset for test/replay commands.

Machine-readable installation, environment and results are in
[`t14-reproduction.json`](t14-reproduction.json). The raw runner report is retained
under the temporary reviewer tree at `outputs/clean-full-replay/reproduction.json`;
its byte-for-byte copy is [`t14-clean-replay.json`](t14-clean-replay.json), so the
actual results survive deletion of that temporary tree.

## Results

| Check | Result |
|---|---|
| New-environment pytest | **240 passed**, 7 existing SWIG deprecation warnings |
| Dependency consistency | `No broken requirements found.` |
| Saved-source CER | **1/253**, 9/10 exact; unchanged |
| T12 core JSON/JSONL/appendix comparison | Byte-identical |
| T13 core cases/summary comparison | Byte-identical |
| Original author-workspace reads during replay | Blocked by Python audit hook |
| Replay network access | Blocked |
| PDF pages rerendered | 9, 17 at 300 DPI |
| Detected line candidate counts | 16, 22 |
| Ten selected IDs, crop hashes and geometry | Match frozen selection |
| Retro PDF | 1 A4 page; 10 pt; extracted text complete; preview visually checked |
| New API calls / fees | **0 / USD 0** |

The original project also passed all **240** tests after the changes. The source
baseline checked **159 unchanged files**, including the budget, truth, frozen
prediction/cache/selection evidence and formal T12/T13 artifacts.

The measured request timing and estimated costs are derived separately in
[`t14-measured-metrics.json`](t14-measured-metrics.json); install/test/image replay
time is not substituted for original paid request latency.

## Deliverables

Final packages are generated into `outputs/t14-delivery/`:

- `code.zip`: source/tests/config, English reports and environment inventory;
- `review-evidence.zip`: **private exercise review only**, hashed raw predictions,
  truth, selected crops, historical diagnostics and required read-only snapshots;
- `packages.json`: hashes, sizes and file counts for both archives.

No input PDF, `.env` or credentials are included. The exporter checks each file
before adding it and checks actual zip-entry bytes after writing. The frozen
baseline verifies source invariance; package verification checks for missing,
changed or escaping paths. Public publication and code licensing remain T15
decisions; no Git repository was initialized and no files were uploaded.
