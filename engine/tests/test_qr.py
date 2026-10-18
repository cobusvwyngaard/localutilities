"""image.qr: the generated codes are decoded again (zxing-cpp) to prove they scan to the address."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pypdfium2 as pdfium
import pytest
import zxingcpp
from PIL import Image
from starlette.testclient import TestClient

from tests.conftest import run_job
from werkbank_engine.config import Settings
from werkbank_engine.tools.image_qr import base_name

URL = "https://www.sun.ac.za/english/Pages/default.aspx?lang=af&x=1#top"


def decode(image: Image.Image) -> list[str]:
    return [result.text for result in zxingcpp.read_barcodes(image)]


def test_file_names() -> None:
    assert base_name("https://example.com") == "QR example.com"
    assert base_name("https://example.com/docs/page/") == "QR example.com-docs-page"
    assert base_name("http://a.test/x?y=1") == "QR a.test-x"


def test_png_scans_to_the_address(real_client: TestClient, settings: Settings) -> None:
    job = run_job(real_client, "image.qr", [{"url": URL}], {"size": 600})
    assert job["status"] == "done", job
    assert [o["name"] for o in job["outputs"]] == ["QR www.sun.ac.za-english-Pages-default.aspx.png"]
    assert "error correction" in job["notes"][0]  # medium, or higher when it fits for free
    with Image.open(settings.outbox / job["outputs"][0]["name"]) as image:
        assert abs(image.width - 600) <= 40 and image.width == image.height
        assert decode(image) == [URL]


def test_all_formats(real_client: TestClient, settings: Settings) -> None:
    job = run_job(real_client, "image.qr", [{"url": "https://example.com/"}], {"format": "all"})
    assert job["status"] == "done", job
    names = sorted(o["name"] for o in job["outputs"])
    assert names == ["QR example.com.pdf", "QR example.com.png", "QR example.com.svg"]
    assert "vector" in job["notes"][0]

    svg = ET.parse(settings.outbox / "QR example.com.svg").getroot()  # noqa: S314 - our own output
    assert svg.tag.endswith("svg") and svg.find("{http://www.w3.org/2000/svg}path") is not None

    doc = pdfium.PdfDocument(settings.outbox / "QR example.com.pdf")
    image = doc[0].render(scale=4).to_pil()
    doc.close()
    assert decode(image) == ["https://example.com/"]


@pytest.mark.parametrize("level", ["l", "m", "q", "h"])
def test_error_levels(real_client: TestClient, settings: Settings, level: str) -> None:
    job = run_job(real_client, "image.qr", [{"url": "https://example.com/a"}], {"errorCorrection": level})
    assert job["status"] == "done", job
    with Image.open(settings.outbox / job["outputs"][0]["name"]) as image:
        assert decode(image) == ["https://example.com/a"]


def test_too_long_for_high_correction(real_client: TestClient) -> None:
    url = "https://example.com/?q=" + "x" * 1900
    job = run_job(real_client, "image.qr", [{"url": url}], {"errorCorrection": "h"})
    assert job["status"] == "failed" and "too long" in job["error"]


def test_only_web_addresses(real_client: TestClient) -> None:
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "not a url"):
        r = real_client.post("/api/jobs", json={"tool": "image.qr", "inputs": [{"url": bad}]})
        assert r.status_code == 400, (bad, r.text)
