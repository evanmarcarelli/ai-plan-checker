"""Tests for the government-source auto-fetch registry: registry integrity,
the download_pdf validation/caching path (no network), and dispatch."""
import pytest

from app.code_library.ingest import gov_sources as gs


def test_registry_keys_unique_and_well_formed():
    keys = [s.key for s in gs.REGISTRY]
    assert len(keys) == len(set(keys)), "duplicate registry keys"
    for s in gs.REGISTRY:
        assert s.strategy in ("download_pdf", "self_fetch")
        assert s.license in ("public_domain", "edict")
        if s.strategy == "download_pdf":
            assert s.url and s.url.startswith("https://"), f"{s.key} needs an https url"
            assert s.filename, f"{s.key} needs a cache filename"
        assert callable(s.ingest)


def test_no_licensed_codes_in_free_registry():
    # The free registry must never list an ICC/IAPMO model code — those are
    # licensed-only. Guard against someone adding e.g. a CBC download URL.
    free_names = " ".join(s.name.lower() for s in gs.REGISTRY)
    for token in ("california building code", "residential code",
                  "plumbing code", "mechanical code", "fire code",
                  "existing building code"):
        assert token not in free_names, f"licensed code {token!r} leaked into free registry"


def test_known_licensed_lists_the_paywalled_codes():
    shorts = {row[0] for row in gs.KNOWN_LICENSED}
    assert {"CBC", "CRC", "CEBC", "CPC", "CMC"} <= shorts


def test_get_source_and_unknown_key():
    assert gs.get_source("energy-code").scope == "CA"
    assert gs.get_source("nope") is None
    with pytest.raises(KeyError):
        gs.fetch_and_ingest("nope")


def test_download_pdf_rejects_non_pdf(tmp_path, monkeypatch):
    """An HTML 404 page (or any non-PDF body) must raise, not get cached."""
    class _Resp:
        status_code = 200
        headers = {"content-type": "text/html; charset=utf-8"}
        content = b"<html>404 Not Found</html>"
        def raise_for_status(self): pass

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(gs.httpx, "Client", _Client)
    dest = tmp_path / "x.pdf"
    with pytest.raises(ValueError, match="did not return a PDF"):
        gs._download_pdf("https://example.gov/missing.pdf", dest)
    assert not dest.exists()


def test_download_pdf_uses_valid_cache(tmp_path, monkeypatch):
    """A cached, valid PDF is reused without any network call."""
    dest = tmp_path / "cached.pdf"
    dest.write_bytes(b"%PDF-1.7\n" + b"x" * 20_000)

    def _boom(*a, **k):
        raise AssertionError("must not hit the network when cache is valid")

    monkeypatch.setattr(gs.httpx, "Client", _boom)
    out = gs._download_pdf("https://example.gov/whatever.pdf", dest)
    assert out == dest


def test_download_pdf_redownloads_truncated_cache(tmp_path, monkeypatch):
    """A too-small/garbage cache file is not trusted; it re-downloads."""
    dest = tmp_path / "stub.pdf"
    dest.write_bytes(b"oops")  # < 10KB and not %PDF

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/pdf"}
        content = b"%PDF-1.7\n" + b"y" * 20_000
        def raise_for_status(self): pass

    class _Client:
        def __init__(self, *a, **k): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def get(self, url): return _Resp()

    monkeypatch.setattr(gs.httpx, "Client", _Client)
    out = gs._download_pdf("https://example.gov/stub.pdf", dest)
    assert out.read_bytes()[:5] == b"%PDF-"
