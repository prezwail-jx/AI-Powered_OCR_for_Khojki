# Data, licenses and distribution

The assignment is *AI-Powered OCR for Khojki*. Its sample document is
`sample_khojki_script_vatiations.pdf` (47 pages), SHA-256
`99f373777e13ad01ccc7ff1ae067cb80a3de2bc22d96df6c7ab0a558f8d11f23`.
The assignment explicitly says **"Please use the pages for this exercise only."**

The user chose separate delivery: code/textual results can form the code package;
full PDFs are supplied privately by the reviewer, and scan crops, overlays and
derived image evidence remain in a **private exercise review** package. No public
redistribution authorization is claimed. Previously recorded approval to submit
the PDFs is not represented as an unrestricted redistribution license.

Source captions identify Harvard Houghton/Widener collections. Page 17 credits
Pir Imam Shah, *5 granth ne 100 ginan bhaj 2 jo*, Bombay, 1903; pages 1-6 identify
manuscripts (1890? on pages 1-3, 1865 on pages 4-6). These captions establish
provenance, not text ground truth or a new license grant. Some later image-only
pages have not had their source provenance resolved and are not in this benchmark.

## Bundled assets

- Unicode data and normalization: **17.0.0**, `unicodedata2==17.0.0`;
  `src/khojki_ocr/assets/unicode/Unicode-LICENSE.txt`.
- Noto Serif Khojki **v2.005** is the complete-coverage shaped reference font;
  `src/khojki_ocr/assets/fonts/SerifKhojki-OFL.txt`.
- Noto Sans Khojki is retained as the assignment's suggested font, but it lacks
  U+11241 in the bundled version. It was not silently treated as full coverage;
  `Khojki-OFL.txt` accompanies it.
- Noto Sans Gujarati renders Gujarati digits; `Gujarati-OFL.txt` accompanies it.
- HarfBuzz + FreeType shape reference glyphs; dotted circles are display aids,
  not emitted OCR characters. The chart is a synthetic reference, not scan truth.

Third-party Python/native dependencies retain their respective licenses. The
exact tested installation is recorded in `requirements-repro.txt`; this inventory
does not grant additional rights to their code. Project code licensing/publication
is a final-delivery decision for T15, not assumed from the presence of font licenses.

## Annotation

The user reviewed the printed crops against the chart and explicitly froze
`ground-truth-v1`. Nine model candidates were accepted; line15 lost one U+11235.
The method is `model_assisted_user_visual_review`, not blind independent expert
annotation. Annotation duration was not supplied and is stored as null.
