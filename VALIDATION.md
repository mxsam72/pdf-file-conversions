# Validation and pilot review

## Automated decisions

PASS requires every configured structural, size, source-preservation, and appearance check to succeed. A PDF that cannot meet the hard size limit within the quality limits goes to REVIEW. The converter does not damage detail simply to reach a byte target.

Supported annotation appearances are baked into PDF page content. Checks specifically examine the pixels occupied by original annotations so a missing small arrow cannot be hidden by a good page-wide average. Form widgets remain interactive. Pixel rendering is used for evidence and comparisons, never as the construction method for final pages.

Text/position checks allow annotation text added by baking while requiring original characters to remain. The final extracted text must match the baked baseline. Link rectangles/destinations, widgets, page boxes/rotation, fonts, vectors, and image placements are checked. Original and output SHA-256 values are recorded. Original-photo decoded content must survive the bake before the separate photograph compression stage.

Default visual limits are recorded in `settings.json`: bake comparison is stricter than photo compression; final page comparison requires mean absolute pixel error at most 8 and block SSIM at least 0.94. These numeric checks and the photo/diagram heuristic are useful safeguards, not a substitute for human review.

Each metadata preparation copy must preserve structure, exact rendered pixels at 144 DPI, image content identities, and original source hash. A separate interpreter then reopens the written file and checks page text hashes, image counts, annotation counts, and repair status.

## Physical viewer review before production

Inspect every pilot PASS PDF, including arrows/numbers, tiny parts, small diagram labels, text selection, page order, and links. Check representative parts **and** installation documents in:

- Android Chrome and an Android native/Google/Samsung PDF viewer.
- iPhone Safari/PDF viewer.
- Windows Chrome and Adobe Acrobat on Windows.

The browser workflow always records `device_review_confirmed: false`. Software running in a cloud runner cannot truthfully attest to these physical checks. No such checks have been assumed.

The setup's six parts PDFs are fewer than the minimum 10 distinct passing documents and do not contain installation examples. Their successful conversion cannot unlock the production batch. The engine requires the same tested code/settings/dependency fingerprint, intact pilot report/output hashes, a sufficient distinct sample, and an operator approval record. Changing code/settings/dependencies invalidates approval.

## Tests and setup evidence

The repository's synthetic suite covers photos/callouts/text/links/vectors, forms/rotation/shared images, small PDFs, size limits, annotations requiring review, encrypted/corrupt inputs, source preservation, pilot gating, report generation, safe extraction, manifest checks, output scope, and metadata preservation. Fixtures are generated in temporary directories; no real test PDF is committed to git.

Actual six-file setup results are recorded separately in the result Release and `SETUP_TEST.md` once the run is completed. Only observed results should be recorded there. GitHub Actions results must be distinguished from local tests; an Actions run that fails or does not start is not a successful cloud test.

## Interpreting outcomes

The HTML/CSV/JSON report is authoritative for individual documents. A run with REVIEW files still publishes its available report and candidates, then exits with a nonzero status so Actions does not present it as a clean success. An input download, metadata preservation, or technical failure can stop conversion before a result Release exists. Inspect the failing step's log, correct the cause, and use a new run or input Release; do not treat missing outputs as PASS.
