# Reviewer reproduction

## Delivery split

`code.zip` contains source/tests/configs, the pinned environment, English reports
and planning history. `review-evidence.zip` contains only the selected benchmark
and historical provenance closure, not the complete working directory. Treat
the latter as **private exercise review only**. Neither zip contains input PDFs
or `.env`. Do not push the private zip to a public repository.

The exporter uses a finite allowlist and writes an index of each file's SHA-256.
It scans source bytes and reads back actual zip entries for credential patterns
and locally known secret values, reporting paths/rules rather than secret text.

## Export from the author's verified workspace

```bash
.venv/bin/python scripts/export_evidence.py --output /absolute/new/delivery-directory
```

The output directory must not exist. `packages.json` records the two zip hashes.
Historical source files are copied byte-for-byte; the exporter does not rewrite
absolute paths, predictions, truth or budget history. Private historical caches
and the ledger are copied as immutable replay evidence, not as a fresh live budget.

## New reviewer directory

1. Unzip `code.zip` and the privately provided `review-evidence.zip` into the same
   new directory, preserving paths including `.cache/` and `outputs/`.
2. Create a new local `.venv` and install exactly as in README. The recorded
   platform is macOS arm64 / Python 3.11.18; other platforms are not verified.
3. Run `.venv/bin/python scripts/reproduce_offline.py --output outputs/replay`.
4. Run `.venv/bin/python -m pytest -q` and `.venv/bin/python -m pip check`.

The evidence index supplies the original project root solely for explicit
old-root-to-new-root mapping. The replay confines reads to the new tree, blocks
network and actual file reads from the author's original workspace, and fails
on missing or mismatched evidence. No fallback to the old tree is permitted.
An autouse test fixture applies the same provenance mapping in the full test
suite; synthetic test roots remain isolated pytest temporary directories.

Original `verify-evaluation`/`verify-error-analysis` commands are convenient in
the author's tree; the replay wrapper is the relocation-aware entry point for
an extracted delivery. It calls the same verifiers and independently recomputes:

- T12 per-line/aggregate CER, confusion and DeepSeek appendix, byte-identical to
  the original core output files;
- T13 summary and cases, byte-identical to the original core output files.

Generated run IDs, timestamps and new absolute provenance paths naturally differ;
they are not part of the core byte comparison. Immutable original manifests are
still hash-verified. No human reference is regenerated or reconfirmed by replay.

## Full image flow

Privately place the exact original `sample_khojki_script_vatiations.pdf` in the
reviewer tree. The replay accepts it only if its SHA-256 matches the benchmark:

```bash
.venv/bin/python scripts/reproduce_offline.py \
  --pdf sample_khojki_script_vatiations.pdf --output outputs/full-replay
```

This renders pages 9/17 at 300 DPI, detects lines and verifies the ten selected
IDs, crop hashes and geometry against the frozen selection. Image drift fails;
the runner does not update expected hashes to hide a library/platform change.
Saved-prediction replay is not fresh live inference. Recalling a paid visual
model may yield different output and requires current access, credentials and
explicit budget approval; it is not needed to reproduce these metrics.

## Failure handling

Keep the first error and generated records. Missing evidence means the private
overlay or a referenced file is absent. A hash mismatch means changed/corrupt
input. Image drift requires investigation of Python/native library versions and
rendering configuration. Do not delete the ledger, weaken checks, replace truth
or silently exclude a failing line. Install-time internet is separate from the
network-blocked inference/evaluation phase.
