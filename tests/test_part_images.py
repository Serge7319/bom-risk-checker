import unittest

from src.component_family_profiles import FAMILY_PROFILES
from src.part_images import (
    ILLUSTRATION_LABEL,
    attach_saved_component_images,
    illustration_kind,
    normalize_supplier_image_url,
    part_image_markup,
)

_KINDS = {
    "ic",
    "resistor",
    "capacitor",
    "connector",
    "diode",
    "transistor",
    "inductor",
    "sensor",
    "switch",
    "generic",
}


def test_accepts_https_product_image_from_supported_distributor():
    assert normalize_supplier_image_url(
        "https://media.digikey.com/Photos/Texas%20Instruments/LM358.jpg",
        provider="DigiKey",
    ) == "https://media.digikey.com/Photos/Texas%20Instruments/LM358.jpg"


def test_upgrades_http_product_image_to_https():
    assert normalize_supplier_image_url(
        "http://www.mouser.com/images/sample.png",
        provider="Mouser",
    ) == "https://www.mouser.com/images/sample.png"


def test_rejects_untrusted_hosts_and_active_content():
    assert normalize_supplier_image_url("https://example.test/part.jpg") == ""
    assert normalize_supplier_image_url("javascript:alert(1)") == ""
    assert normalize_supplier_image_url("https://www.newark.com/part.svg") == ""


def test_constructs_newark_photo_from_documented_image_object():
    assert normalize_supplier_image_url(
        {"baseName": "/1234567-40.jpg", "vrntPath": "nio/"},
        provider="Newark",
    ) == "https://www.newark.com/productimages/standard/en_US/1234567-40.jpg"


def test_neutral_part_thumbnail_does_not_claim_to_be_a_product_photo():
    markup = part_image_markup("", "ABC-123")
    assert ILLUSTRATION_LABEL in markup
    assert "Product photo for ABC-123" not in markup
    assert "<img" not in markup
    assert 'data-illustration="generic"' in markup


def test_every_component_family_has_an_illustration_fallback():
    seen = set()
    for family_id in {profile.id for profile in FAMILY_PROFILES.values()}:
        markup = part_image_markup("", "PART-1", category=family_id)
        kind = illustration_kind(category=family_id)
        assert kind in _KINDS
        assert ILLUSTRATION_LABEL in markup
        assert f'data-illustration="{kind}"' in markup
        assert "Product photo" not in markup
        assert "<img" not in markup
        seen.add(kind)
    assert seen == _KINDS


def test_mpn_alone_does_not_select_a_category_illustration():
    markup = part_image_markup("", "LM358DT", part={"manufacturer_part_number": "LM358DT"})
    assert 'data-illustration="generic"' in markup
    assert 'data-illustration="ic"' not in markup
    assert ILLUSTRATION_LABEL in markup


def test_supplier_photo_is_used_when_the_url_is_trusted():
    markup = part_image_markup(
        "https://mm.digikey.com/Volume0/opasdata/d220001/medias/images/2/LM358.jpg",
        "LM358DT",
        part={"description": "IC OPAMP GP 2 CIRCUIT 8SO"},
    )
    assert "<img" in markup
    assert "Product photo for LM358DT" in markup
    assert ILLUSTRATION_LABEL not in markup
    assert "data-illustration" not in markup


def test_supplier_description_selects_the_op_amp_illustration():
    markup = part_image_markup(
        "",
        "LM358DT",
        part={
            "description": "IC OPAMP GP 2 CIRCUIT 8SO",
            "Category": "Catalog candidate — insufficient evidence for compatibility",
            "Estimated Risk": "Unknown",
        },
    )
    assert 'data-illustration="ic"' in markup
    assert ILLUSTRATION_LABEL in markup
    assert "<img" not in markup


def test_missing_category_metadata_uses_the_generic_illustration():
    markup = part_image_markup(
        "",
        "ABC-123",
        part={"Category": "Catalog candidate — insufficient evidence for compatibility"},
    )
    assert 'data-illustration="generic"' in markup
    assert ILLUSTRATION_LABEL in markup
    assert "<img" not in markup


def test_stored_description_selects_the_category_drawing():
    capacitor = part_image_markup("", "GRM188", part={"description": "Ceramic capacitor"})
    ic = part_image_markup("", "MAX32625", part={"description": "Low-power microcontroller"})
    assert 'data-illustration="capacitor"' in capacitor
    assert 'data-illustration="ic"' in ic
    assert "Product photo for GRM188" not in capacitor
    assert "Product photo for MAX32625" not in ic


def test_part_thumbnail_escapes_part_number_and_only_embeds_trusted_image():
    markup = part_image_markup(
        "https://media.digikey.com/photos/sample.jpg",
        '<script>alert(1)</script>',
    )
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert 'src="https://media.digikey.com/photos/sample.jpg"' in markup



class SavedComponentImageTests(unittest.TestCase):
    def test_saved_component_photo_attaches_by_analysis_and_mpn(self):
        rows = attach_saved_component_images(
            [{"analysis_id": "analysis-1", "mpn": "LM358DT"}],
            [{
                "analysis_id": "analysis-1",
                "mpn": "LM358DT",
                "image_url": "https://media.digikey.com/Photos/TI/LM358.jpg",
                "manufacturer": "Texas Instruments",
                "description_raw": "Operational amplifier",
            }],
        )
        self.assertEqual(rows[0]["image_url"], "https://media.digikey.com/Photos/TI/LM358.jpg")
        self.assertEqual(rows[0]["manufacturer"], "Texas Instruments")
        self.assertEqual(rows[0]["description_raw"], "Operational amplifier")

    def test_unlinked_component_uses_only_a_unique_trusted_saved_photo(self):
        unique = attach_saved_component_images(
            [{"mpn": "LM358DT"}],
            [{
                "analysis_id": "analysis-1",
                "mpn": "LM358DT",
                "image_url": "https://media.digikey.com/Photos/TI/LM358.jpg",
            }],
        )
        ambiguous = attach_saved_component_images(
            [{"mpn": "LM358DT"}],
            [
                {"analysis_id": "analysis-1", "mpn": "LM358DT", "image_url": "https://media.digikey.com/Photos/TI/LM358.jpg"},
                {"analysis_id": "analysis-2", "mpn": "LM358DT", "image_url": "https://www.mouser.com/images/LM358.jpg"},
            ],
        )
        self.assertEqual(unique[0]["image_url"], "https://media.digikey.com/Photos/TI/LM358.jpg")
        self.assertNotIn("image_url", ambiguous[0])
