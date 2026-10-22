# PDF File Conversions

Convert a small set of large PDFs in GitHub Actions, then download the PDFs and a validation report. The browser workflow installs no Python, command line tools, or converter software on the operator's Windows PC.

**Initial six-file test:** [download the converted PDFs and report](https://github.com/mxsam72/pdf-file-conversions/releases/tag/results-39840595561-1) · [successful GitHub run](https://github.com/mxsam72/pdf-file-conversions/actions/runs/39840595561) · [recorded test details](SETUP_TEST.md). All six passed; physical device review remains pending.

The converter makes arrows and other supported annotations ordinary PDF page content. It reduces oversized photographs while preserving selectable text, vector drawings, page geometry, hyperlinks, and interactive form fields. It never renders entire pages into replacement images and never overwrites uploaded masters.

## Run from a browser

1. Prepare a ZIP containing only the PDF files you intend to publish. Preserve their original filenames. An optional `manifest.json` may contain checksums. Keep each ZIP below 2,000,000,000 bytes. Do not include unrelated documents or folders.
2. Open this repository's **Releases → Draft a new release**. Create a tag such as `inputs-test-001`, attach the ZIP as **`test-inputs.zip`**, and publish the Release.
3. Open **Actions → Convert PDFs → Run workflow**, use the `main` branch, supply the input Release tag and exact ZIP asset name, and press **Run workflow**. For the initial split upload, use `inputs-test-001` and `test-inputs.json`.
4. When the job finishes, open the new **PDF pilot results** Release. Download `pdf-conversion-results.zip` and `SHA256SUMS.txt`. Extract the ZIP using Windows File Explorer.
5. Open `REPORTS / run folder / OPEN REPORT.html`. Use the comparison pictures and inspect the actual files under `PILOT PDFs`. Keep files under `REVIEW` out of the website.

The initial setup test uses six supplied parts PDFs. This demonstrates the GitHub route. It does **not** approve a full production batch. The browser workflow deliberately runs a pilot of at most 15 PDFs; it does not automatically process all 250 files. A representative pilot needs at least 10 distinct passing PDFs, including installation documents, followed by the physical viewer checks in [VALIDATION.md](VALIDATION.md). The engine retains its bulk approval gate for the later production phase.

Input Releases and result Releases are public and remain available until removed. Uploading or publishing files does not start conversion; pressing **Run workflow** starts it. A code push runs the synthetic tests only. No website is updated by this project.

For the initial large-file transfer, the exact same input ZIP may be split into smaller parts. In that case the Release contains `test-inputs.json` plus numbered `test-inputs.zip.part-*` assets. The workflow automatically finds this descriptor when `test-inputs.zip` is absent, downloads only same-repository assets, verifies each part, rejoins the unchanged ZIP in the descriptor's order, and verifies its full checksum before extraction. Normal browser uploads can continue to use a single ZIP.

## What runs, where, and why

| Component | Where it runs | Purpose |
|---|---|---|
| Existing web browser | Operator's PC | Upload a ZIP, start/monitor Actions, download results |
| Windows File Explorer / existing PDF viewer | Operator's PC | Extract the download and inspect PDFs |
| GitHub-hosted Ubuntu 24.04 runner | GitHub | Temporary computer that runs the job |
| Git and the Node.js runtime used by official Actions | GitHub runner | Check out source files and run GitHub's setup actions |
| Python 3.12, selected by `actions/setup-python` | GitHub runner | Execute the converter and checks |
| pip | GitHub runner | Download the three pinned Python packages from PyPI |
| PyMuPDF 1.26.6, including its native MuPDF engine | GitHub runner | Read/write PDFs, flatten supported annotations, inspect PDF structure, render comparisons |
| Pillow 12.3.0 | GitHub runner | Resize/re-encode eligible photos; create comparison pictures |
| NumPy 2.3.5 | GitHub runner | Compare pixels and measure visual changes |
| GitHub's temporary `GITHUB_TOKEN` | GitHub runner | Read this repository's inputs and create its result Release |

The workflow uses GitHub's standard hosted runner. It installs no self-hosted runner or background service on the PC. No personal access token or custom secret is required. Checkout does not save GitHub credentials in the working copy. The conversion job's token has repository contents write permission so it can publish the result download; the test job has read permission.

Only the GitHub Actions runner installs the Python libraries. The job does not request a paid runner, change billing settings, or install Adobe Acrobat, Ghostscript, a printer driver, or a Windows executable. Actions availability and account limits are still controlled by GitHub.

## Conversion and evidence

- Preferred size: no more than **900,000 bytes** per PDF. Hard pass limit: **strictly below 1,000,000 bytes**.
- Supported annotations are baked once; form widgets stay interactive. Unsupported/redaction/signature/attachment cases require review.
- Photo passes restart from the same baked baseline. Photos are never repeatedly compressed from the previous lossy pass.
- Text characters and positions, fonts, vector paths, image placement, links, widgets, dimensions, page count, reopening, source hashes, annotation pixels, and appearance are checked.
- Each result has CSV/HTML/JSON evidence. Public JSON uses text hashes/counts instead of an extra copy of extracted document text, hashes link destinations, and excludes annotation author/comment dictionaries and form values.
- The metadata helper clears document Info fields, XMP metadata, and annotation author/subject/date fields in a separate working copy. It verifies structure and exact rendered pixels and performs an independent fresh-process reopen check. This is conventional metadata cleanup, not a guarantee that every possible hidden PDF object has been removed.

See [DATA_SCOPE.md](DATA_SCOPE.md) for what is public, [VALIDATION.md](VALIDATION.md) for limits and review, and [THIRD_PARTY.md](THIRD_PARTY.md) for dependencies and licenses.

## Source layout

| File | Responsibility |
|---|---|
| `.github/workflows/convert-pdfs.yml` | Tests, browser/manual entry point, hosted job and permissions |
| `cloud_run.py` | Same-repository input download, ZIP checks, pilot, allowlisted result package, Release upload |
| `prepare_upload.py` | Metadata-minimized copies with preservation checks |
| `converter.py` | PDF conversion, validation, reports, production approval gate |
| `settings.json` | Size, quality, resolution, and pilot limits |
| `test_converter.py`, `test_cloud.py` | Synthetic functional and boundary tests; no real customer documents |

## Optional developer use

The commands below are for a development machine with Python already available. Browser-only operators do not need to run them on a company PC.

```sh
python -m pip install --only-binary=:all: -r requirements.txt
python -m unittest discover -p 'test_*.py' -v
python cloud_run.py --archive /path/to/test-inputs.zip --work /path/to/new-work-folder
```

Source code is distributed under AGPL-3.0; see [LICENSE](LICENSE). Uploaded PDFs retain their existing ownership and permissions.
