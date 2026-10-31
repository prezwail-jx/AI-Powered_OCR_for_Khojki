# T15 Final Local Acceptance

## Decision and boundary

The user explicitly selected **“通过本地验收”** after reviewing the final scope,
limitations, cost accounting and remaining publication tasks. T15 local delivery
is accepted. This is **not a claim that the assignment has already been submitted**:
no Git repository, GitHub URL, public upload or email submission has been created.

Technical verification: [t15-verification.json](t15-verification.json).
User decision: [t15-signoff.json](t15-signoff.json).
Final code/private-evidence archives and checksums: `outputs/t15-delivery/`.
The earlier `outputs/t14-delivery/` remains unchanged as historical evidence.

## P0 requirements matrix

All 13 P0 requirements are satisfied within the explicitly selected ten-row
printed OCR scope. “Each line” means each selected evaluation line, not all 47
pages or every detector candidate.

| ID | Local result | Evidence |
|---|---|---|
| FR-01 | Pass: PDF, pages, output directory accepted | `cli.py`, `config.py`, CLI help and foundation tests |
| FR-02 | Pass: configurable DPI | T04 300/400 DPI runs; T14 300 DPI clean replay |
| FR-03 | Pass: grayscale, contrast enhancement and guarded deskew | `preprocess.py`; separate recognition/detection image routes |
| FR-04 | Pass: full-page geometric line detection and reading order | `line_detection.py`; page-9/page-17 clean replay yields 16/22 candidates; no accuracy claim |
| FR-05 | Pass: line boxes, page coordinates and crops retained | detection JSONL, overlays and crop hashes |
| FR-06 | Pass: ten independent OpenAI predictions | original T10 result records, frozen raw prediction archive; first row reused the original independent pilot |
| FR-07 | Pass: text-offset uncertainty, alternatives and review material | original `uncertain_spans`, T09/T10 review records; no pixel-box claim |
| FR-08 | Pass: raw predictions, Unicode reports and human edits preserved | `ground_truth-v1`, explicit confirmation and line15 edit trail |
| FR-09 | Pass: assigned Khojki, Gujarati digits and punctuation checked | Unicode 17.0.0 rules/tests; all ten actual predictions and references pass |
| FR-10 | Pass: UTF-8 text, JSONL and codepoint arrays | T10 export manifest; ten raw `.txt` files decode strictly and equal original candidates |
| FR-11 | Pass: ten user-confirmed references | `data/annotations/ground_truth.jsonl`, frozen archive; model-assisted review disclosed |
| FR-12 | Pass: per-row, micro/macro CER and exact-line rate | T12 deterministic alignment, `summary.json`, `lines.jsonl` |
| FR-13 | Pass: stage definitions and evidence-bound breakdown | T13: main recognition 1, detection/mapping 0; two detection failure examples separately; unknown/mixed allowed |

P1: FR-14 caching/recovery is implemented and tested; FR-15 model/config/token/cost
metadata is retained; FR-16 printed and manuscript observations are reported
separately, with no unmeasured manuscript OCR metric manufactured.

## PRD acceptance criteria

| # | Criterion | Result/evidence |
|---|---|---|
| 1 | Two full printed pages processed | Pass: PDF pages 9 and 17, original T04/T05 and T14 clean replay |
| 2 | At least five real lines detected and recognized | Pass: ten original selected printed rows |
| 3 | All scored rows have human-confirmed truth | Pass: ten confirmed rows, `ground-truth-v1` |
| 4 | Valid UTF-8 final text | Pass: original exports decoded strictly; JSONL and scalar arrays verified |
| 5 | Nonempty final text is Unicode-valid | Pass: actual ten predictions and ten references checked; this does not mean visually correct |
| 6 | Per-line/overall CER and exact-line rate | Pass: 1/253 micro, 0.003333333333 macro, 9/10 exact |
| 7 | Insertions/deletions/substitutions and confusions | Pass: S=0/D=0/I=1; U+11235 insertion; no substitution pairs observed |
| 8 | Detection/recognition/mapping analyzed separately | Pass: evidence-based T13 report, qualitative detection scope and zero observed mapping caveat |
| 9 | English installation-to-report README | Pass: concise README plus reproduction instructions; fresh-directory installation/replay verified |
| 10 | English retro at most one page | Pass: one A4 page, 10 pt, all Markdown text present in PDF, visually checked |
| 11 | Cost does not exceed USD 15 | Pass on conservative local accounting: USD 4.8915832 including unknown reservation; vendor invoice unknown |
| 12 | No API keys in code/submission | Pass for inspected source/archive entries and 35 historical log/error files; `.env` excluded; no Git repository yet |

## Nonfunctional requirements

- NFR-01: CPython 3.11.18 in isolated `.venv`; current and clean environment tests pass.
- NFR-02: allowlisted export scans known secret values/patterns; no `.env` in packages.
- NFR-03: default tests block sockets; T15 dispatches no provider client/request.
- NFR-04: same saved inputs reproduce T12/T13 core bytes; live-model output stability is not promised.
- NFR-05: per-line saved state, failure/retry/cache/budget paths are tested; no failing row is silently removed from CER.
- NFR-06: line/image/model/prediction/truth/version hashes bind each evaluated result.
- NFR-07: shared USD 15 cap and unknown reservation are retained. The nominal USD 5-15 budget is not a minimum-spend requirement.

## Results and cost

| Item | Accepted value |
|---|---:|
| Main rows / reference codepoints | 10 / 253 |
| Micro CER | **1/253 = 0.003952569170** |
| Macro CER | **0.003333333333** |
| Exact rows | **9/10** |
| Main S / D / I | **0 / 0 / 1** |
| Ten original request elapsed sum | 442.3611 s |
| Ten original request cost estimate | USD 1.036664 |
| All recorded usage estimates | USD 1.1421432 |
| Unknown historical reservation | USD 3.74944 |
| Total locally accounted | USD 4.8915832 |
| Remaining local allowance | USD 10.1084168 |
| T15 new API calls / fees | **0 / USD 0** |

DeepSeek D0/D1/D2 historical first-row CER: 0.92/1.00/1.04 under different
configurations, never combined into a second-model aggregate. D1b is synthetic
only (1.00), D3 was cancelled. Line18/v2 remains a separate historical experiment,
excluded from main truth. Both expenditures and the unknown amount remain in the ledger.

## Explicitly accepted limitations and remaining work

1. Clear selected printed crops and candidate-assisted review introduce selection
   and anchoring bias; this is not expert-blind or collection-wide accuracy.
2. Human annotation duration is unknown; it is not inferred from timestamps.
3. No complete independent manual boxes: recall, precision, IoU and detection CER
   delta are unmeasured. Candidate counts are not detection accuracy.
4. Two manuscript crops are qualitative and untranscribed; the page-1 crop is a
   user-accepted clipping failure despite no detector flag, not a complete OCR input.
5. Usage estimates and unknown reservations are not vendor-confirmed billing.
6. Code/textual reports and private scan evidence are separate. Full PDFs are
   privately supplied by the reviewer, not included in either archive.
7. Cross-directory reproduction is tested on macOS arm64/Python 3.11.18, not all platforms.
8. Code-license selection, Git/GitHub initialization/publication and sending the
   GitHub link to the evaluator remain subsequent tasks requiring explicit direction.

These boundaries were included in the user's acceptance question; none is
silently presented as completed work. All local T01-T15 tasks can be closed;
the external submission milestone remains outstanding.
