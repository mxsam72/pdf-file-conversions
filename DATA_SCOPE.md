# Public data and file scope

This repository is public. Publish only PDF documents that are approved for public distribution.

## Intended uploads

- Generic converter source, settings, synthetic tests, workflow, license, and operating documentation.
- The explicitly selected test PDFs, as metadata-minimized copies inside the input Release ZIP.
- A manifest containing the selected filenames, byte counts, SHA-256 checksums, page/annotation counts, and preservation check results.
- Converted/review PDFs, visible comparison pictures, validation reports, software versions, and workflow information in result Releases.

The original attachments are kept unchanged. Initial public copies remove conventional document title/author/subject/keywords/creator/producer/date metadata, XMP metadata, and annotation author/subject/date labels. Visible PDF branding, product names, callout numbers, hyperlinks, and content remain part of the approved documents. Product filenames are preserved, including spaces.

## Boundaries

Input ZIPs accept only PDFs and an optional `manifest.json`. The extractor rejects traversal paths, absolute paths, backslashes, symlinks, encryption, duplicate/case-colliding names, unrelated files, and excessive size/counts. Release inputs must come from this same repository. The optional manifest, if present, must match the exact PDF set and its checksums.

The result ZIP includes only `PILOT PDFs`, `WEBSITE PDFs`, `REVIEW`, and `REPORTS`, plus two generic starting files. It does not package the source working tree, downloaded input ZIP, `ORIGINALS`, credentials, or unrelated PC folders. A REVIEW PDF can be an unconverted copy of a selected input; its accompanying label explains this. It is still public and must not be treated as website-ready.

Public evidence omits literal extracted document text, annotation author/comment dictionaries, actual link destination strings, and form values. Those elements may still be visible or embedded in the PDFs themselves. Comparison pictures intentionally show approved visible document content. Logs show selected filenames, sizes, status, and technical errors.

The repository does not connect to company drives, read arbitrary folders on the operator's PC, upload browsing history, or publish to a video service. The only external services used by the committed workflow are GitHub for code/files/jobs and PyPI for the pinned conversion packages.

## Storage and retention

PDFs and ZIPs are excluded from git to keep large documents out of source history. They are stored as Release assets. Release downloads remain public until explicitly removed. GitHub also retains workflow logs according to repository/account settings. The temporary hosted runner and its working copies are disposed of by GitHub after the job. Keep your own unchanged master PDFs outside this repository.

Split transfer parts, when used, contain only the bytes of the same approved input ZIP. Their descriptor contains generic part filenames, byte counts, and SHA-256 checksums. The runner verifies each part and the reassembled archive before opening it. The split format adds no other source data.

Future uploads should be checked for conventional metadata **before** publishing the input Release if that metadata must never appear publicly. The workflow's own metadata cleanup occurs after the public input upload and cannot retroactively make an original upload private.
