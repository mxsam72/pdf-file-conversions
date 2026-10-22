# Software and licensing

The browser workflow uses Python 3.12 on GitHub's hosted Ubuntu 24.04 runner. The three runtime libraries are pinned in `requirements.txt`:

| Package | Version | Role | License family |
|---|---|---|---|
| PyMuPDF | 1.26.6 | PDF operations, rendering and analysis | AGPL-3.0 or a separately obtained commercial license |
| Pillow | 12.3.0 | Photo processing and comparison pictures | MIT-CMU |
| NumPy | 2.3.5 | Numerical/pixel comparison | BSD-3-Clause |

The source project uses AGPL-3.0 in alignment with the open-source PyMuPDF option. See the complete `LICENSE` and the packages' own notices. This license applies to the converter code; uploading or processing a PDF does not change that PDF's ownership or license.

GitHub's official `actions/checkout` and `actions/setup-python` are pinned to full commit hashes in the workflow, with their release versions in comments. The workflow invokes pip against the standard package index with binary wheels only. The hosted runner includes operating-system tools supplied by GitHub; there is no OS package-install step in this workflow.

Relevant primary documentation:

- [GitHub Actions Python workflows](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python)
- [GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)
- [PyMuPDF licensing](https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright)
- [Pillow license](https://pillow.readthedocs.io/en/stable/about.html#license)
- [NumPy license](https://numpy.org/doc/stable/license.html)
