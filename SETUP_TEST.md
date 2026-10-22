# Six-file setup test — 2026-10-22

## Observed results

All six supplied PDFs passed locally and in the complete GitHub workflow: metadata copy preparation, ZIP checksum matching, conversion, structural/appearance checks, result packaging, and Release publication. The original attachments were not overwritten. Independent local `pypdf` parsing and Poppler rendering with annotations hidden succeeded for every output page. A contact-sheet inspection showed the tables, product pictures, and red callouts present across the 24 pages.

| PDF filename | Output bytes | Pages | Ordinary annotations flattened | Automated result |
|---|---:|---:|---:|---|
| `NQD-BCFX72_PARTS.pdf` | 561,248 | 4 | 42 | PASS |
| `NQD-ERDS-48_PARTS.pdf` | 544,852 | 4 | 46 | PASS |
| `NQD-ERDS-5460_PARTS.pdf` | 578,357 | 4 | 54 | PASS |
| `NQD-FPLUS-72_PARTS.pdf` | 553,887 | 4 | 44 | PASS |
| `NQD-FPLUS-72LH_PARTS.pdf` | 566,800 | 4 | 44 | PASS |
| `NQD-WLV36-60_PARTS .pdf` | 558,528 | 4 | 42 | PASS |

Total: **24 pages**, **272 annotations flattened**, **3,363,672 output bytes**, **0 REVIEW files**. All outputs are below the preferred 900,000-byte target. The space before `.pdf` in the last filename is intentional and preserved.

The prepared input ZIP contains exactly the six metadata-minimized PDFs and their manifest. It is **459,852,903 bytes**. Its public upload copies preserve original decoded photo content and exact page renders at 144 DPI; photo compression happens later in conversion. The metadata helper removed 272 annotation author labels plus conventional document metadata. Removed label values are not repeated in public reports.

The 18 embedded photos in these six upload copies were also inspected; no EXIF fields or XMP image metadata were found.

## GitHub verification

The 22 synthetic functional/boundary tests passed in GitHub Actions on the committed workflow: [successful test run](https://github.com/mxsam72/pdf-file-conversions/actions/runs/39837773583). This verifies the hosted runner, Python/dependency setup, source checkout, converter fixtures, and upload boundaries.

The actual six-PDF cloud conversion and publication succeeded in [Actions run 39840595561](https://github.com/mxsam72/pdf-file-conversions/actions/runs/39840595561), using commit `46ae3c90b84422e33f0f3bb43db18ef90855b543`. Both the 22-test job and the real-document pilot job succeeded. The output byte counts match the table above.

[Download the verified result Release](https://github.com/mxsam72/pdf-file-conversions/releases/tag/results-39840595561-1). Its `pdf-conversion-results.zip` is **6,848,230 bytes**, including six PDFs and their reports/comparison pictures. SHA-256: `e5d422d7fb7ac7f86251900eda41d33166a12d3669e4686217f3c51c9710ff22`.

The public ZIP and checksum file were downloaded after publication and independently verified. ZIP integrity, all six output hashes, PDF page counts, absence of ordinary annotations, six PASS report rows, and the package's allowed folder scope were checked. The downloaded package contains no `ORIGINALS` folder or source working tree. Device review is explicitly recorded as false.

## Production status

Physical Android/iPhone/Windows viewer review has not been attested. These six parts documents are a setup pilot, below the minimum 10 distinct representative passing PDFs needed for production approval. Installation documents must also be included in that broader pilot. No full production batch or website publication is authorized by this test result.
