# T08 Single-Line Smoke Test

## Status

**OpenAI authentication now works following a user-authorized retry.** It returned
an encoding-valid target-line candidate with three explicit uncertain spans.
The user later decided to drop DeepSeek after three additional diagnostic cases;
the planned D3 ordering trial was cancelled before dispatch. The active route is
OpenAI-only plus human verification. Total: four DeepSeek attempts and two OpenAI
attempts (one 401, one accepted inference). There were no automatic retries or
batch recognition. The user has now accepted the OpenAI-only candidate/cost
review and authorized the frozen ten-row batch; T08 is complete for that route.
Batch execution (T10), manual Ground Truth and real-scan CER remain pending.

## Approved setup

- Frozen sample: PDF page 17, overlay order 6, line ID
  `p0017-l006-2dcc97e9dc05` (first evaluation row).
- Target crop: `data/evaluation/crops/p0017-l006-2dcc97e9dc05.png`.
- One target image and eight separately labeled reference charts per request.
- `configs/smoke.yaml`: one attempt per provider, 180-second timeout, maximum
  4096 output tokens, shared USD 15 budget.
- User approved disabling OpenAI cloud cache writes while retaining local result
  caching, and disabling automatic smoke-test retries.
- OpenAI payload now explicitly requests `service_tier=default` and
  `prompt_cache_options={mode: explicit, ttl: 30m}` with no cache breakpoints.
  These settings have passed SDK/mock tests but are not yet live-verified.
- OpenAI reservation uses the model's official 922,000 maximum input and Standard
  long-context rates, USD 4/15 per million input/output tokens. DeepSeek uses
  peak cache-miss USD 0.30/1.20 and a deliberately loose 2M input upper bound above
  its documented 1M total context. These are conservative bounds, not predicted
  actual input sizes or invoices.
- Pricing checked 2026-10-30:
  [OpenAI model](https://developers.openai.com/api/docs/models/gpt-6.1-sol),
  [OpenAI caching](https://developers.openai.com/api/docs/guides/prompt-caching),
  [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing).

## DeepSeek attempt 1

| Item | Observed result |
|---|---|
| Requested / returned model | `deepseek-flash` / `deepseek-flash` |
| API dispatch attempts | 1 |
| Elapsed | 2.371886 seconds |
| Input tokens | 6,723 |
| Output tokens | 76 |
| Cached input tokens | 0 |
| Reasoning tokens | Not returned (`null`), not assumed zero |
| Application status | `needs_review` |
| JSON/Schema | Parsed successfully |
| Unicode whitelist | Valid, with two isolated-mark warnings |
| Conservative cost estimate | USD 0.0021081, not a confirmed invoice |
| Ledger unknown charges | 0 |
| Remaining ledger budget | USD 14.9978919 |

Run: `outputs/20261030T173809Z-e8fce2637d69/`.
Result: `results/deepseek-p0017-l006-2dcc97e9dc05.json` in that run.

Returned candidate codepoints:

```text
U+1122C U+1122D U+1122E U+1122F U+11234 U+11235 U+11236 U+11237
U+11238 U+11239 U+1123A U+1123B U+1123C U+1123D U+1123E
```

This output consists only of combining/vowel signs and punctuation. It contains
no base Khojki letters and omits the visible trailing Gujarati number. The target
clearly contains a full printed text line. The candidate is therefore not an
acceptable transcription. It strongly suggests reference-chart copying or
target/reference confusion, but the internal cause has not been established.

The model returned `unreadable=false` and no uncertainty spans despite this
failure. This is an example of why JSON validity, Unicode validity and a model's
self-report do not establish OCR correctness.

## OpenAI

After the DeepSeek failure, the user explicitly chose to run the originally
planned single OpenAI control with the same input. It was attempted once and not
retried.

| Item | Observed result |
|---|---|
| Requested model | `gpt-6.1-sol` |
| Application status | `authentication_error` |
| HTTP status / provider code | 401 / `invalid_api_key` |
| Returned model | Not returned |
| Transcription / usage | Not returned |
| Attempt elapsed | Approximately 0.68 seconds |
| Reservation retained as unknown | USD 3.74944 |
| Confirmed charge | Unknown; reservation is NOT a confirmed charge |

Run: `outputs/20261030T174836Z-5d78d0d83615/`.
Authentication failed before a usable model response was received. This does not
establish that the model or image/Schema parameters are unsupported.

Only selected redacted diagnostics are retained. The provider's masked key
prefix/suffix was also fully removed from our result/attempt files; error code,
request ID, timing and budget records remain unchanged.

### OpenAI attempt 2 — user-authorized retry

The user requested another attempt after the authentication failure. Only OpenAI
was retried, once, on the same frozen crop/reference package. No endpoint, model,
prompt, output limit or reference package was changed by the agent.

| Item | Observed result |
|---|---|
| Requested / returned model | `gpt-6.1-sol` / `gpt-6.1-sol` |
| Application status | `needs_review` (three model-declared uncertain spans) |
| Elapsed | 47.467846 seconds |
| Input tokens | 19,316 |
| Output tokens | 1,754 |
| Reasoning tokens | 1,542 (already included in output total) |
| Cached input / cache-write tokens | 0 / 0 |
| Returned service tier | `default` |
| JSON, span indices and Unicode checks | Passed, no Unicode issues |
| Conservative configured-rate estimate | USD 0.103574 |

Run: `outputs/20261030T185807Z-806667a839b0/`.
Result: `results/openai-p0017-l006-2dcc97e9dc05.json` in that run.

Candidate (not verified Ground Truth):

```text
𑈁𑈜𑈺𑈀𑈴𑈙𑈺𑈤𑈭𑈜𑈰𑈺𑈙𑈰𑈌𑈺𑈌𑈺𑈜𑈲𑈙𑈬𑈺 ૨
```

| Raw code-point span (zero-based, end exclusive) | Candidate | Model alternative |
|---|---|---|
| [8, 9) | U+1122D, vowel sign I | U+1122E, vowel sign II |
| [14, 15) | U+1120C, GHA | U+11210, JA |
| [16, 17) | U+1120C, GHA | U+11210, JA |

Unlike the DeepSeek result, this candidate includes Khojki base letters and the
visible trailing Gujarati digit ૨. That makes it a plausible candidate to review,
not proof that the character sequence is correct. All three uncertain spans and
the full line must be checked manually before CER.

The ledger uses conservative long-context rates (USD 4/15 per million tokens).
For comparison, applying the checked Standard short-context USD 2/10 rates to
the returned usage gives `(19316*2 + 1754*10)/1e6 = USD 0.056172`. This is also an
estimate, not a verified invoice. Reasoning tokens must not be added again.

## Current budget

- DeepSeek baseline conservative estimate: USD 0.0021081.
- Additional DeepSeek D1/D1b/D2 estimates: USD 0.0010311 total.
- OpenAI first-attempt unresolved reservation: USD 3.74944 (401, no usage returned).
- OpenAI retry conservative usage estimate: USD 0.103574.
- Known usage-based conservative estimates total: USD 0.1067132.
- Total local accounted/held amount including the old unresolved entry: USD 3.8561532.
- Remaining local ledger allowance: USD 11.1438468.
- Do not present the OpenAI reservation as a confirmed charge or automatically
  release it without reconciliation against provider evidence.

## Follow-up decision

The latest configured credential was accepted by the official OpenAI endpoint;
the previous authentication blocker is resolved for this request. Preserve the
old 401 record and unresolved ledger entry until provider evidence supports
reconciliation. No further credential edits are currently requested.

DeepSeek's additional diagnostic outcomes and the user's decision are recorded in
`reports/t08-deepseek-diagnosis.md`. It is no longer an active dependency; do not
make more requests. D3 is cancelled, not a successful experiment.

The active single-model configuration is `configs/openai.yaml`, with explicit
`--provider openai`. Preserve original model candidates, organize uncertainty for
human review. The user's reply "接受" grants batch approval for the frozen ten
rows only. Reuse the first-row cache when inputs/parameters match; the other nine
rows are roughly USD 0.93 at the prior conservative per-row usage estimate, not
a guaranteed quote. Reuse the existing USD 15 ledger and historical holds.
No additional provider, diagnostic retry or enlarged sample is authorized.
Only human-verified transcriptions can serve as scan Ground Truth; no valid
machine-only accuracy or CER is established by dropping the second provider.

Ground Truth remains pending and no CER has been computed. All selected source
crops and the original failed candidate are preserved.

## Offline preparation checks

146 tests pass, including seven isolated diagnostic tests, Standard/cache-policy serialization, billing
assumption checks and redacted/masked-key diagnostics. `pip check` reports no broken
requirements. Credentials were loaded from `.env` using uv and only presence was
reported. No key values or authentication headers are included in this report.
