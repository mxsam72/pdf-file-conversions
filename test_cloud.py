"""Tests for upload boundaries, metadata copies, and published result scope."""
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

import pymupdf as fitz

import cloud_run as cloud
import converter as c
from prepare_upload import prepare_copy
from test_converter import create_fixture


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, entries):
        archive = self.root / "input.zip"
        with zipfile.ZipFile(archive, "w") as z:
            for name, content in entries:
                z.writestr(name, content)
        return archive

    def test_zip_rejects_traversal_collisions_and_unrelated_files(self):
        for entries in [ [("../outside.pdf", b"a")], [("/absolute.pdf", b"a")],
                         [("a.pdf", b"a"), ("A.pdf", b"b")],
                         [("script.py", b"a")], [("a\\b.pdf", b"a")]]:
            with self.subTest(entries=entries):
                archive = self.bundle(entries)
                with self.assertRaises(ValueError):
                    cloud.extract_inputs(archive, self.root / "extracted")
                self.assertFalse((self.root / "outside.pdf").exists())

    def test_manifest_verifies_exact_files_and_uppercase_extension(self):
        pdf = self.root / "sample.PDF"
        create_fixture(pdf, photo=False)
        manifest = {"files": [{"file": "sample.PDF", "prepared_sha256": c.sha256_file(pdf)}]}
        archive = self.bundle([("sample.PDF", pdf.read_bytes()), ("manifest.json", json.dumps(manifest))])
        cloud.extract_inputs(archive, self.root / "good")
        manifest["files"][0]["prepared_sha256"] = "0" * 64
        archive = self.bundle([("sample.PDF", pdf.read_bytes()), ("manifest.json", json.dumps(manifest))])
        with self.assertRaisesRegex(ValueError, "checksum"):
            cloud.extract_inputs(archive, self.root / "bad")

    def test_only_result_folders_are_packaged(self):
        for folder, name in [("ORIGINALS", "master.pdf"), ("REPORTS/run", "summary.json"),
                             ("PILOT PDFs/run", "sample.pdf"), ("unrelated", "other.pdf")]:
            path = self.root / "work" / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("synthetic")
        archive = self.root / "results.zip"
        cloud.package_results(self.root / "work", archive, {"mode": "pilot"})
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), {"RUN_INFO.json", "START_HERE.txt",
                "REPORTS/run/summary.json", "PILOT PDFs/run/sample.pdf"})

    def test_metadata_copy_preserves_visible_annotation_and_source(self):
        source, clean = self.root / "source.pdf", self.root / "clean.pdf"
        create_fixture(source, photo=False)
        with fitz.open(source) as doc:
            page = doc[0]
            line = page.add_line_annot((50, 400), (250, 450))
            line.set_info(title="SYNTHETIC HIDDEN AUTHOR", subject="internal test label")
            line.update()
            doc.saveIncr()
        before = c.sha256_file(source)
        result = prepare_copy(source, clean)
        self.assertEqual(c.sha256_file(source), before)
        self.assertEqual(result["author_labels_removed"], 1)
        self.assertTrue(all(p["render_pixels_identical"] for p in result["page_checks"]))
        with fitz.open(clean) as doc:
            self.assertFalse(doc.metadata["author"])
            page = doc[0]
            self.assertFalse(next(page.annots()).info["title"])
        with self.assertRaises(ValueError):
            prepare_copy(source, source)

    def test_public_report_omits_extracted_text_and_annotation_info(self):
        source = self.root / "synthetic.pdf"
        create_fixture(source, photo=False)
        with fitz.open(source) as doc:
            snapshot = c.snapshot_page(doc[0])
            report = c.public_snapshot(snapshot)
        serialized = json.dumps(report)
        self.assertNotIn("SYNTHETIC TEST", serialized)
        self.assertNotIn("https://example.com", serialized)
        self.assertIn("text_sha256", report)
        self.assertNotIn("text", report)


if __name__ == "__main__":
    unittest.main()
