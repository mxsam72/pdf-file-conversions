"""Reproducible functional tests; all PDFs are generated locally in temporary folders.

These fixtures are synthetic. They do not replace PDF File Conversions's real-document pilot
or Android/iPhone/desktop testing. Run: python test_converter.py
"""
import copy
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, ImageDraw
import pymupdf as fitz

import converter as c


HERE = Path(__file__).resolve().parent


def photo_bytes(width=2400, height=1800, seed=19):
    """Colored textured fixture, saved as PNG to exercise a large photo stream."""
    random = np.random.default_rng(seed)
    y, x = np.mgrid[:height, :width]
    noise = random.normal(0, 5, (height, width, 3))
    data = np.stack((45 + x / width * 150 + 30*np.sin(y/height*8),
                     55 + y / height * 130 + 25*np.cos(x/width*7),
                     60 + (x + y) / (width + height) * 120 + 35*np.sin(x/width*10)), axis=2) + noise
    image = Image.fromarray(np.clip(data, 0, 255).astype(np.uint8))
    draw = ImageDraw.Draw(image)
    draw.rectangle((width*.17, height*.30, width*.78, height*.63), fill=(158, 116, 48))
    draw.ellipse((width*.12, height*.53, width*.35, height*.88), fill=(25, 28, 29))
    draw.ellipse((width*.60, height*.53, width*.83, height*.88), fill=(25, 28, 29))
    draw.line((width*.45, height*.3, width*.6, height*.10), fill=(175, 180, 185), width=14)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


PHOTO = None


def create_fixture(path, variant=0, photo=True, annotations=True, rotate=False, widgets=False):
    global PHOTO
    if photo and PHOTO is None:
        PHOTO = photo_bytes()
    doc = fitz.open()
    p = doc.new_page(width=612, height=792)
    p.insert_text((44, 50), f"PDF CONVERSION SYNTHETIC TEST {variant} - NOT A PRODUCT DOCUMENT", fontsize=11)
    p.insert_text((44, 80), "Part  Qty  Description", fontsize=12)
    for i in range(5):
        p.draw_rect(fitz.Rect(40, 90+i*25, 560, 115+i*25), color=(0, 0, 0), width=.4)
        p.insert_text((50, 107+i*25), f"TEST-{i+1}   1   Synthetic component {variant}-{i+1}", fontsize=10)
    p.insert_text((44, 290), "View PDF File Conversions website", fontsize=11)
    p.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(40, 272, 230, 300),
                   "uri": "https://example.com/?page_id=762"})
    if widgets:
        widget = fitz.Widget()
        widget.field_name = "TEST preserved field"
        widget.field_type = fitz.PDF_WIDGET_TYPE_TEXT
        widget.field_value = "DO NOT FLATTEN ME"
        widget.rect = fitz.Rect(44, 320, 300, 350)
        p.add_widget(widget)
    if photo:
        p = doc.new_page(width=792 if rotate else 612, height=612 if rotate else 792)
        p.insert_text((40, 45), "Synthetic image fixture - inspect arrow and number 7", fontsize=12)
        target = fitz.Rect(40, 95, 740 if rotate else 570, 550 if rotate else 600)
        p.insert_image(target, stream=PHOTO, keep_proportion=True)
        if annotations:
            line = p.add_line_annot((135, 220), (350, 370))
            line.set_colors(stroke=(1, 0, 0))
            line.set_border(width=3)
            line.set_line_ends(0, 4)
            line.update()
            number = p.add_freetext_annot(fitz.Rect(95, 175, 145, 210), "7", fontsize=23,
                                         text_color=(1, 0, 0))
            number.update()
        # Shared image reused at a larger placement on one page and small on another.
        p.insert_image(fitz.Rect(440, 620 if not rotate else 555, 540, 695 if not rotate else 605), stream=PHOTO)
        if rotate:
            p.set_rotation(90)
        p.insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(40, 52, 200, 77),
                       "page": 0, "to": fitz.Point(40, 40)})
    doc.set_metadata({"title": f"Synthetic validation fixture {variant}", "author": "PDF File Conversions converter tests"})
    doc.save(path, deflate=True)
    doc.close()


class ConversionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pdf-conversion-test-")
        self.root = Path(self.temporary.name)
        for filename in ("settings.json", "converter.py"):
            shutil.copyfile(HERE / filename, self.root / filename)
        self.settings = c.load_settings(self.root)
        c.create_folders(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def convert(self, filename, **kwargs):
        path = self.root / "ORIGINALS" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        create_fixture(path, **kwargs)
        before = c.sha256_file(path)
        row = c.process_file(path, Path(filename), self.root, "test-run", self.settings, "pilot")
        self.assertEqual(before, c.sha256_file(path), "Original bytes changed")
        return path, row

    def test_photo_arrows_text_links_vectors_and_master(self):
        source, row = self.convert("DOC-DEMO PARTS.pdf")
        self.assertEqual(row["result"], "PASS", row["notes"])
        self.assertTrue(all(row["checks"].values()), row["checks"])
        self.assertEqual(row["original_annotations"], 2)
        self.assertEqual(row["website_annotations"], 0)
        self.assertEqual(row["original_links"], row["website_links"])
        self.assertLess(row["website_bytes"], 900000)
        self.assertGreater(row["original_bytes"], row["website_bytes"] * 2)
        output = self.root / row["output"]
        self.assertEqual(source.name, output.name)
        with fitz.open(output) as doc:
            self.assertEqual(len(doc), 2)
            self.assertIn("TEST-1", doc[0].get_text())
            self.assertGreater(len(doc[0].get_cdrawings()), 0)
            no_annotations = c.render(doc[1], 100, annots=False)
            annotations_on = c.render(doc[1], 100, annots=True)
            self.assertTrue(np.array_equal(np.asarray(no_annotations), np.asarray(annotations_on)))
            pixels = np.asarray(no_annotations)
            red = (pixels[:,:,0] > 180) & (pixels[:,:,1] < 100) & (pixels[:,:,2] < 100)
            self.assertGreater(red.sum(), 100, "Red callouts are absent from page content")

    def test_installation_profile_rotation_shared_image_and_form(self):
        _, row = self.convert("nested/DOC-DEMO INSTALL.pdf", variant=2, rotate=True, widgets=True)
        self.assertEqual(row["profile"], "installation")
        self.assertEqual(row["result"], "PASS", row["notes"])
        with fitz.open(self.root / row["output"]) as doc:
            widget = next(doc[0].widgets())
            self.assertEqual(widget.field_value, "DO NOT FLATTEN ME")
            self.assertEqual(doc[1].rotation, 90)
            catalog = c.image_inventory(doc)
            self.assertTrue(any(len(v["placements"]) >= 2 for v in catalog))

    def test_small_document_not_lossily_recompressed(self):
        _, row = self.convert("small.pdf", photo=False)
        self.assertEqual(row["result"], "PASS", row["notes"])
        self.assertEqual(row["compression_pass"], "none")

    def test_unsupported_redaction_and_sticky_note_quarantined(self):
        for name, kind in (("redaction.pdf", "redact"), ("notes.pdf", "note")):
            with self.subTest(kind=kind):
                source = self.root / "ORIGINALS" / name
                create_fixture(source, photo=False)
                with fitz.open(source) as doc:
                    if kind == "redact":
                        doc[0].add_redact_annot(fitz.Rect(40,40,100,60))
                    else:
                        doc[0].add_text_annot((70,70), "Important hidden comment")
                    doc.saveIncr()
                row = c.process_file(source, Path(name), self.root, "review-test", self.settings, "pilot")
                self.assertEqual(row["result"], "REVIEW")
                self.assertTrue(row["output"].startswith("REVIEW/"))
                self.assertIn("UNCONVERTED", row["copy_kind"])
                self.assertEqual(c.sha256_file(source), row["output_sha256"])

    def test_encrypted_and_corrupt_pdf_quarantined(self):
        source = self.root / "ORIGINALS" / "protected.pdf"
        with fitz.open() as doc:
            doc.new_page().insert_text((50,50), "Private test")
            doc.save(source, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="test")
        row = c.process_file(source, Path(source.name), self.root, "protected", self.settings, "pilot")
        self.assertEqual(row["result"], "REVIEW")
        corrupt = self.root / "ORIGINALS" / "broken.pdf"
        corrupt.write_bytes(b"This is not a PDF")
        row = c.process_file(corrupt, Path(corrupt.name), self.root, "broken", self.settings, "pilot")
        self.assertEqual(row["result"], "REVIEW")

    def test_size_limit_routes_to_review_instead_of_destroying_quality(self):
        self.settings["target_bytes"] = 200
        self.settings["maximum_bytes"] = 500
        _, row = self.convert("too-large INSTALL.pdf", photo=False)
        self.assertEqual(row["result"], "REVIEW")
        self.assertFalse(row["checks"]["size"])
        self.assertTrue(row["output"].startswith("REVIEW/"))

    def test_lost_text_and_links_detected(self):
        source = self.root / "ORIGINALS" / "text.pdf"
        create_fixture(source, photo=False)
        with fitz.open(source) as doc:
            before = [c.snapshot_page(p) for p in doc]
            link = doc[0].get_links()[0]
            doc[0].delete_link(link)
            doc[0].add_redact_annot(fitz.Rect(40,35,590,60))
            doc[0].apply_redactions()
            checks, _ = c.verify_structure(doc, before)
            self.assertFalse(checks["text"])
            self.assertFalse(checks["links"])

    def test_deleted_supported_link_is_restored(self):
        source = self.root / "ORIGINALS" / "links.pdf"
        create_fixture(source, photo=False)
        with fitz.open(source) as doc:
            before = [c.snapshot_page(p) for p in doc]
            page = doc[0]
            page.delete_link(page.get_links()[0])
            doc.reload_page(page)
            self.assertEqual(c.restore_links(doc, before), 1)
            output = self.root / "restored.pdf"
            c.save_pdf(doc, output)
        with fitz.open(output) as doc:
            checks, _ = c.verify_structure(doc, before)
            self.assertTrue(checks["links"])

    def test_file_io_failure_is_reported_and_other_files_continue(self):
        for name in ("a-locked.pdf", "b-readable.pdf"):
            create_fixture(self.root / "ORIGINALS" / name, photo=False)
        actual = c.process_file
        def fail_one(source, *args, **kwargs):
            if source.name == "a-locked.pdf":
                raise PermissionError("Synthetic locked-file error")
            return actual(source, *args, **kwargs)
        with patch.object(c, "process_file", side_effect=fail_one):
            self.assertEqual(c.run_conversion(self.root, self.settings, "pilot"), 2)
        _, report = c.latest_pilot(self.root)
        self.assertEqual([r["result"] for r in report["files"]], ["REVIEW", "PASS"])
        self.assertIsNone(report["files"][0]["output"])

    def test_missing_small_arrow_detected_by_annotation_pixels(self):
        before = Image.new("RGB", (600,800), "white")
        ImageDraw.Draw(before).line((200,250,220,275), fill="red", width=2)
        after = Image.new("RGB", before.size, "white")
        mask = Image.new("L", before.size)
        ImageDraw.Draw(mask).line((200,250,220,275), fill=255, width=2)
        metrics = c.visual_metrics(before, after, mask)
        self.assertLess(metrics["annotation_pixel_retention"], .1)
        self.assertGreater(metrics["block_ssim"], .99, "Fixture should illustrate a whole-page false negative")

    def test_transparency_and_raster_diagrams_left_unchanged(self):
        source = self.root / "ORIGINALS" / "diagram.pdf"
        rgba = Image.new("RGBA", (1200,1000), (255,0,0,80))
        stream = io.BytesIO(); rgba.save(stream, format="PNG")
        with fitz.open() as doc:
            doc.new_page().insert_image(fitz.Rect(40,40,500,500), stream=stream.getvalue())
            catalog = c.image_inventory(doc)
            self.assertTrue(catalog[0]["preserve_reason"])
            changes = c.compress_photos(doc, catalog, {"long_edge":1200, "quality":55},
                                        self.settings["profiles"]["parts"], False)
            self.assertTrue(all(v["action"] == "preserved" for v in changes))
        diagram = Image.new("RGB", (1200,1000), "white")
        ImageDraw.Draw(diagram).rectangle((50,50,900,850), outline="black", width=3)
        reason, _ = c.photo_assessment(diagram)
        self.assertTrue(reason)

    def test_target_stops_and_passes_restart_from_baked(self):
        self.settings["target_bytes"] = 15000
        self.settings["maximum_bytes"] = 1000000
        records = []
        original_compress = c.compress_photos
        def observe(doc, catalog, stage, profile, excluded):
            records.append([c.sha256_file(Path(doc.name)),
                            [(r["width"], r["height"], r.get("compressed_bytes")) for r in catalog]])
            return original_compress(doc, catalog, stage, profile, excluded)
        with patch.object(c, "compress_photos", side_effect=observe):
            _, row = self.convert("multi-pass PARTS.pdf", variant=3)
        self.assertGreaterEqual(len(records), 2)
        self.assertTrue(all(v == records[0] for v in records), "A pass used a previously compressed generation")
        self.assertEqual(row["result"], "PASS", row["notes"])

    def test_pilot_limit_mixed_profiles_and_bulk_gate(self):
        for index in range(20):
            path = self.root / "ORIGINALS" / f"test-{index:02} {'PARTS' if index%2 else 'INSTALL'}.pdf"
            create_fixture(path, variant=index, photo=False)
        pairs = c.discover_inputs(self.root, [])
        pilot = c.select_pilot(pairs, self.settings, "auto")
        self.assertEqual(len(pilot), 15)
        self.assertEqual({c.profile_for(rel, self.settings) for _, rel in pilot}, {"parts", "installation"})
        with self.assertRaises(ValueError):
            c.require_approval(self.root, self.settings)

    def test_reports_and_operator_approval_then_changed_settings_block_bulk(self):
        for index in range(10):
            path = self.root / "ORIGINALS" / f"test-{index:02} {'PARTS' if index%2 else 'INSTALL'}.pdf"
            create_fixture(path, variant=index, photo=False)
        code = c.run_conversion(self.root, self.settings, "pilot")
        self.assertEqual(code, 0)
        report, summary = c.latest_pilot(self.root)
        self.assertTrue((report.parent / "OPEN REPORT.html").is_file())
        self.assertTrue((report.parent / "processing_report.csv").is_file())
        with patch("builtins.input", return_value="YES"):
            self.assertEqual(c.approve_pilot(self.root, self.settings), 0)
        self.assertTrue(c.require_approval(self.root, self.settings))
        self.assertEqual(c.run_conversion(self.root, self.settings, "bulk"), 0)
        self.assertEqual(len(list((self.root / "WEBSITE PDFs").rglob("*.pdf"))), 10)
        changed = copy.deepcopy(self.settings); changed["target_bytes"] = 850000
        with self.assertRaises(ValueError):
            c.require_approval(self.root, changed)

    def test_profile_overrides_preservation_and_unicode_paths(self):
        self.settings["profile_overrides"] = [{"pattern":"*/DOC-*.pdf", "profile":"parts"}]
        self.assertEqual(c.profile_for(Path("Mowers/DOC-ABC.pdf"), self.settings), "parts")
        self.assertEqual(c.profile_for(Path("unknown.pdf"), self.settings), "installation")
        _, row = self.convert("Mowers/DOC-café (1).PDF", photo=False, variant=77)
        self.assertEqual(row["result"], "PASS", row["notes"])
        self.assertEqual(Path(row["output"]).name, "DOC-café (1).PDF")


if __name__ == "__main__":
    unittest.main(verbosity=2)
