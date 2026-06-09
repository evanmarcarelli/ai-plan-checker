"""Schema for structured plan-check correction checklists."""
from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class ChecklistItem(BaseModel):
    """One correction-list line, code-cited."""

    item_id: str                       # e.g. "B3" (as printed on the source list)
    discipline: str                    # human-readable, e.g. "General Construction Requirements"
    discipline_code: str               # slug, e.g. "general_construction"
    text: str                          # the correction text, cleaned
    code_citation: Optional[str] = None  # e.g. "CRC R302.5.1"
    # How the item maps to a department reviewer (matches departments.py codes).
    department_code: Optional[str] = None


class ChecklistSource(BaseModel):
    """Provenance for a whole checklist — required for the citation gate."""

    jurisdiction: str                  # "Orange County, CA"
    authority: str                     # publishing department
    edition: str                       # "2019 CRC"
    occupancy: str                     # "R-3"
    doc_title: str
    url: str
    retrieved: str                     # ISO date the list was ingested


class Checklist(BaseModel):
    """A full standard correction list for one (jurisdiction, edition, occupancy)."""

    id: str                            # "oc_2019_crc_r3"
    source: ChecklistSource
    items: List[ChecklistItem] = Field(default_factory=list)

    def by_department(self, department_code: str) -> List[ChecklistItem]:
        return [i for i in self.items if i.department_code == department_code]
