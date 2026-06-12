"""Common contract every per-source ingester implements.

A concrete ingester (amlegal, municode, ecode360, ca_state, etc.) walks its
particular site, yields normalized RawSection objects, and the shared
chunker/writer takes care of category classification and JSONL output.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, List, Optional


@dataclass
class RawSection:
    """One scraped section before classification/chunking.

    Keep this dumb on purpose: the scraper only needs to populate what it
    physically read from the site. Category mapping, citation normalization,
    tag extraction, and JSONL serialization all happen downstream so each
    scraper stays small.
    """
    # Logical hierarchy: e.g. ["Title 17 Zoning", "Chapter 17.32 Hillside", "17.32.040"]
    breadcrumb: List[str]
    section_number: str           # "17.32.040" or "R301.2" etc
    title: str                    # human-readable section title
    text: str                     # full body text, stripped of HTML
    source_url: str = ""          # for traceability / debugging
    extra_tags: List[str] = None  # optional additional keywords


@dataclass
class IngestTarget:
    """Where the chunks land. Built from CLI args + jurisdictions.yaml."""
    code_short: str               # e.g. "PASADENA-MC"
    code_name: str                # e.g. "Pasadena Municipal Code"
    version: str                  # e.g. "2024-06"
    jurisdictions: List[str]      # e.g. ["CA:Pasadena"]
    output_filename: str          # e.g. "amlegal_pasadena_ca.jsonl"
    # When the whole source has one known discipline (the ADA standard is
    # accessibility, full stop), force it instead of keyword-classifying each
    # section — body sampling routed 184 ADA chunks to plumbing/fire/electrical
    # reviewers because their keywords are checked first.
    force_category: Optional[str] = None


class BaseIngester(ABC):
    """ABC for source-specific scrapers."""

    name: str = "base"

    @abstractmethod
    def fetch_sections(self, target: IngestTarget) -> Iterable[RawSection]:
        """Yield every section in the target jurisdiction's code book.
        Implementations should be polite (rate-limit, identify themselves
        via User-Agent, respect robots.txt)."""

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.name!r}>"
