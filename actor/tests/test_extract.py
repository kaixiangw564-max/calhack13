"""Offline tests for the Actor's extraction logic (saved dmv.ca.gov fixtures, fetched 2026-10-23)."""
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from src.extract import extract_records, form_from_link
from src.pdf import RobotsGate

FIXTURES = Path(__file__).parent / "fixtures"
DPP_URL = "https://www.dmv.ca.gov/portal/vehicle-registration/license-plates-decals-and-placards/disabled-person-parking-placards-plates/"
REQUIRED_KEYS = {"site", "url", "title", "service", "steps_raw", "required_documents", "forms", "locations", "fees", "crawled_at"}


def records(name: str, url: str) -> list[dict]:
    soup = BeautifulSoup((FIXTURES / name).read_text(encoding="utf-8"), "html.parser")
    return extract_records(soup, url, "2026-10-24T00:00:00Z")


def test_dpp_page_records_match_output_format():
    recs = records("dpp.html", DPP_URL)
    assert len(recs) >= 2
    for rec in recs:
        assert REQUIRED_KEYS <= rec.keys()
        assert rec["site"] == "dmv.ca.gov"
        assert rec["url"] == DPP_URL
        assert rec["steps_raw"]
        for form in rec["forms"]:
            assert {"name", "url", "fields"} <= form.keys()


def test_dpp_page_finds_reg_195_form_and_mailing_address():
    page = records("dpp.html", DPP_URL)[0]
    reg195 = [f for f in page["forms"] if f["number"] == "REG 195"]
    assert reg195, page["forms"]
    assert reg195[0]["url"].startswith("https://www.dmv.ca.gov/portal/file/")
    assert "Disabled Person Placard" in reg195[0]["name"]
    assert any("PO Box 942869" in loc["address"] for loc in page["locations"])
    assert "no additional fee" in page["fees"]


def test_dpp_page_has_action_section_records():
    services = [r["service"] for r in records("dpp.html", DPP_URL)[1:]]
    assert any(s.startswith("Applying for a DP Parking Placard") for s in services)
    assert any("replace" in s.lower() for s in services)


@pytest.mark.parametrize(
    "text,href,number",
    [
        ("Application for Disabled Person Placard or Plates (REG 195) (PDF)",
         "https://www.dmv.ca.gov/portal/file/application-for-disabled-person-placard-or-plates-reg-195-pdf/", "REG 195"),
        ("PDF", "https://www.dmv.ca.gov/portal/file/notice-of-transfer-and-release-of-liability-reg-138-pdf/", "REG 138"),
        ("Planned Non-Operation Certification (REG 102) (PDF)", "https://www.dmv.ca.gov/portal/uploads/2020/03/reg102.pdf", "REG 102"),
    ],
)
def test_form_number_from_text_or_slug(text, href, number):
    form = form_from_link(text, href)
    assert form["number"] == number
    assert form["url"] == href


def test_non_form_link_is_ignored():
    assert form_from_link("DMV office", "https://www.dmv.ca.gov/portal/locations/field-offices/") is None


DMV_ROBOTS = b"""User-agent: *
Disallow: /portal/wp-admin/
Allow: /portal/wp-admin/admin-ajax.php

User-agent: *
Disallow:

Sitemap: https://www.dmv.ca.gov/portal/sitemap_index.xml

User-agent: *
Disallow: /portal/wp-content/uploads/
"""


async def test_robots_gate_blocks_uploads_but_allows_file_links():
    async def fetch(url):
        assert url == "https://www.dmv.ca.gov/robots.txt"
        return 200, DMV_ROBOTS

    gate = RobotsGate(fetch)
    assert await gate.allowed("https://www.dmv.ca.gov/portal/file/application-for-disabled-person-placard-or-plates-reg-195-pdf/")
    assert not await gate.allowed("https://www.dmv.ca.gov/portal/wp-content/uploads/2020/03/reg195.pdf")
