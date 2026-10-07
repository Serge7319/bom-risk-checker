from src.part_images import normalize_supplier_image_url, part_image_markup


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
    assert "No supplier photo available for ABC-123" in markup
    assert "<img" not in markup


def test_part_thumbnail_escapes_part_number_and_only_embeds_trusted_image():
    markup = part_image_markup(
        "https://media.digikey.com/photos/sample.jpg",
        '<script>alert(1)</script>',
    )
    assert "<script>" not in markup
    assert "&lt;script&gt;" in markup
    assert 'src="https://media.digikey.com/photos/sample.jpg"' in markup
