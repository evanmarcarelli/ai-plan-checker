"""Tests for the LA-County ingesters (municode, qcode, ecode360) and the
CLI's LA-County dispatch + filtering.

Pure-Python, no live network. Fixture HTML mirrors each publisher's current
page shape closely enough to catch parser regressions.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.code_library.ingest.base import IngestTarget


def _target(code_short: str = "TEST-MC", code_name: str = "Test Code") -> IngestTarget:
    return IngestTarget(
        code_short=code_short,
        code_name=code_name,
        version="2024",
        jurisdictions=["CA:Testville"],
        output_filename="test_testville.jsonl",
    )


# ─────────────────────────────────────────────────────────────────────────
# municode
# ─────────────────────────────────────────────────────────────────────────


MUNICODE_LEAF_HTML = """\
<!doctype html>
<html><body>
  <header><h1>Sec. 12.21 General Provisions</h1></header>
  <div id="codeContent">
    <p>No building or structure shall be erected, reconstructed, structurally
    altered, enlarged, moved or maintained except in conformity with the
    regulations of this article.</p>
    <p>Yards and other open spaces around buildings shall not be reduced
    below the requirements of this chapter.</p>
  </div>
</body></html>
"""

MUNICODE_TOC_HTML = """\
<!doctype html>
<html><body>
  <nav>
    <ul>
      <li><a data-nodeid="t12" href="/ca/losangeles/codes/code_of_ordinances?nodeId=t12">Chapter 12 Zoning</a>
        <ul>
          <li><a data-nodeid="s1221" href="/ca/losangeles/codes/code_of_ordinances?nodeId=s1221">Sec. 12.21 General Provisions</a></li>
          <li><a data-nodeid="s1222" href="/ca/losangeles/codes/code_of_ordinances?nodeId=s1222">Sec. 12.22 R1 District</a></li>
        </ul>
      </li>
    </ul>
  </nav>
</body></html>
"""


def test_municode_parse_leaf_extracts_section_and_text():
    from app.code_library.ingest.municode import MunicodeIngester

    ing = MunicodeIngester(slug="losangeles_ca")
    breadcrumb = ["Chapter 12 Zoning", "Sec. 12.21 General Provisions"]
    sect = ing._parse_leaf(MUNICODE_LEAF_HTML, "http://example.test/.../s1221", breadcrumb)
    assert sect is not None
    assert sect.section_number == "12.21"
    assert "General Provisions" in sect.title
    assert "no building or structure" in sect.text.lower()


def test_municode_walks_toc_and_yields_leaves():
    from app.code_library.ingest.municode import MunicodeIngester

    root = "https://library.municode.com/ca/losangeles_ca/codes/code_of_ordinances"
    pages = {
        root: MUNICODE_TOC_HTML,
        "https://library.municode.com/ca/losangeles/codes/code_of_ordinances?nodeId=t12": MUNICODE_TOC_HTML,
        "https://library.municode.com/ca/losangeles/codes/code_of_ordinances?nodeId=s1221": MUNICODE_LEAF_HTML,
        "https://library.municode.com/ca/losangeles/codes/code_of_ordinances?nodeId=s1222":
            MUNICODE_LEAF_HTML
            .replace("Sec. 12.21 General Provisions", "Sec. 12.22 R1 District")
            .replace("No building or structure", "In the R1 zone, only one-family dwellings"),
    }

    def fake_get(self, url):
        if url not in pages:
            raise RuntimeError(f"unmocked URL: {url}")
        return pages[url]

    with patch.object(MunicodeIngester, "_get", new=fake_get):
        ing = MunicodeIngester(slug="losangeles_ca", delay_sec=0)
        sects = list(ing.fetch_sections(_target("LAMC", "Los Angeles Municipal Code")))

    section_numbers = [s.section_number for s in sects]
    assert "12.21" in section_numbers
    assert "12.22" in section_numbers


def test_municode_cloudflare_challenge_surfaces_clear_error():
    """A bot-challenge must raise a recognizable RuntimeError, not pass through
    as a silent 403."""
    from app.code_library.ingest.municode import MunicodeIngester

    class FakeResp:
        status_code = 403
        headers = {"cf-mitigated": "challenge"}

        def raise_for_status(self):
            raise RuntimeError("should not be reached")

    class FakeClient:
        def get(self, url):
            return FakeResp()

    ing = MunicodeIngester(slug="losangeles_ca", delay_sec=0, client=FakeClient())
    with pytest.raises(RuntimeError, match="Cloudflare bot-challenge"):
        ing._get("https://library.municode.com/ca/losangeles_ca/codes/code_of_ordinances")


# ─────────────────────────────────────────────────────────────────────────
# qcode
# ─────────────────────────────────────────────────────────────────────────


QCODE_CHAPTER_HTML = """\
<!doctype html>
<html><body>
  <div id="main">
    <h2>Chapter 17.04 Definitions</h2>
    <p>17.04.010 Purpose.
    The purpose of this title is to promote and protect the public health,
    safety, and welfare.</p>
    <p>17.04.020 Definitions.
    For purposes of this title, the following words and phrases have the
    meanings ascribed to them in this section.</p>
  </div>
</body></html>
"""

QCODE_INDEX_HTML = """\
<!doctype html>
<html><body>
  <ul>
    <li><a href="view.php?topic=17_04">Chapter 17.04 Definitions</a></li>
    <li><a href="view.php?topic=17_06">Chapter 17.06 Districts</a></li>
  </ul>
</body></html>
"""


def test_qcode_extracts_chapters_from_index():
    from app.code_library.ingest.qcode import QcodeIngester

    ing = QcodeIngester(slug="hermosabeach")
    chapters = ing._extract_chapter_urls(
        QCODE_INDEX_HTML, "https://qcode.us/codes/hermosabeach/"
    )
    assert len(chapters) >= 2
    # showAll forced on each chapter URL
    assert all("showAll=1" in url for url, _ in chapters)


def test_qcode_parses_chapter_into_sections():
    from app.code_library.ingest.qcode import QcodeIngester

    ing = QcodeIngester(slug="hermosabeach")
    sects = list(
        ing._parse_chapter(
            QCODE_CHAPTER_HTML,
            "https://qcode.us/codes/hermosabeach/view.php?topic=17_04&showAll=1",
            ["Title 17", "Chapter 17.04 Definitions"],
        )
    )
    section_numbers = [s.section_number for s in sects]
    assert "17.04.010" in section_numbers
    assert "17.04.020" in section_numbers


# ─────────────────────────────────────────────────────────────────────────
# ecode360
# ─────────────────────────────────────────────────────────────────────────


ECODE_LEAF_HTML = """\
<!doctype html>
<html><body>
  <article>
    <header><h2>§ 200-15 Setback requirements</h2></header>
    <div class="section-content">
      <p>The minimum side-yard setback in the R-1 district shall be ten (10) feet.</p>
    </div>
  </article>
</body></html>
"""


def test_ecode360_parse_leaf():
    from app.code_library.ingest.ecode360 import Ecode360Ingester

    ing = Ecode360Ingester(slug="EXAMPLE")
    breadcrumb = ["Chapter 200 Zoning", "§ 200-15 Setback requirements"]
    sect = ing._parse_leaf(ECODE_LEAF_HTML, "https://ecode360.com/EXAMPLE/123", breadcrumb)
    assert sect is not None
    assert sect.section_number == "200-15"
    assert "ten (10) feet" in sect.text


# ─────────────────────────────────────────────────────────────────────────
# LA-County CLI filter
# ─────────────────────────────────────────────────────────────────────────


def test_la_county_filter_recognizes_la_jurisdictions():
    from app.code_library.ingest.__main__ import _entry_is_la_county

    assert _entry_is_la_county({"jurisdictions": ["CA:Los Angeles"]})
    assert _entry_is_la_county({"jurisdictions": ["CA:Pasadena"]})
    assert _entry_is_la_county({"jurisdictions": ["CA:Beverly Hills"]})
    assert _entry_is_la_county({"jurisdictions": ["CA:Hermosa Beach"]})
    assert _entry_is_la_county({"jurisdictions": ["CA:LA County Unincorporated"]})


def test_la_county_filter_excludes_non_la_jurisdictions():
    from app.code_library.ingest.__main__ import _entry_is_la_county

    assert not _entry_is_la_county({"jurisdictions": ["CA:San Francisco"]})
    assert not _entry_is_la_county({"jurisdictions": ["CA:San Diego"]})
    assert not _entry_is_la_county({"jurisdictions": ["CA:Sacramento"]})
    assert not _entry_is_la_county({"jurisdictions": ["CA"]})
    assert not _entry_is_la_county({"jurisdictions": []})


def test_loaded_yaml_contains_la_targets_per_publisher():
    """Smoke test: the yaml ships with non-zero LA County coverage on the
    publishers we expect (amlegal, municode, qcode). Catches accidental
    regressions where a yaml edit drops an LA city."""
    from app.code_library.ingest.__main__ import _entry_is_la_county, _load_targets

    for publisher in ("amlegal", "municode", "qcode"):
        entries = _load_targets(publisher)
        la_count = sum(1 for e in entries if _entry_is_la_county(e))
        assert la_count >= 1, f"{publisher} has zero LA County entries"
