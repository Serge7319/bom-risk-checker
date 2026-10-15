import unittest

from src.alternate_reference_parser import extract_description_alternates


class AlternateReferenceParserTests(unittest.TestCase):
    def test_explicit_replacement_hints_are_extracted_from_supplier_description(self):
        description = (
            "<p>Recommended Alt: 81-GRM188R72A104KA35.</p>"
            "<div>Successor product is GRM188R72A104KA35</div>"
            "<script>Recommended Alt BAD123</script>"
        )
        self.assertEqual(
            extract_description_alternates(description),
            ["81-GRM188R72A104KA35", "GRM188R72A104KA35"],
        )

    def test_parser_does_not_invent_candidates_from_generic_description_text(self):
        self.assertEqual(extract_description_alternates("High quality recommended solution"), [])
        self.assertEqual(extract_description_alternates("Replacement part is available"), [])
