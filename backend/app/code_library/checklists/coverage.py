"""Coverage report for the ingested correction checklists.

    python -m app.code_library.checklists.coverage

Shows, per checklist, how many correction items exist by department and what
share carry an explicit code citation. This is the quick read on whether the
corpus is deep enough to rival a real plan check, and the first half of the
golden-set validation (the LLM half — how many actually surface on a labeled
plan — needs an API key and lives in the eval harness).
"""
from __future__ import annotations

import collections

from app.code_library.checklists.loader import load_checklists


def main() -> None:
    lists = load_checklists()
    if not lists:
        print("No checklists ingested yet. Run build_from_pdf on a correction list.")
        return
    grand = 0
    for cl in lists:
        by_dept = collections.Counter(i.department_code for i in cl.items)
        cited = sum(1 for i in cl.items if i.code_citation)
        n = len(cl.items)
        grand += n
        print(f"\n{cl.id}  ({cl.source.jurisdiction}, {cl.source.edition}, {cl.source.occupancy})")
        print(f"  {n} items · {cited}/{n} code-cited ({cited * 100 // max(n, 1)}%)")
        for dept, c in by_dept.most_common():
            print(f"    {dept:<18} {c}")
    print(f"\nTOTAL correction items across {len(lists)} checklist(s): {grand}")


if __name__ == "__main__":
    main()
