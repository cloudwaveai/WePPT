import shutil
import unittest
from unittest.mock import patch

from ppt_workbench.reference_inspection import inspect_reference


def make_pdf(text):
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    result = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


class ReferenceInspectionTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("pdftotext"), "Poppler is optional")
    def test_extracts_pdf_text(self):
        result = inspect_reference(make_pdf("Reference evidence"), "application/pdf")
        self.assertEqual(result["readStatus"], "text-available")
        self.assertIn("Reference evidence", result["text"])
        self.assertIn("扫描页未检查", result["note"])

    @unittest.skipUnless(shutil.which("pdftotext"), "Poppler is optional")
    def test_invalid_pdf_is_not_inspected(self):
        result = inspect_reference(b"%PDF-not valid", "application/pdf")
        self.assertEqual(result["readStatus"], "not-inspected")
        self.assertEqual(result["text"], "")

    def test_no_extractor_is_truthful(self):
        with patch("ppt_workbench.reference_inspection.shutil.which", return_value=None):
            result = inspect_reference(make_pdf("text"), "application/pdf")
        self.assertEqual(result["readStatus"], "not-inspected")
        self.assertIn("未安装", result["note"])

    def test_image_is_never_claimed_inspected(self):
        result = inspect_reference(b"image", "image/png")
        self.assertEqual(result["purpose"], "visual-reference")
        self.assertEqual(result["readStatus"], "not-inspected")
        self.assertFalse(result["text"])

    @unittest.skipUnless(shutil.which("pdftotext"), "Poppler is optional")
    def test_extraction_is_truncated(self):
        with patch("ppt_workbench.reference_inspection.MAX_TEXT_CHARS", 10):
            result = inspect_reference(make_pdf("Reference evidence"), "application/pdf")
        self.assertEqual(len(result["text"]), 10)
        self.assertIn("截断", result["note"])


if __name__ == "__main__":
    unittest.main()
