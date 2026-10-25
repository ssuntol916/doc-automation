"""New PNG metadata declarations; native observations are not layout approval."""
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_STORED, ZipFile

from lxml import etree as ET
from PIL import Image
import pytest

from doc_automation.compose import (
    ComposeError, HANCOM_MAC_12_30_PNG_METADATA, TemplateDocument,
)
from doc_automation.hwpx import NS, local, own_text, parse_xml


FIXTURES = Path(__file__).parent / "fixtures/synthetic"


@pytest.fixture
def source_document(tmp_path):
    path = tmp_path / "source.hwpx"
    with ZipFile(path, "w", compression=ZIP_STORED) as archive:
        archive.writestr("mimetype", "application/hwp+zip")
        for name in ("header.xml", "section0.xml", "content.hpf"):
            archive.writestr("Contents/" + name, (FIXTURES / name).read_bytes())
    return path, TemplateDocument(path)


def raster(pixels, dpi=None, image_format="PNG"):
    image = Image.new("RGB", pixels, "white")
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((pixels[0] - 1, pixels[1] - 1), (0, 0, 255))
    stream = BytesIO()
    image.save(stream, format=image_format, **({"dpi": dpi} if dpi else {}))
    return stream.getvalue()


def picture_geometry(picture, *, without_metadata=False):
    copy = deepcopy(picture)
    for key in ("id", "instid"):
        copy.attrib.pop(key, None)
    copy.find("hc:img", NS).attrib.pop("binaryItemIDRef")
    if without_metadata:
        for name in ("imgClip", "imgDim"):
            copy.remove(copy.find("hp:" + name, NS))
    return ET.tostring(copy, method="c14n")


# Independently observed after actual viewport traversal, SaveAs, close/reopen
# in Hancom for Mac12.30.0 build6544. The diagnostic source SHA was
# 2e65680abec31d08af4dde5ac41c40fac62eff519f7ba371e572e2330741cf15;
# native result SHA ddb9bfa5bce3481b6f4925e279492117e94fb72d05e95154be8c0d7209194568.
# DPI120/none and boundary widths distinguish source-DPI/unchanged models.
@pytest.mark.parametrize("pixels,dpi,expected", [
    ((1800, 608), (96, 96), (135000, 45600)),
    ((1800, 609), (96, 96), (135000, 45660)),
    ((1800, 610), (96, 96), (135000, 45780)),
    ((1800, 611), (96, 96), (135000, 45840)),
    ((1800, 612), (96, 96), (135000, 45900)),
    ((1801, 610), (96, 96), (135060, 45780)),
    ((1802, 611), (96, 96), (135180, 45840)),
    ((1800, 610), (120, 120), (135000, 45780)),
    ((1800, 610), None, (135000, 45780)),
])
def test_opt_in_matches_loaded_png_observations_and_preserves_display_and_bytes(
        source_document, tmp_path, pixels, dpi, expected):
    source, doc = source_document
    source_bytes = source.read_bytes()
    paragraph = doc.paragraphs()[0]
    text = own_text(paragraph)
    raw = raster(pixels, dpi)
    options = {"width_mm": 47934 * 25.4 / 7200, "height_mm": 70,
               "description": "합성 좌표 검증·실제 사업 증빙 아님"}
    plain = doc.insert_picture(paragraph, raw, "image/png", "png", **options)
    original_plain = ET.tostring(plain)
    declared = doc.insert_picture(paragraph, raw, "image/png", "png", **options,
                                  raster_metadata_profile=HANCOM_MAC_12_30_PNG_METADATA)
    assert ET.tostring(plain) == original_plain
    assert own_text(paragraph) == text
    assert picture_geometry(plain, without_metadata=True) == picture_geometry(declared, without_metadata=True)
    dimension = declared.find("hp:imgDim", NS)
    clip = declared.find("hp:imgClip", NS)
    assert (int(dimension.get("dimwidth")), int(dimension.get("dimheight"))) == expected
    assert dict(clip.attrib) == {"left": "0", "right": str(expected[0]),
                                "top": "0", "bottom": str(expected[1])}
    size = declared.find("hp:curSz", NS)
    assert abs(int(size.get("width")) / int(size.get("height")) - pixels[0] / pixels[1]) < 0.001
    # The metadata profile changes neither the raster payload nor its edge
    # pixels. clip covers the complete imgDim, even when orgSz differs.
    output = tmp_path / "declared.hwpx"
    result = doc.save(output)
    assert result["package_validation"]["valid"] and not result["native_verified"]
    assert source.read_bytes() == source_bytes
    record = result["inserted_picture_metadata"][-1]
    assert record["raster_metadata_profile"] == HANCOM_MAC_12_30_PNG_METADATA
    assert record["raster_sha256"] == sha256(raw).hexdigest()
    assert record["pixel_size"] == list(pixels)
    assert record["shape_original_size_hwp"] == [pixels[0] * 75, pixels[1] * 75]
    assert record["image_dimension_hwp"] == list(expected)
    assert record["display_size_hwp"] == [int(size.get("width")), int(size.get("height"))]
    with ZipFile(output) as archive:
        manifest = parse_xml(archive.read("Contents/content.hpf"))
        item = next(node for node in manifest.iter()
                    if local(node) == "item" and node.get("id") == record["binary_id"])
        embedded = archive.read(item.get("href"))
        assert embedded == raw
        with Image.open(BytesIO(embedded)) as image:
            assert image.getpixel((0, 0)) == (255, 0, 0)
            assert image.getpixel((pixels[0] - 1, pixels[1] - 1)) == (0, 0, 255)


def test_metadata_selection_is_per_new_picture_and_duplicate_geometry_is_consistent(source_document):
    _, doc = source_document
    paragraph = doc.paragraphs()[0]
    raw = raster((1800, 610), (96, 96))
    selected = [doc.insert_picture(paragraph, raw, "image/png", "png", width_mm=80,
                                  raster_metadata_profile=HANCOM_MAC_12_30_PNG_METADATA)
                for _ in range(3)]
    assert len({picture_geometry(picture) for picture in selected}) == 1
    assert len({picture.get("id") for picture in selected}) == 3
    plain = doc.insert_picture(paragraph, raw, "image/png", "png", width_mm=80)
    assert plain.find("hp:imgDim", NS).get("dimheight") == "45750"
    assert doc._inserted_picture_metadata[-1]["raster_metadata_profile"] is None


@pytest.mark.parametrize("image_format,media,extension,profile,match", [
    ("PNG", "image/png", "png", "unknown", "Unknown raster metadata profile"),
    ("JPEG", "image/jpeg", "jpg", HANCOM_MAC_12_30_PNG_METADATA, "only for PNG"),
    ("BMP", "image/bmp", "bmp", HANCOM_MAC_12_30_PNG_METADATA, "only for PNG"),
])
def test_unsupported_metadata_profile_is_rejected_before_any_mutation(
        source_document, image_format, media, extension, profile, match):
    _, doc = source_document
    paragraph = doc.paragraphs()[0]
    before = ([ET.tostring(doc.xml(name)) for name in doc._roots],
              dict(doc._new_entries), doc._next_id, list(doc._inserted_picture_metadata))
    with pytest.raises(ComposeError, match=match):
        doc.insert_picture(paragraph, raster((20, 10), image_format=image_format), media, extension,
                           width_mm=80, raster_metadata_profile=profile)
    after = ([ET.tostring(doc.xml(name)) for name in doc._roots],
             dict(doc._new_entries), doc._next_id, list(doc._inserted_picture_metadata))
    assert after == before


def test_pixel_viewport_preserves_whole_payload_and_native_edge_coordinate_basis(source_document, tmp_path):
    source, doc = source_document
    original_source = source.read_bytes()
    paragraph = doc.paragraphs()[0]
    original_own_text = own_text(paragraph)
    raw = raster((13, 9), (120, 120))
    original = doc.insert_picture(paragraph, raw, "image/png", "png", width_mm=120,
        raster_metadata_profile=HANCOM_MAC_12_30_PNG_METADATA)
    original_geometry = ET.tostring(original)
    detail = doc.insert_picture(paragraph, raw, "image/png", "png", width_mm=120,
        viewport_pixels=[6, 3, 13, 9],
        raster_metadata_profile=HANCOM_MAC_12_30_PNG_METADATA)
    assert ET.tostring(original) == original_geometry and own_text(paragraph) == original_own_text
    # Actual Mac12.30 build6544 edge/loaded probes retained these coordinates.
    # imgDim-normalized interpretation produced7x5 instead of requested7x6.
    assert dict(detail.find("hp:imgClip", NS).attrib) == {
        "left": "450", "right": "975", "top": "225", "bottom": "675"}
    assert dict(detail.find("hp:imgDim", NS).attrib) == {"dimwidth": "960", "dimheight": "660"}
    assert dict(detail.find("hp:orgSz", NS).attrib) == {"width": "975", "height": "675"}
    assert detail.find("hp:renderingInfo/hc:scaMatrix", NS).get("e1") == "34.888206"
    size = detail.find("hp:curSz", NS)
    assert abs(int(size.get("width"))*6 - int(size.get("height"))*7) <= 3.5
    output = tmp_path / "source-preserving-detail.hwpx"
    record = doc.save(output)
    assert record["package_validation"]["valid"] and not record["native_verified"]
    metadata = record["inserted_picture_metadata"][-1]
    assert metadata["viewport_pixels_ltrb"] == [6, 3, 13, 9]
    assert metadata["whole_embedded_raster_preserved"] is True
    with ZipFile(output) as archive:
        opf = parse_xml(archive.read("Contents/content.hpf"))
        for picture in [original, detail]:
            bid = picture.find("hc:img", NS).get("binaryItemIDRef")
            item = next(item for item in opf.iter() if local(item) == "item" and item.get("id") == bid)
            embedded = archive.read(item.get("href"))
            assert embedded == raw
            with Image.open(BytesIO(embedded)) as image:
                assert image.size == (13, 9)
                assert image.getpixel((0, 0)) == (255, 0, 0)
                assert image.getpixel((12, 8)) == (0, 0, 255)
    assert source.read_bytes() == original_source


@pytest.mark.parametrize("box,profile", [
    ([0, 0, 5, 4], None),
    ([0, 0, 13, 9], HANCOM_MAC_12_30_PNG_METADATA),
    ([0, 0, 14, 9], HANCOM_MAC_12_30_PNG_METADATA),
    ([0, 0, 13, 10], HANCOM_MAC_12_30_PNG_METADATA),
    ([3, 2, 3, 7], HANCOM_MAC_12_30_PNG_METADATA),
    ([-1, 2, 10, 7], HANCOM_MAC_12_30_PNG_METADATA),
    ([True, 2, 10, 7], HANCOM_MAC_12_30_PNG_METADATA),
    ([1.0, 2, 10, 7], HANCOM_MAC_12_30_PNG_METADATA),
    ([1, 2, 10], HANCOM_MAC_12_30_PNG_METADATA),
    ("1,2,10,7", HANCOM_MAC_12_30_PNG_METADATA),
])
def test_invalid_pixel_viewport_does_not_allocate_objects_or_touch_source(source_document, box, profile):
    source, doc = source_document
    paragraph = doc.paragraphs()[0]
    before = ([ET.tostring(doc.xml(name)) for name in doc._roots],
              dict(doc._new_entries), doc._next_id, list(doc._inserted_picture_metadata), source.read_bytes())
    with pytest.raises(ComposeError, match="viewport|whole-image"):
        doc.insert_picture(paragraph, raster((13, 9)), "image/png", "png", width_mm=120,
            viewport_pixels=box, raster_metadata_profile=profile)
    after = ([ET.tostring(doc.xml(name)) for name in doc._roots],
             dict(doc._new_entries), doc._next_id, list(doc._inserted_picture_metadata), source.read_bytes())
    assert after == before
