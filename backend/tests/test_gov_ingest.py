"""Offline tests for the government-source ingesters (ca_leginfo, ada_gov).

Fixtures mirror the live page anatomy captured 2026-06-11:
  - leginfo: <h6><b>51182.  </b></h6> + sibling <p> paragraphs in a <div>
  - ada.gov: <p><strong>404.2.3 Clear Width.</strong> body</p> provisions,
    <h3 id="...">603 Toilet and Bathing Rooms</h3> parent headings, and
    EXCEPTION paragraphs attached to the preceding provision.
"""
from app.code_library.ingest.ada_gov import parse_ada_html
from app.code_library.ingest.ca_leginfo import parse_section_html


# ── ca_leginfo ───────────────────────────────────────────────────────

LEGINFO_HTML = """
<html><body>
<div style="clear:both;"></div>
<div><font face="Times New Roman">
<h6 style="float:left;"><b>51182.  </b></h6>
<p style="margin:0;">(a) A person who owns an occupied dwelling within a very
high fire hazard severity zone shall maintain defensible space of 100 feet
from each side of the structure.</p>
<p style="margin:0;">(b) A greater distance may be required by state law.</p>
</font></div>
</body></html>
"""


def test_leginfo_parses_section_body():
    text = parse_section_html(LEGINFO_HTML, "51182")
    assert text is not None
    assert "defensible space of 100 feet" in text
    assert "(b) A greater distance" in text


def test_leginfo_returns_none_for_wrong_section():
    assert parse_section_html(LEGINFO_HTML, "9999") is None


def test_leginfo_returns_none_for_empty_page():
    assert parse_section_html("<html><body></body></html>", "51182") is None


# ── ada_gov ──────────────────────────────────────────────────────────

ADA_HTML = """
<html><body>
<h2>Chapter 4: Accessible Routes</h2>
<p><strong>402 Accessible Routes.</strong></p>
<p><strong>404.2.3 Clear Width.</strong> Door openings shall provide a clear
width of 32 inches (815 mm) minimum.</p>
<p><strong>EXCEPTION:</strong> Door openings to hospital patient rooms shall
provide a clear width of 41 1/2 inches.</p>
<h3 id="603-toilet-and-bathing-rooms">603 Toilet and Bathing Rooms</h3>
<p><strong>603.1 General.</strong> Toilet and bathing rooms shall comply
with 603.</p>
<p>For more information see <strong>404</strong> which is referenced
mid-paragraph and must not start a new section.</p>
</body></html>
"""


def test_ada_parses_numbered_provisions_with_chapter_breadcrumb():
    sections = parse_ada_html(ADA_HTML)
    by_num = {s.section_number: s for s in sections}
    assert "404.2.3" in by_num
    s = by_num["404.2.3"]
    assert s.title == "Clear Width"
    assert "32 inches" in s.text
    assert s.breadcrumb == ["2010 ADA Standards", "Chapter 4 Accessible Routes"]


def test_ada_exception_attaches_to_parent_provision():
    sections = parse_ada_html(ADA_HTML)
    s = next(x for x in sections if x.section_number == "404.2.3")
    assert "hospital patient rooms" in s.text


def test_ada_heading_level_parent_sections_are_citable():
    sections = parse_ada_html(ADA_HTML)
    by_num = {s.section_number: s for s in sections}
    # <h3> parent section becomes a citable stub.
    assert "603" in by_num
    assert by_num["603"].title == "Toilet and Bathing Rooms"
    # <p><strong> with empty body also kept as a stub.
    assert "402" in by_num


def test_ada_midparagraph_bold_does_not_start_section():
    sections = parse_ada_html(ADA_HTML)
    nums = {s.section_number for s in sections}
    assert "404" not in nums  # the mid-paragraph cross-ref
    # ...and its text attaches to the open section (603.1).
    s = next(x for x in sections if x.section_number == "603.1")
    assert "mid-paragraph" in s.text


def test_ada_max_sections_cap():
    assert len(parse_ada_html(ADA_HTML, max_sections=2)) <= 3  # cap + final flush


# ── writer shrink guard ──────────────────────────────────────────────


def test_writer_refuses_large_shrink(tmp_path, monkeypatch):
    import app.code_library.ingest.writer as writer_mod
    from app.code_library.ingest.base import IngestTarget
    from app.code_library.ingest.writer import write_jsonl

    monkeypatch.setattr(writer_mod, "CORPUS_DIR", tmp_path)
    monkeypatch.delenv("INGEST_ALLOW_SHRINK", raising=False)
    target = IngestTarget(
        code_short="X", code_name="X", version="1",
        jurisdictions=["*"], output_filename="x.jsonl",
    )
    big = [{"chunk_id": f"x-{i}", "text": "t"} for i in range(100)]
    write_jsonl(target, big)
    # A capped re-run (10 chunks vs 100) must NOT clobber the bigger file...
    write_jsonl(target, big[:10])
    lines = (tmp_path / "x.jsonl").read_text().strip().splitlines()
    assert len(lines) == 100
    # ...unless the operator opts in explicitly.
    monkeypatch.setenv("INGEST_ALLOW_SHRINK", "1")
    write_jsonl(target, big[:10])
    lines = (tmp_path / "x.jsonl").read_text().strip().splitlines()
    assert len(lines) == 10
