# Six-file setup test — 2026-10-22

## Observed results

All six supplied PDFs passed the complete local browser-workflow wrapper: metadata copy preparation, ZIP checksum matching, conversion, structural/appearance checks, and result packaging. The original attachments were not overwritten. Independent `pypdf` parsing and Poppler rendering with annotations hidden succeeded for every output page. A contact-sheet inspection showed the tables, product pictures, and red callouts present across the 24 pages.

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

The actual six-PDF cloud conversion is pending completion of the input Release transfer. This section will be updated with the observed Actions result and result Release after that run completes. Local conversion success and hosted synthetic-test success do not by themselves establish six-file cloud conversion success.

## Production status

Physical Android/iPhone/Windows viewer review has not been attested. These six parts documents are a setup pilot, below the minimum 10 distinct representative passing PDFs needed for production approval. Installation documents must also be included in that broader pilot. No full production batch or website publication is authorized by this test result.
