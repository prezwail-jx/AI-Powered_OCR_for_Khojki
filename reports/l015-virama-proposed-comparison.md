# l015: Proposed Virama Deletion — Not Yet Confirmed

**Subsequent decision:** the user explicitly accepted option B and restored the
original v1 selection. T11 is now frozen as `ground-truth-v1`; see
[t11-ground-truth.md](t11-ground-truth.md). The comparison below and its HTML
retain their original pre-confirmation labels for provenance.

[Open the side-by-side visual comparison](../outputs/20261030T221931Z-f5afa6843c01/index.html).
The offline HTML embeds Khojki/Gujarati fonts and shows both native scan crops,
the two textual options and the complete original line.

## The proposed edit

| | Fifth word group | Codepoints |
|---|---|---|
| A — original machine prediction | 𑈙𑈡𑈵 | U+11219 TA + U+11221 BA + U+11235 VIRAMA |
| B — proposed deletion, unconfirmed | 𑈙𑈡 | U+11219 TA + U+11221 BA |

Only delete raw codepoint `[21,22)`, U+11235. This is not an ASCII slash deletion.
All other characters, separators and Gujarati number ૧૦ remain unchanged.

### A: Original complete prediction

> 𑈞𑈴𑈪𑈮𑈴𑈺𑈙𑈡𑈺𑈞𑈬𑈤𑈺𑈞𑈴𑈪𑈮𑈴𑈺𑈙𑈡𑈵𑈺𑈐𑈬𑈙𑈬𑈺 ૧૦

### B: Complete proposed text — NOT confirmed Ground Truth

> 𑈞𑈴𑈪𑈮𑈴𑈺𑈙𑈡𑈺𑈞𑈬𑈤𑈺𑈞𑈴𑈪𑈮𑈴𑈺𑈙𑈡𑈺𑈐𑈬𑈙𑈬𑈺 ૧૦

## Scan comparison

Both crops below use native pixels, without resampling or warping; coordinates
are relative to `p0017-l015-e38c91e25be6.png`, with exclusive right/bottom bounds.
The lower area is retained so a possible mark is not removed by tight cropping.

| Reference: second word group | Disputed: fifth word group |
|---|---|
| ![Second group](../outputs/20261030T221931Z-f5afa6843c01/reference-word.png) | ![Fifth group](../outputs/20261030T221931Z-f5afa6843c01/disputed-word.png) |
| Box `[324,20,541,185)`, 217 × 165 | Box `[1141,20,1358,185)`, 217 × 165 |
| Machine text: 𑈙𑈡 | Machine text: 𑈙𑈡𑈵 |

Inspection question: is the detached lower-right ink in the fifth group part of
the BA letter's broken terminal stroke, or an independent mark? The five-to-one
model consistency is supporting evidence, not a substitute for this visual
decision. Equal crop width does not mean identical pixels.

## State

This is a proposed-edit comparison only. No source prediction, truth record,
selection version or budget entry was changed. The generation checks verified
their hashes stayed unchanged. No API call was made.

The active selection remains v2 with line18. Creating this comparison neither
restores the original v1 set nor freezes either version's Ground Truth.
