# Khojki OCR: Technical Retro

## Result and stage breakdown
Ten selected printed rows: CER 1/253 = 0.3953%; macro CER 0.3333%; 9/10 exact. The sole extra U+11235 is attributed to character recognition (1); main-set detection and confirmed Unicode-mapping errors are 0. This is model-assisted user review, not blind expert ground truth: nine candidates were accepted unchanged. Annotation time is unknown. Two page-9 detection failures are qualitative, not extra CER events; no complete manual boxes exist.

## Experiments that failed
Historical DeepSeek first-row configurations yielded CER 0.92, 1.00 (empty output), and 1.04; a synthetic 11-codepoint control also yielded 1.00. Settings differ, so no aggregate model comparison is valid. D3 was cancelled. A temporary line18 replacement was excluded when the original ten-row set was restored. Page-1 handwriting clipping escaped detector flags; page-5 overlap was flagged. Neither manuscript was transcribed or scored.

## Encoding decisions
Use atomic Khojki vowel letters/signs, U+1123A word separators and Gujarati digits U+0AE6-U+0AEF. Unicode 17.0.0 checks assigned characters, scripts and atomic forms; HarfBuzz/FreeType charts use Noto Serif Khojki because the supplied Sans lacks U+11241. NFC is applied to both strings; spaces, marks and digits count as codepoints. Empty predictions are deletions; CER may exceed 1. Valid encoding does not imply correct OCR.

## Bottleneck and next dataset
The biggest accuracy/evaluation gain would be independent, double-reviewed real scan lines, especially small marks and historical fonts, rather than another unverified model vote. Start with 200 diverse printed lines to audit errors, expand toward 1,000 for a local adaptation experiment, and separately collect 200 handwriting lines across hands. These are planning estimates, not measured learning-curve thresholds; use a held-out set and annotation disagreement to revise them.

## Scale and cost
Ten original OpenAI requests sum to 442.36 s and estimated USD 1.036664: 44.24 s and USD 0.1036664 per line. Assuming 15 similar rows/page, serial inference is about 11.1 min and USD 1.55/page; 47 such pages would be 8.66 h and USD 73.08, not a quote or the actual mixed collection cost. Add segmentation/review time. All usage estimates total USD 1.1421432, plus USD 3.74944 unknown reserved, not confirmed billed. Handwriting needs separate measurement; concurrency helps throughput but not recognition reliability.

## Where AI was wrong
OpenAI inserted U+11235 on line15 and flagged the tiny lower mark as uncertain. The user checked the scan/chart, accepted the version without it, and froze that reference; codepoint alignment exposed exactly one insertion. Text offsets are not pixel boxes. Preserve original responses, uncertainty and manual decisions: an AI explanation or Unicode whitelist alone cannot certify the answer.
