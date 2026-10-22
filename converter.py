#!/usr/bin/env python3
"""PDF File Conversions local PDF publisher. Masters are opened for reading only.

Page rendering is used for comparisons and previews, NEVER to build output PDFs.
See README.md and settings.json before changing the quality limits.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime
import csv
import fnmatch
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time
import traceback
from urllib.parse import quote
import uuid

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, __version__ as PIL_VERSION
import pymupdf as fitz

VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parent
DEPENDENCIES = {"PyMuPDF": "1.26.6", "Pillow": "12.3.0", "numpy": "2.3.5"}
CHECK_NAMES = ("page_count", "page_dimensions", "annotations", "text", "fonts",
               "vectors", "image_geometry", "bake_image_content", "links", "widgets", "integrity", "appearance",
               "original_unchanged", "size")
SUPPORTED_ANNOTATIONS = {"FreeText", "Line", "Square", "Circle", "Polygon",
                         "PolyLine", "Highlight", "Underline", "Squiggly",
                         "StrikeOut", "Stamp", "Caret", "Ink"}


class ReviewRequired(Exception):
    """An input needs a person's decision; it is never published automatically."""


def sha256_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".writing")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def dependencies():
    return {"PyMuPDF": fitz.VersionBind, "Pillow": PIL_VERSION, "numpy": np.__version__}


def validate_dependencies():
    if sys.version_info < (3, 11) or sys.version_info >= (3, 15):
        raise ValueError("Use 64-bit Python 3.11, 3.12, 3.13, or 3.14. Python 3.12 is recommended.")
    if sys.maxsize <= 2**32:
        raise ValueError("64-bit Python is required for large iPhone photo PDFs.")
    if dependencies() != DEPENDENCIES:
        raise ValueError("Dependency versions do not match this tested package. Install the pinned requirements.txt dependencies again.")


def load_settings(root):
    settings = json.loads((root / "settings.json").read_text(encoding="utf-8-sig"))
    if not (0 < settings["target_bytes"] < settings["maximum_bytes"]):
        raise ValueError("target_bytes must be positive and less than maximum_bytes.")
    if not 10 <= settings["pilot_limit"] <= 15:
        raise ValueError("pilot_limit must be between 10 and 15.")
    if not 10 <= settings["minimum_pilot_passes"] <= settings["pilot_limit"]:
        raise ValueError("minimum_pilot_passes must be between 10 and pilot_limit.")
    if not 96 <= settings["comparison_dpi"] <= 200:
        raise ValueError("comparison_dpi must be between 96 and 200.")
    for profile in ("parts", "installation"):
        rules = settings["profiles"][profile]
        if not 100 <= rules["minimum_ppi"] <= 400:
            raise ValueError("minimum_ppi must be between 100 and 400.")
        for stage in rules["passes"]:
            if not 900 <= stage["long_edge"] <= 4000 or not 45 <= stage["quality"] <= 95:
                raise ValueError("Each pass needs long_edge 900-4000 and quality 45-95.")
    for rule in settings["profile_overrides"]:
        if rule["profile"] not in settings["profiles"]:
            raise ValueError("Unknown profile in profile_overrides.")
    return settings


def fingerprint(root, settings):
    data = {"version": VERSION, "settings": settings, "dependencies": dependencies(),
            "engine_sha256": sha256_file(root / "converter.py")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode("utf-8")).hexdigest()


def profile_for(relative, settings, forced="auto"):
    if forced != "auto":
        return forced
    name = relative.as_posix().casefold()
    for rule in settings["profile_overrides"]:
        if fnmatch.fnmatchcase(name, rule["pattern"].casefold()):
            return rule["profile"]
    if "install" in name or "instruction" in name:
        return "installation"
    if "parts" in name:
        return "parts"
    # A name alone cannot prove an image is a photograph. Unmatched names get
    # the higher-detail installation profile; explicit overrides are easy to edit.
    return "installation"


def create_folders(root):
    for name in ("ORIGINALS", "PILOT PDFs", "WEBSITE PDFs", "REVIEW", "REPORTS"):
        path = root / name
        if path.exists() and path.resolve() != path.absolute():
            raise ValueError(f"Do not use a shortcut/junction/symbolic link for {name}.")
        path.mkdir(exist_ok=True)


@contextmanager
def exclusive_run(root):
    """An OS lock is automatically released after a crash; no stale-lock prompt."""
    path = root / ".converter.lock"
    with path.open("a+b") as lock:
        lock.seek(0, os.SEEK_END)
        if lock.tell() == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("Another converter is running in this folder. Let it finish first.") from exc
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def canonical(value):
    if isinstance(value, (fitz.Rect, fitz.Point, fitz.Quad, fitz.Matrix)):
        return canonical(list(value))
    if isinstance(value, dict):
        return {key: canonical(v) for key, v in value.items() if key not in ("xref", "id", "seqno")}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if isinstance(value, float):
        return round(value, 3)
    return value


def signature(value):
    return json.dumps(canonical(value), sort_keys=True, ensure_ascii=False)


def character_inventory(page):
    chars = []
    fonts = set()
    for span in page.get_texttrace():
        fonts.add(span["font"])
        for code, glyph, origin, bbox in span["chars"]:
            chars.append((code, float(origin[0]), float(origin[1])))
    return chars, fonts


def characters_preserved(before, after, tolerance=0.08):
    """Match characters AND locations, allowing annotation text to be added."""
    buckets = defaultdict(list)
    cell = 0.2
    for char, x, y in after:
        buckets[(char, math.floor(x / cell), math.floor(y / cell))].append((x, y))
    for char, x, y in before:
        cx, cy = math.floor(x / cell), math.floor(y / cell)
        found = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                points = buckets[(char, cx + dx, cy + dy)]
                for index, (px, py) in enumerate(points):
                    if abs(px - x) <= tolerance and abs(py - y) <= tolerance:
                        points.pop(index)
                        found = True
                        break
                if found:
                    break
            if found:
                break
        if not found:
            return False
    return True


def snapshot_page(page):
    chars, fonts = character_inventory(page)
    annotations = []
    for annot in page.annots() or []:
        annotations.append({"type": annot.type[1], "rect": list(annot.rect),
                            "flags": annot.flags, "info": dict(annot.info)})
    widgets = []
    for widget in page.widgets() or []:
        widgets.append({"name": widget.field_name, "type": widget.field_type_string,
                        "value": widget.field_value, "rect": list(widget.rect),
                        "flags": widget.field_flags,
                        "choices": widget.choice_values})
    return {"dimensions": {"rect": list(page.rect), "mediabox": list(page.mediabox),
                            "cropbox": list(page.cropbox), "rotation": page.rotation},
            "chars": chars, "fonts": fonts, "text": page.get_text("text"),
            "drawings": Counter(signature(drawing) for drawing in page.get_cdrawings()),
            "image_placements": Counter(signature({"bbox": info["bbox"], "transform": info["transform"]})
                                         for info in page.get_image_info()),
            "links": page.get_links(), "widgets": widgets, "annotations": annotations}


def image_inventory(doc):
    """Inventory displayed images, including every placement of shared images."""
    catalog = {}
    mask_xrefs = set()
    for page in doc:
        for record in page.get_images(full=True):
            if record[1]:
                mask_xrefs.add(record[1])
        for info in page.get_image_info(xrefs=True):
            xref = info["xref"]
            key = str(xref) if xref else f"inline-{page.number}-{info['number']}"
            if key not in catalog:
                catalog[key] = {"xref": xref, "first_page": page.number,
                    "width": info["width"], "height": info["height"],
                    "bits_per_component": info["bpc"], "pixel_digest": info["digest"].hex(),
                    "placements": []}
                if xref:
                    raw = doc.xref_stream_raw(xref)
                    catalog[key]["compressed_bytes"] = len(raw) if raw else 0
            a, b, c, d, e, f = info["transform"]
            width_pt, height_pt = math.hypot(a, b), math.hypot(c, d)
            catalog[key]["placements"].append({"page": page.number + 1,
                "bbox": list(info["bbox"]), "width_pt": width_pt, "height_pt": height_pt,
                "ppi_x": round(info["width"] * 72 / max(width_pt, .001), 2),
                "ppi_y": round(info["height"] * 72 / max(height_pt, .001), 2)})
    for record in catalog.values():
        xref = record["xref"]
        reason = ""
        if not xref:
            reason = "Inline image: preserved unchanged"
        elif xref in mask_xrefs:
            reason = "Transparency mask: preserved unchanged"
        elif record["bits_per_component"] != 8:
            reason = "Not an 8-bit photograph: preserved unchanged"
        else:
            for key in ("SMask", "Mask", "ImageMask", "SMaskInData", "Decode"):
                kind, value = doc.xref_get_key(xref, key)
                if kind != "null" and value not in ("false", "0"):
                    reason = f"Image uses {key}: preserved unchanged"
                    break
        record["preserve_reason"] = reason
    return list(catalog.values())


def image_content_identities(catalog):
    return Counter(signature({"digest": im["pixel_digest"], "width": im["width"], "height": im["height"],
                              "page": p["page"], "bbox": p["bbox"],
                              "width_pt": p["width_pt"], "height_pt": p["height_pt"]})
                   for im in catalog for p in im["placements"])


def preflight(doc, pages):
    reasons = []
    if doc.is_repaired:
        reasons.append("Source required PDF repair; inspect it manually")
    if doc.get_sigflags() > 0:
        reasons.append("Signature fields/signatures require a separate publishing decision")
    if doc.embfile_count():
        reasons.append("Embedded attachments require manual review")
    for key in ("Collection", "OCProperties"):
        if doc.xref_get_key(doc.pdf_catalog(), key)[0] != "null":
            reasons.append(f"PDF has {key}; its interactive/layered content needs review")
    for number, page in enumerate(pages, 1):
        for annot in page["annotations"]:
            if annot["type"] not in SUPPORTED_ANNOTATIONS:
                reasons.append(f"Page {number}: annotation type {annot['type']} needs manual review")
            if annot["flags"] & (1 | 2 | 32):
                reasons.append(f"Page {number}: hidden/invisible annotation needs manual review")
        if any(w["type"] == "Signature" for w in page["widgets"]):
            reasons.append(f"Page {number}: signature widget is preserved for manual review")
        raw_links = sum(1 for _, kind, _ in doc[number - 1].annot_xrefs() if kind == fitz.PDF_ANNOT_LINK)
        if raw_links != len(page["links"]):
            reasons.append(f"Page {number}: a link action cannot be fully inspected")
    if reasons:
        raise ReviewRequired("; ".join(dict.fromkeys(reasons)))


def restore_links(doc, source_pages):
    restored = 0
    for page, original in zip(doc, source_pages):
        existing = Counter(signature(link) for link in page.get_links())
        for link in original["links"]:
            key = signature(link)
            if existing[key]:
                existing[key] -= 1
                continue
            if link["kind"] not in (fitz.LINK_URI, fitz.LINK_GOTO, fitz.LINK_GOTOR, fitz.LINK_LAUNCH):
                raise ReviewRequired("A removed link type could not be safely restored")
            page.insert_link({k: v for k, v in link.items() if k not in ("xref", "id")})
            restored += 1
    return restored


def save_pdf(doc, path):
    # clean removes unused image resource entries left by replace_image's
    # temporary insertion. Without it, equivalent old/new image dictionaries
    # can keep two copies of every JPEG alive despite garbage collection.
    doc.save(str(path), garbage=4, deflate=True, deflate_fonts=True,
             clean=True, use_objstms=0, encryption=fitz.PDF_ENCRYPT_KEEP)


def render(page, dpi, annots=True):
    pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False, annots=annots)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


def reference_renders(doc, directory, dpi, pages):
    for number, page in enumerate(doc):
        image = render(page, dpi)
        image.save(directory / f"before-{number}.png")
        if pages[number]["annotations"] or pages[number]["widgets"]:
            no_annotations = render(page, dpi, annots=False)
            delta = np.abs(np.asarray(image).astype(np.int16) -
                           np.asarray(no_annotations).astype(np.int16)).max(axis=2)
            mask = Image.fromarray(np.uint8(delta > 24) * 255)
        else:
            mask = Image.new("L", image.size)
        mask.save(directory / f"annotation-mask-{number}.png")


def block_ssim(before, after):
    """Mean SSIM over 8x8 luminance blocks, with separate annotation checks."""
    a = np.asarray(before.convert("L"), dtype=np.float32)
    b = np.asarray(after.convert("L"), dtype=np.float32)
    height, width = (a.shape[0] // 8) * 8, (a.shape[1] // 8) * 8
    if not height or not width:
        return 1.0 if np.array_equal(a, b) else 0.0
    def blocks(array):
        return array[:height, :width].reshape(height // 8, 8, width // 8, 8).transpose(0, 2, 1, 3)
    aa, bb = blocks(a), blocks(b)
    ma, mb = aa.mean((2, 3)), bb.mean((2, 3))
    va, vb = aa.var((2, 3)), bb.var((2, 3))
    cov = ((aa - ma[..., None, None]) * (bb - mb[..., None, None])).mean((2, 3))
    ssim = ((2 * ma * mb + 6.5025) * (2 * cov + 58.5225) /
            ((ma**2 + mb**2 + 6.5025) * (va + vb + 58.5225)))
    return float(np.mean(ssim))


def visual_metrics(before, after, mask):
    if before.size != after.size:
        return {"dimensions_match": False, "pass": False}
    a = np.asarray(before, dtype=np.int16)
    b = np.asarray(after, dtype=np.int16)
    delta = np.abs(a - b)
    selected = np.asarray(mask, dtype=np.uint8) > 0
    retention = 1.0
    if selected.any():
        # Compare only pixels that the original annotations actually painted.
        # A one-pixel neighbourhood tolerates antialiasing, not a missing arrow.
        best = np.full(selected.shape, 255, dtype=np.int16)
        pad = np.pad(b, ((1, 1), (1, 1), (0, 0)), mode="edge")
        for dy in range(3):
            for dx in range(3):
                np.minimum(best, np.abs(a - pad[dy:dy+a.shape[0], dx:dx+a.shape[1]]).max(axis=2), out=best)
        retention = float((best[selected] <= 40).mean())
    return {"dimensions_match": True, "mean_absolute_error": round(float(delta.mean()), 6),
            "changed_fraction": round(float((delta.max(axis=2) > 16).mean()), 7),
            "block_ssim": round(block_ssim(before, after), 6),
            "annotation_pixels": int(selected.sum()),
            "annotation_pixel_retention": round(retention, 6)}


def compare_visuals(doc, reference_dir, settings, strict=False):
    metrics, passed = [], True
    for number, page in enumerate(doc):
        with Image.open(reference_dir / f"before-{number}.png") as original, \
             Image.open(reference_dir / f"annotation-mask-{number}.png") as mask:
            values = visual_metrics(original.convert("RGB"), render(page, settings["comparison_dpi"]), mask)
        if strict:
            good = (values.get("dimensions_match", False) and
                    values["mean_absolute_error"] <= 2.0 and
                    values["block_ssim"] >= .985 and
                    values["annotation_pixel_retention"] >= .98)
        else:
            good = (values.get("dimensions_match", False) and
                    values["mean_absolute_error"] <= settings["maximum_visual_mae"] and
                    values["block_ssim"] >= settings["minimum_block_ssim"] and
                    values["annotation_pixel_retention"] >= .98)
        values.update({"page": number + 1, "pass": bool(good)})
        metrics.append(values)
        passed = passed and bool(good)
    return passed, metrics


def verify_structure(doc, original, baked=None):
    checks = {key: True for key in ("page_count", "page_dimensions", "annotations", "text",
                                   "fonts", "vectors", "image_geometry", "links", "widgets", "integrity")}
    checks["page_count"] = len(doc) == len(original)
    checks["integrity"] = bool(doc.is_pdf and not doc.is_repaired and not doc.needs_pass)
    snapshots = [snapshot_page(page) for page in doc]
    if not checks["page_count"]:
        return checks, snapshots
    for index, (before, after) in enumerate(zip(original, snapshots)):
        checks["page_dimensions"] &= signature(before["dimensions"]) == signature(after["dimensions"])
        checks["annotations"] &= not after["annotations"]
        checks["text"] &= characters_preserved(before["chars"], after["chars"])
        checks["fonts"] &= before["fonts"].issubset(after["fonts"])
        checks["vectors"] &= not bool(before["drawings"] - after["drawings"])
        checks["image_geometry"] &= not bool(before["image_placements"] - after["image_placements"])
        checks["links"] &= (Counter(signature(v) for v in before["links"]) ==
                            Counter(signature(v) for v in after["links"]))
        checks["widgets"] &= signature(before["widgets"]) == signature(after["widgets"])
        if baked is not None:
            # After flattening, compression must preserve ALL extracted text and
            # drawings, including the newly permanent arrow/number graphics.
            checks["text"] &= (baked[index]["text"] == after["text"] and
                               characters_preserved(baked[index]["chars"], after["chars"]) and
                               len(baked[index]["chars"]) == len(after["chars"]))
            checks["fonts"] &= baked[index]["fonts"].issubset(after["fonts"])
            checks["vectors"] &= baked[index]["drawings"] == after["drawings"]
            checks["image_geometry"] &= baked[index]["image_placements"] == after["image_placements"]
    return {key: bool(value) for key, value in checks.items()}, snapshots


def photo_assessment(image):
    """Conservative heuristic: ambiguous/diagram-like raster images stay intact.

    It is not possible to prove from pixels that an image contains no small text.
    The pilot and previews remain required, and any image can be excluded.
    """
    small = image.copy()
    small.thumbnail((256, 256), Image.Resampling.LANCZOS)
    data = np.asarray(small.convert("RGB"), dtype=np.int16)
    spread = data.max(axis=2) - data.min(axis=2)
    white = (data.min(axis=2) > 235).mean()
    saturated = (spread > 25).mean()
    gray = (spread < 10).mean()
    quantized = np.asarray(small.convert("RGB"), dtype=np.uint8) // 16
    colors = len(np.unique(quantized.reshape(-1, 3), axis=0))
    entropy = float(small.convert("L").entropy())
    reason = ""
    if gray > .97:
        reason = "Grayscale/line-art-like image left unchanged"
    elif white > .65 and saturated < .08:
        reason = "Mostly white scan/diagram-like image left unchanged"
    elif colors < 96 or entropy < 4.2:
        reason = "Limited-color diagram/icon-like image left unchanged"
    return reason, {"gray_fraction": round(float(gray), 4), "white_fraction": round(float(white), 4),
                    "saturated_fraction": round(float(saturated), 4),
                    "quantized_colors": colors, "gray_entropy": round(entropy, 4)}


def compress_photos(doc, catalog, stage, profile_settings, excluded):
    changes = []
    for record in catalog:
        item = dict(record)
        xref = record["xref"]
        item["action"] = "preserved"
        item["reason"] = record["preserve_reason"]
        if not item["reason"] and (record["compressed_bytes"] < 120_000 or
                record["width"] * record["height"] < 400_000 or
                max(record["width"], record["height"]) < 900):
            item["reason"] = "Small/already compact image left unchanged"
        if excluded:
            item["reason"] = "File is excluded from photo recompression in settings.json"
        if not item["reason"]:
            pix = fitz.Pixmap(doc, xref)
            if pix.alpha or not pix.colorspace or pix.colorspace.n != 3:
                item["reason"] = "Non-RGB/transparency image left unchanged"
            else:
                if pix.colorspace.name != "DeviceRGB":
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
                reason, assessment = photo_assessment(image)
                item["assessment"] = assessment
                if reason:
                    item["reason"] = reason
                else:
                    width, height = image.size
                    scale = min(1.0, stage["long_edge"] / max(width, height))
                    min_ppi = profile_settings["minimum_ppi"]
                    # Every placement matters: a shared image may appear small
                    # on one page and full-size on another.
                    minimum_scale = max(max(p["width_pt"] * min_ppi / (72 * width),
                                            p["height_pt"] * min_ppi / (72 * height))
                                        for p in record["placements"])
                    scale = min(1.0, max(scale, minimum_scale))
                    # Ceil keeps rounding from taking an image below its PPI floor.
                    dimensions = (max(1, math.ceil(width * scale)), max(1, math.ceil(height * scale)))
                    if dimensions != image.size:
                        image = image.resize(dimensions, Image.Resampling.LANCZOS)
                    stream = io.BytesIO()
                    image.save(stream, format="JPEG", quality=stage["quality"],
                               optimize=True, progressive=False, subsampling=0)
                    compressed = stream.getvalue()
                    if len(compressed) >= record["compressed_bytes"] * .90:
                        item["reason"] = "Recompression would not save at least 10%; image left unchanged"
                    else:
                        doc[record["first_page"]].replace_image(xref, stream=compressed)
                        item.update({"action": "recompressed", "reason": "Photograph candidate",
                                     "new_width": dimensions[0], "new_height": dimensions[1],
                                     "new_bytes": len(compressed), "quality": stage["quality"]})
                image.close()
            del pix
        changes.append(item)
    return changes


def public_snapshot(page):
    # Reports expose validation evidence, not another copy of document text,
    # annotation authors, form values, or hyperlink destinations.
    return {"dimensions": page["dimensions"],
            "text_sha256": hashlib.sha256(page["text"].encode("utf-8")).hexdigest(),
            "text_characters": len(page["chars"]), "fonts": sorted(page["fonts"]),
            "vector_path_count": sum(page["drawings"].values()),
            "links": [{"kind": link["kind"], "rect": list(link["from"]),
                       "destination_sha256": hashlib.sha256(signature(link).encode("utf-8")).hexdigest()}
                      for link in page["links"]],
            "widget_count": len(page["widgets"]),
            "annotations": [{"type": annot["type"], "rect": annot["rect"], "flags": annot["flags"]}
                            for annot in page["annotations"]]}


def comparison_preview(before_path, after_page, destination, label):
    with Image.open(before_path) as source:
        before = source.convert("RGB")
    after = render(after_page, 110)
    before.thumbnail((650, 850), Image.Resampling.LANCZOS)
    after.thumbnail((650, 850), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (1340, max(before.height, after.height) + 82), "#e5e7eb")
    draw = ImageDraw.Draw(canvas)
    draw.text((18, 12), label, fill="#111111")
    draw.text((18, 38), "ORIGINAL (annotations visible)", fill="#111111")
    draw.text((688, 38), "WEBSITE COPY (baked annotations)", fill="#111111")
    canvas.paste(before, (18, 66))
    canvas.paste(after, (688, 66))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, format="JPEG", quality=88)


def process_file(source, relative, root, run_id, settings, mode, forced_profile="auto"):
    start = time.monotonic()
    file_id = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16]
    report_dir = root / "REPORTS" / run_id
    row = {"filename": relative.as_posix(), "profile": profile_for(relative, settings, forced_profile),
           "result": "REVIEW", "notes": [], "checks": {name: None for name in CHECK_NAMES},
           "original_bytes": source.stat().st_size, "website_bytes": None,
           "original_pages": None, "website_pages": None,
           "original_annotations": None, "website_annotations": None,
           "original_links": None, "website_links": None,
           "output": None, "previews": [], "compression_pass": "none",
           "details": f"details/{file_id}.json", "started": now()}
    detail = {"filename": row["filename"], "version": VERSION, "dependencies": dependencies(),
              "original": [], "baked": [], "final": [], "attempts": []}
    source_hash = sha256_file(source)
    row["source_sha256"] = source_hash
    with tempfile.TemporaryDirectory(prefix="pdf-conversion-") as temporary:
        temp = Path(temporary)
        baked_path = temp / "baked.pdf"
        selected = None
        original_pages, baked_pages, final_pages = [], [], []
        try:
            fitz.TOOLS.mupdf_warnings(reset=True)
            with fitz.open(source) as doc:
                if not doc.is_pdf or doc.needs_pass or doc.is_encrypted:
                    raise ReviewRequired("Encrypted/password-protected or non-PDF input; no conversion performed")
                if not len(doc):
                    raise ReviewRequired("PDF has no pages")
                original_pages = [snapshot_page(page) for page in doc]
                detail["original"] = [public_snapshot(page) for page in original_pages]
                row.update({"original_pages": len(doc),
                            "original_annotations": sum(len(p["annotations"]) for p in original_pages),
                            "original_links": sum(len(p["links"]) for p in original_pages)})
                preflight(doc, original_pages)
                detail["original_images"] = image_inventory(doc)
                reference_renders(doc, temp, settings["comparison_dpi"], original_pages)
                # This is the only flattening operation. Form fields stay interactive.
                doc.bake(annots=True, widgets=False)
                detail["links_restored"] = restore_links(doc, original_pages)
                save_pdf(doc, baked_path)
            selected = baked_path
            with fitz.open(baked_path) as baked:
                checks, baked_pages = verify_structure(baked, original_pages)
                catalog = image_inventory(baked)
                checks["bake_image_content"] = not bool(image_content_identities(detail["original_images"]) -
                                                        image_content_identities(catalog))
                visual_pass, visual = compare_visuals(baked, temp, settings, strict=True)
                detail["bake_visual_checks"] = visual
                detail["baked"] = [public_snapshot(page) for page in baked_pages]
                row["checks"].update(checks)
                row["checks"]["appearance"] = visual_pass
                if not all(checks.values()) or not visual_pass:
                    raise ReviewRequired("Baking changed structure or visible appearance; inspect comparisons")
            detail["baked_images"] = catalog
            profile = settings["profiles"][row["profile"]]
            excluded = any(fnmatch.fnmatchcase(relative.as_posix().casefold(), pattern.casefold())
                           for pattern in settings["preserve_images_for"])
            final_pages = baked_pages
            if selected.stat().st_size > settings["target_bytes"]:
                for index, stage in enumerate(profile["passes"], 1):
                    candidate = temp / f"pass-{index}.pdf"
                    # Always reopen the pristine baked PDF. No generation loss.
                    with fitz.open(baked_path) as work:
                        changes = compress_photos(work, catalog, stage, profile, excluded)
                        save_pdf(work, candidate)
                    with fitz.open(candidate) as work:
                        candidate_checks, candidate_pages = verify_structure(work, original_pages, baked_pages)
                        appearance, visual = compare_visuals(work, temp, settings)
                    candidate_checks["appearance"] = appearance
                    attempt = {"pass": index, "settings": stage, "bytes": candidate.stat().st_size,
                               "checks": candidate_checks, "visual_checks": visual, "images": changes}
                    detail["attempts"].append(attempt)
                    if not all(candidate_checks.values()):
                        row["notes"].append(f"Stopped at pass {index}: validation failed; retained previous safe copy")
                        break
                    if candidate.stat().st_size < selected.stat().st_size:
                        selected = candidate
                        final_pages = candidate_pages
                        row["compression_pass"] = str(index)
                        row["checks"].update(candidate_checks)
                    if selected.stat().st_size <= settings["target_bytes"]:
                        break
                    if not any(c["action"] == "recompressed" for c in changes):
                        # Later passes may still save bytes at lower quality, so
                        # continue unless images were all categorically excluded.
                        if excluded or all(c["reason"] != "Recompression would not save at least 10%; image left unchanged"
                                           for c in changes):
                            break
            with fitz.open(selected) as final:
                checks, final_pages = verify_structure(final, original_pages, baked_pages)
                appearance, visual = compare_visuals(final, temp, settings)
                row["checks"].update(checks)
                row["checks"]["appearance"] = appearance
                detail["final_visual_checks"] = visual
                detail["final_images"] = image_inventory(final)
                detail["final"] = [public_snapshot(page) for page in final_pages]
                row["website_pages"] = len(final)
                row["website_annotations"] = sum(len(p["annotations"]) for p in final_pages)
                row["website_links"] = sum(len(p["links"]) for p in final_pages)
                row["website_bytes"] = selected.stat().st_size
                row["checks"]["size"] = row["website_bytes"] < settings["maximum_bytes"]
                row["checks"]["original_unchanged"] = sha256_file(source) == source_hash
                failed = [name for name, ok in row["checks"].items() if ok is not True]
                if failed:
                    row["notes"].append("Failed checks: " + ", ".join(failed))
                else:
                    row["result"] = "PASS"
                if row["website_bytes"] > settings["target_bytes"]:
                    row["notes"].append(f"Preferred {settings['target_bytes']/1000:g} KB target was not reached; quality limits were respected")
                if row["result"] == "REVIEW" or mode == "pilot":
                    for number, page in enumerate(final):
                        preview = report_dir / "comparisons" / f"{file_id}-page-{number+1}.jpg"
                        comparison_preview(temp / f"before-{number}.png", page, preview,
                                           f"Page {number + 1} | {relative.name[:110]}")
                        row["previews"].append(preview.relative_to(report_dir).as_posix())
        except Exception as exc:
            row["result"] = "REVIEW"
            row["notes"].append(str(exc) or type(exc).__name__)
            detail["exception"] = traceback.format_exc()
            if selected and selected.exists():
                try:
                    with fitz.open(selected) as review:
                        row["website_pages"] = len(review)
                        row["website_annotations"] = sum(1 for page in review for _ in page.annots() or [])
                        row["website_bytes"] = selected.stat().st_size
                        for number, page in enumerate(review):
                            original_render = temp / f"before-{number}.png"
                            if original_render.exists():
                                preview = report_dir / "comparisons" / f"{file_id}-page-{number+1}.jpg"
                                comparison_preview(original_render, page, preview, f"REVIEW | Page {number+1}")
                                row["previews"].append(preview.relative_to(report_dir).as_posix())
                except Exception:
                    pass
        finally:
            try:
                row["checks"]["original_unchanged"] = sha256_file(source) == source_hash
            except OSError:
                row["checks"]["original_unchanged"] = False
            if row["checks"]["original_unchanged"] is not True:
                row["result"] = "REVIEW"
                row["notes"].append("Source changed during processing; no automatic publication")
            detail["mupdf_messages"] = fitz.TOOLS.mupdf_warnings(reset=True)
        folder = "REVIEW" if row["result"] != "PASS" else ("PILOT PDFs" if mode == "pilot" else "WEBSITE PDFs")
        destination = root / folder / run_id / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.resolve() == source.resolve():
            raise RuntimeError("Refusing to overwrite an original")
        copy_source = selected if selected and selected.exists() else source
        row["copy_kind"] = ("converted candidate" if copy_source == selected else
                            "UNCONVERTED SOURCE COPY - not website-ready")
        # A failed/interrupted filesystem copy must not leave a partial .pdf
        # in a folder that contains automatic PASS files.
        pending = destination.with_name(destination.name + ".writing")
        try:
            shutil.copyfile(copy_source, pending)
            expected_hash = sha256_file(copy_source)
            if sha256_file(pending) != expected_hash:
                raise OSError("Output copy verification failed")
            os.replace(pending, destination)
        finally:
            pending.unlink(missing_ok=True)
        row["output"] = destination.relative_to(root).as_posix()
        row["output_sha256"] = sha256_file(destination)
        if row["result"] != "PASS":
            destination.with_name(destination.name + ".REVIEW.txt").write_text(
                row["copy_kind"] + "\n\n" + "\n".join(row["notes"]) +
                "\n\nDo not upload this file until reviewed. ORIGINALS was not edited.\n", encoding="utf-8")
    row["seconds"] = round(time.monotonic() - start, 2)
    detail["result"] = row
    write_json(report_dir / row["details"], detail)
    return row


def safe_csv(value):
    value = "" if value is None else str(value)
    return "'" + value if value.startswith(("=", "+", "-", "@")) else value


def relative_href(path, base):
    return quote(os.path.relpath(path, base).replace(os.sep, "/"), safe="/.")


def filesystem_failure(source, relative, root, run_id, settings, exc):
    """Keep processing other files when an input is locked or a copy fails."""
    file_id = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16]
    try:
        size = source.stat().st_size
    except OSError:
        size = 0
    row = {"filename": relative.as_posix(), "profile": profile_for(relative, settings),
        "result": "REVIEW", "notes": ["File could not be processed/copied: " + str(exc)],
        "checks": {name: None for name in CHECK_NAMES}, "original_bytes": size,
        "website_bytes": None, "original_pages": None, "website_pages": None,
        "original_annotations": None, "website_annotations": None,
        "original_links": None, "website_links": None, "output": None,
        "source_sha256": None, "output_sha256": None, "previews": [],
        "details": f"details/{file_id}.json", "compression_pass": "none", "seconds": 0,
        "copy_kind": "No output could be written", "started": now()}
    write_json(root / "REPORTS" / run_id / row["details"],
               {"result": row, "exception": traceback.format_exc()})
    return row


def write_reports(root, report_dir, summary):
    rows = summary["files"]
    fields = ["Filename", "Profile", "Original MB", "Website KB", "Original pages", "Website pages",
              "Original annotations", "Website annotations", "Original links", "Website links"]
    fields += [name.replace("_", " ").title() for name in CHECK_NAMES]
    fields += ["Compression pass", "Result", "Notes", "Output", "Source SHA256", "Output SHA256", "Seconds"]
    with (report_dir / "processing_report.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        for r in rows:
            values = [r["filename"], r["profile"], round(r["original_bytes"] / 1_000_000, 3),
                round(r["website_bytes"] / 1000, 1) if r["website_bytes"] is not None else None,
                r["original_pages"], r["website_pages"], r["original_annotations"], r["website_annotations"],
                r["original_links"], r["website_links"]]
            values += ["PASS" if r["checks"].get(name) is True else
                       ("FAIL" if r["checks"].get(name) is False else "NOT CHECKED") for name in CHECK_NAMES]
            values += [r["compression_pass"], r["result"], "; ".join(r["notes"]), r["output"],
                       r["source_sha256"], r["output_sha256"], r["seconds"]]
            writer.writerow([safe_csv(v) for v in values])
    write_json(report_dir / "summary.json", summary)
    escaped = html.escape
    entries = []
    for r in rows:
        preview_links = " ".join(f'<a href="{quote(p, safe="/.")}">Page {i+1}</a>'
                                 for i, p in enumerate(r["previews"]))
        if r["output"]:
            output_link = relative_href(root / r["output"], report_dir)
            file_link = f'<a href="{output_link}">{escaped(r["filename"])}</a>'
        else:
            file_link = escaped(r["filename"])
        pages = f'{r["original_pages"]} &rarr; {r["website_pages"]}'
        annotations = f'{r["original_annotations"]} &rarr; {r["website_annotations"]}'
        size = f'{r["website_bytes"] / 1000:,.1f} KB' if r["website_bytes"] is not None else "unconverted"
        failure = ", ".join(name for name, value in r["checks"].items() if value is False)
        entries.append(f'''<tr><td>{file_link}
            <small>{escaped(r["profile"])} | {r["original_bytes"]/1_000_000:.2f} MB original</small></td>
            <td class="{r["result"].lower()}">{r["result"]}<small>{escaped(failure)}</small></td>
            <td>{size}</td><td>{pages}</td><td>{annotations}</td>
            <td>{preview_links}<small><a href="{r["details"]}">Detailed checks</a></small></td>
            <td>{escaped("; ".join(r["notes"]))}</td></tr>''')
    passed = sum(r["result"] == "PASS" for r in rows)
    banner = ("PILOT: automatic checks only. Check these PDFs on Android, iPhone and Windows before approving the bulk run."
              if summary["mode"] == "pilot" else
              "BULK: converted with the approved pilot settings. PASS means automatic checks passed; spot-check the published copies.")
    document = f'''<!doctype html><html lang="en"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1"><title>PDF File Conversions PDF report</title>
    <style>body{{margin:0;background:#eff0f2;color:#171717;font:16px/1.5 Segoe UI,Arial,sans-serif}}
    header{{background:#101010;border-bottom:6px solid #f3c800;padding:24px;color:white}}
    main{{padding:24px;max-width:1600px;margin:auto}}h1{{margin:0;font-size:28px}}
    .banner{{background:#fff3be;padding:16px;border-left:5px solid #e2b900}}
    table{{border-collapse:collapse;width:100%;background:white;margin-top:20px}}
    th,td{{padding:12px;text-align:left;border-bottom:1px solid #ddd;vertical-align:top}}
    th{{background:#202020;color:white;position:sticky;top:0}}small{{display:block;color:#555}}
    a{{color:#004da5}}.pass{{color:#126324;font-weight:bold}}.review{{color:#a52c17;font-weight:bold}}
    .scroll{{overflow-x:auto}}footer{{margin:20px 0;color:#555}}</style>
    <header><h1>PDF File Conversions PDF conversion</h1><div>{escaped(summary["started"])} | {escaped(summary["mode"].upper())}</div></header>
    <main><p class="banner">{banner}</p><p><b>{passed} PASS</b> &nbsp; | &nbsp;
    <b>{len(rows)-passed} REVIEW</b> &nbsp; | &nbsp; {summary["selected_count"]} selected of {summary["available_count"]} PDFs
    &nbsp; | &nbsp; State: {escaped(summary["state"])}</p>
    <p><a href="processing_report.csv">Open CSV in Excel</a> | <a href="summary.json">Full run data</a></p>
    <p>Output filenames and folders match the source names. Original files are never written.
    Preview images are for comparison only; inspect fine details in the PDFs at full zoom.</p>
    <div class="scroll"><table><thead><tr><th>File</th><th>Result</th><th>Output size</th><th>Pages</th>
    <th>Annotations</th><th>Compare</th><th>Notes</th></tr></thead><tbody>{"".join(entries)}</tbody></table></div>
    <footer>Converter {VERSION}. Size units are decimal: 1 MB = 1,000,000 bytes; 1 KB = 1,000 bytes.
    Page rendering is used only for verification and previews. Photos use lossy JPEG compression;
    preserve ORIGINALS as editable masters. REVIEW files are not ready to upload.</footer></main></html>'''
    (report_dir / "OPEN REPORT.html").write_text(document, encoding="utf-8")


def discover_inputs(root, patterns):
    result = []
    original_root = root / "ORIGINALS"
    for directory, folders, files in os.walk(original_root, followlinks=False):
        folders[:] = sorted(f for f in folders if not (Path(directory) / f).is_symlink())
        for filename in sorted(files):
            path = Path(directory) / filename
            if path.suffix.casefold() != ".pdf":
                continue
            if path.is_symlink() or path.resolve() != path.absolute():
                raise ValueError(f"Move real PDF files into ORIGINALS; a link/junction was found: {filename}")
            relative = path.relative_to(original_root)
            if not patterns or any(fnmatch.fnmatchcase(relative.as_posix().casefold(), p.casefold()) for p in patterns):
                result.append((path, relative))
    return sorted(result, key=lambda pair: pair[1].as_posix().casefold())


def select_pilot(inputs, settings, forced):
    if len(inputs) <= settings["pilot_limit"]:
        return inputs
    # Include both document profiles, mixing large, medium and small files.
    pools = []
    for profile in ("parts", "installation"):
        group = sorted((pair for pair in inputs if profile_for(pair[1], settings, forced) == profile),
                       key=lambda pair: pair[0].stat().st_size, reverse=True)
        ordered = []
        while group:
            ordered.append(group.pop(0))
            if group:
                ordered.append(group.pop(len(group) // 2))
            if group:
                ordered.append(group.pop())
        pools.append(ordered)
    chosen = []
    while any(pools) and len(chosen) < settings["pilot_limit"]:
        for pool in pools:
            if pool and len(chosen) < settings["pilot_limit"]:
                chosen.append(pool.pop(0))
    return chosen


def latest_pilot(root):
    candidates = sorted((root / "REPORTS").glob("*/summary.json"), reverse=True)
    for path in candidates:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("mode") == "pilot" and data.get("state") == "complete":
            return path, data
    raise ValueError("Run a pilot first with the Convert PDFs workflow.")


def approval_evidence(root, settings):
    path, summary = latest_pilot(root)
    if summary["fingerprint"] != fingerprint(root, settings):
        raise ValueError("The converter/settings changed after the pilot. Run a new pilot before approval.")
    passing = [r for r in summary["files"] if r["result"] == "PASS"]
    if len({r["source_sha256"] for r in passing}) < settings["minimum_pilot_passes"]:
        raise ValueError(f"At least {settings['minimum_pilot_passes']} distinct passing PDFs are needed. "
                         "Use a representative mix of parts and installation PDFs, then run the pilot again.")
    for row in passing:
        output = root / row["output"]
        if not output.is_file() or sha256_file(output) != row["output_sha256"]:
            raise ValueError("A pilot output is missing or changed. Run a new pilot.")
    return path, summary, passing


def approve_pilot(root, settings):
    path, summary, passing = approval_evidence(root, settings)
    print("\nBefore approval, open REPORTS / " + summary["run_id"] + " / OPEN REPORT.html")
    print(f"This pilot has {len(passing)} automatic PASS files and {len(summary['files'])-len(passing)} REVIEW files.")
    print("Check all pilot PASS files; use both parts and installation examples. REVIEW files stay excluded.")
    print("Inspect the PDF itself: arrows/numbers, tiny parts, diagram labels, selectable text, page order and links.")
    print("Open comparisons in the report, then check the PDFs in these viewers:")
    attestations = []
    for viewer in ("Android Chrome", "Android Google/Samsung/native PDF viewer",
                   "iPhone Safari/PDF viewer", "Windows Chrome", "Adobe Acrobat on Windows"):
        answer = input(f"  {viewer}: did all pilot PASS files display correctly? Type YES: ").strip()
        if answer.upper() != "YES":
            print("Pilot remains unapproved. Complete the device checks, then run this step again.")
            return 1
        attestations.append(viewer)
    answer = input("Were parts AND installation documents, arrows, fine details and links checked? Type YES: ").strip()
    if answer.upper() != "YES":
        print("Pilot remains unapproved.")
        return 1
    write_json(root / "PILOT_APPROVAL.json", {"approved_at": now(), "fingerprint": summary["fingerprint"],
        "pilot_report": path.relative_to(root).as_posix(), "report_sha256": sha256_file(path),
        "viewers_confirmed_by_operator": attestations, "passing_files": len(passing)})
    print("Pilot approved for this converter and these settings. An approved batch can now process the supplied originals.")
    return 0


def require_approval(root, settings):
    path = root / "PILOT_APPROVAL.json"
    if not path.is_file():
        raise ValueError("Bulk conversion requires a reviewed pilot. Run and review a representative pilot first.")
    approval = json.loads(path.read_text(encoding="utf-8"))
    if approval["fingerprint"] != fingerprint(root, settings):
        raise ValueError("Settings/converter/dependencies changed. Repeat the pilot and device review.")
    report = root / approval["pilot_report"]
    if not report.is_file() or sha256_file(report) != approval["report_sha256"]:
        raise ValueError("The approved pilot report is missing or changed. Repeat the pilot.")
    summary = json.loads(report.read_text(encoding="utf-8"))
    passing = [r for r in summary["files"] if r["result"] == "PASS"]
    if len({r["source_sha256"] for r in passing}) < settings["minimum_pilot_passes"]:
        raise ValueError("Approved pilot does not meet the sample requirement.")
    for row in passing:
        file = root / row["output"]
        if not file.is_file() or sha256_file(file) != row["output_sha256"]:
            raise ValueError("An approved pilot output is missing/changed. Repeat the pilot.")
    return approval


def run_conversion(root, settings, mode, patterns=(), forced="auto"):
    approval = require_approval(root, settings) if mode == "bulk" else None
    inputs = discover_inputs(root, patterns)
    if not inputs:
        raise ValueError("No PDFs found. Copy your master PDFs into ORIGINALS, then run the Convert PDFs workflow.")
    selected = select_pilot(inputs, settings, forced) if mode == "pilot" else inputs
    run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "_" + uuid.uuid4().hex[:6]
    report_dir = root / "REPORTS" / run_id
    report_dir.mkdir(parents=True)
    summary = {"run_id": run_id, "mode": mode, "started": now(), "state": "running",
               "fingerprint": fingerprint(root, settings), "dependencies": dependencies(),
               "settings": settings, "python": sys.version, "platform": platform.platform(),
               "selected_count": len(selected), "available_count": len(inputs),
               "operator_pilot_approval": approval, "files": []}
    print(f"\n{mode.upper()}: {len(selected)} of {len(inputs)} PDFs. Originals are read-only inputs.")
    print("Report:", report_dir / "OPEN REPORT.html")
    print("Each PDF may take time when the source photographs are very large. Ctrl+C stops safely.\n")
    write_reports(root, report_dir, summary)
    try:
        for index, (source, relative) in enumerate(selected, 1):
            print(f"[{index}/{len(selected)}] {relative}", flush=True)
            try:
                row = process_file(source, relative, root, run_id, settings, mode, forced)
            except OSError as exc:
                row = filesystem_failure(source, relative, root, run_id, settings, exc)
            summary["files"].append(row)
            size = f"{row['website_bytes']/1000:,.1f} KB" if row["website_bytes"] is not None else "unconverted"
            print(f"    {row['result']} | {size} | {row['original_annotations']} -> {row['website_annotations']} annotations", flush=True)
            if row["result"] != "PASS":
                print("    " + "; ".join(row["notes"]), flush=True)
            write_reports(root, report_dir, summary)
        summary["state"] = "complete"
    except KeyboardInterrupt:
        summary["state"] = "interrupted"
        print("\nStopped. Completed results/report are retained. Run again to start a new run.")
    except Exception:
        summary["state"] = "error"
        summary["error"] = traceback.format_exc()
        raise
    finally:
        summary["finished"] = now()
        write_reports(root, report_dir, summary)
    passed = sum(row["result"] == "PASS" for row in summary["files"])
    print(f"\nFinished: {passed} PASS, {len(summary['files'])-passed} REVIEW.\n{report_dir / 'OPEN REPORT.html'}")
    if mode == "pilot":
        print("Pilot PDFs are held in PILOT PDFs. Confirm the device tests, before running an approved batch.")
    return 0 if summary["state"] == "complete" and passed == len(summary["files"]) else 2


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("pilot", "bulk", "approve", "check"))
    parser.add_argument("--root", type=Path, default=ROOT, help="Converter folder; normally leave unchanged")
    parser.add_argument("--include", action="append", default=[], help="Optional relative filename glob; repeatable")
    parser.add_argument("--profile", choices=("auto", "parts", "installation"), default="auto")
    args = parser.parse_args(argv)
    try:
        validate_dependencies()
        root = args.root.resolve()
        settings = load_settings(root)
        create_folders(root)
        if args.mode == "check":
            print("Installation OK. Tested dependencies:", dependencies())
            return 0
        if args.mode in ("approve", "bulk") and (args.include or args.profile != "auto"):
            raise ValueError("For an approved bulk run, use settings.json rules rather than temporary CLI overrides.")
        if args.mode == "pilot" and args.profile != "auto":
            raise ValueError("Put profile overrides in settings.json so pilot and bulk use identical settings.")
        with exclusive_run(root):
            if args.mode == "approve":
                return approve_pilot(root, settings)
            return run_conversion(root, settings, args.mode, args.include, args.profile)
    except (ValueError, OSError, KeyError) as exc:
        print("\nACTION NEEDED:", exc)
        return 1
    except Exception:
        print("\nUnexpected error. Keep the report and share the message below for troubleshooting.")
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
