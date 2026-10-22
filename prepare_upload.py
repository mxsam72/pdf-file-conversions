#!/usr/bin/env python3
"""Prepare metadata-minimized upload COPIES; source files are never saved over.

This helper runs where Python is available. Browser-only users may run the
GitHub workflow directly; that workflow also removes this metadata in its
temporary working copies before conversion.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
import uuid

import numpy as np
import pymupdf as fitz

import converter as c


def prepare_copy(source, destination):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("A metadata-cleaned copy must have a separate destination")
    source_hash = c.sha256_file(source)
    pending = destination.with_name(destination.name + "." + uuid.uuid4().hex + ".writing")
    with fitz.open(source) as doc:
        if doc.needs_pass or not doc.is_pdf or doc.is_repaired:
            raise ValueError("Encrypted, non-PDF, or repaired input needs manual review")
        if doc.get_sigflags() > 0 or doc.embfile_count():
            raise ValueError("Signature fields or embedded attachments require manual review")
        original = [c.snapshot_page(page) for page in doc]
        original_images = c.image_inventory(doc)
        doc.set_metadata({})
        doc.del_xml_metadata()
        removed_author_labels = 0
        for page in doc:
            for annot in page.annots() or []:
                if annot.info.get("title"):
                    removed_author_labels += 1
                # Change dictionary metadata only. Do NOT call annot.update(),
                # which could regenerate its existing appearance stream.
                for key in ("T", "Subj", "CreationDate", "M"):
                    doc.xref_set_key(annot.xref, key, "null")
        destination.parent.mkdir(parents=True, exist_ok=True)
        doc.save(pending, garbage=4, deflate=True, clean=False)
    page_checks = []
    saved_hash = c.sha256_file(pending)
    with fitz.open(pending) as clean, fitz.open(source) as before_doc:
        if len(clean) != len(original):
            raise ValueError("Metadata preparation changed page count")
        for number, page in enumerate(clean):
            before, after = original[number], c.snapshot_page(page)
            passed = (
                c.signature(before["dimensions"]) == c.signature(after["dimensions"])
                and before["text"] == after["text"]
                and c.characters_preserved(before["chars"], after["chars"])
                and len(before["chars"]) == len(after["chars"])
                and before["fonts"] == after["fonts"]
                and before["drawings"] == after["drawings"]
                and before["image_placements"] == after["image_placements"]
                and Counter(c.signature(link) for link in before["links"]) ==
                    Counter(c.signature(link) for link in after["links"])
                and c.signature(before["widgets"]) == c.signature(after["widgets"])
                and [(a["type"], a["rect"], a["flags"]) for a in before["annotations"]] ==
                    [(a["type"], a["rect"], a["flags"]) for a in after["annotations"]]
                and all(not a["info"].get(key) for a in after["annotations"]
                        for key in ("title", "subject", "creationDate", "modDate"))
            )
            old_image, new_image = c.render(before_doc[number], 144), c.render(page, 144)
            difference = np.abs(np.asarray(old_image, dtype=np.int16) - np.asarray(new_image, dtype=np.int16))
            pixels_equal = bool((difference == 0).all())
            page_checks.append({"page": number + 1, "structure_pass": bool(passed),
                                "render_pixels_identical": pixels_equal})
            if not passed or not pixels_equal:
                raise ValueError(f"Metadata preparation changed visible content on page {number+1}")
        if c.image_content_identities(original_images) != c.image_content_identities(c.image_inventory(clean)):
            raise ValueError("Metadata preparation changed image content")
        if any(clean.metadata.get(key) for key in
               ("title", "author", "subject", "keywords", "creator", "producer", "creationDate", "modDate")):
            raise ValueError("Document metadata was not cleared")
        if clean.get_xml_metadata():
            raise ValueError("XML metadata was not cleared")
    # A fresh interpreter independently reopens the actual bytes on disk. This
    # catches serialization/reopen failures that an in-process cache may mask.
    probe = subprocess.run([sys.executable, "-c", """
import hashlib,json,sys,pymupdf
with pymupdf.open(sys.argv[1]) as doc:
 print(json.dumps({'repaired':doc.is_repaired,'pages':[
  {'text_sha256':hashlib.sha256(p.get_text().encode()).hexdigest(),
   'images':len(p.get_image_info()),'annotations':sum(1 for _ in p.annots() or [])}
  for p in doc]}))
""", str(pending)], check=True, capture_output=True, text=True)
    reopened = json.loads(probe.stdout)
    expected = [{"text_sha256": hashlib.sha256(p["text"].encode()).hexdigest(),
                 "images": sum(p["image_placements"].values()),
                 "annotations": len(p["annotations"])} for p in original]
    if reopened["repaired"] or reopened["pages"] != expected:
        raise ValueError("Metadata copy failed independent reopen validation")
    if c.sha256_file(pending) != saved_hash:
        raise ValueError("Metadata copy changed after validation")
    if c.sha256_file(source) != source_hash:
        raise ValueError("Source changed during preparation")
    os.replace(pending, destination)
    return {"file": destination.name, "prepared_bytes": destination.stat().st_size,
            "prepared_sha256": c.sha256_file(destination), "pages": len(original),
            "annotations": sum(len(p["annotations"]) for p in original),
            "author_labels_removed": removed_author_labels,
            "source_unchanged": True, "page_checks": page_checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = prepare_copy(args.source, args.destination)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
