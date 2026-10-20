import unittest

from src.approval_evidence import has_document_page_citation


class ApprovalEvidenceCitationTests(unittest.TestCase):
    def test_accepts_part_or_document_identifier_with_pdf_pages(self):
        self.assertTrue(
            has_document_page_citation("MC68HC11E1 datasheet Rev. 2, PDF pp. 8–10")
        )
        self.assertTrue(
            has_document_page_citation("Motorola MCU reference manual, pages 14-16")
        )

    def test_rejects_blank_placeholders_and_page_numbers_without_document_identity(self):
        for value in (
            "",
            "NA",
            "N/A",
            "N.A. p. 3",
            "unknown pages 2-3",
            "not available",
            "NA page 3",
            "PDF pp. 8–10",
        ):
            with self.subTest(value=value):
                self.assertFalse(has_document_page_citation(value))

    def test_rejects_citations_without_page_numbers(self):
        self.assertFalse(has_document_page_citation("MC68HC11E1 datasheet Rev. 2"))


if __name__ == "__main__":
    unittest.main()
