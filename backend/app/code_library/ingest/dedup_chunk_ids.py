#!/usr/bin/env python3
"""Enforce unique chunk_id values in a corpus .jsonl file.

Retrieval dedup and citation in the RAG pipeline key off chunk_id, so every
row must carry a distinct id. This tool:

  1. Enumerates duplicate chunk_ids and the (1-based) line numbers they occur on.
  2. Classifies each duplicate group:
       - identical-text rows  -> TRUE duplicate (safe to remove all but the first)
       - distinct-text rows   -> distinct chunks that must be disambiguated by the
                                 existing "-1/-2" multi-part suffix convention
  3. In --fix mode, rewrites the file so every chunk_id is unique. The edit is
     surgical: only the chunk_id *value* is rewritten; section numbers, text, key
     order, unicode and whitespace are left byte-for-byte intact. A .bak is written.

Usage:
    python dedup_chunk_ids.py PATH            # report only
    python dedup_chunk_ids.py PATH --fix      # report, then apply fixes in place
"""
from __future__ import annotations

import collections
import json
import re
import sys


def load(path):
    rows = []  # (line_no, raw_line_without_newline, obj)
    with open(path, encoding="utf-8") as fh:
        for i, raw in enumerate(fh, 1):
            rows.append((i, raw.rstrip("\n"), json.loads(raw)))
    return rows


def norm(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def groups(rows):
    by_id = collections.defaultdict(list)
    for i, raw, obj in rows:
        by_id[obj["chunk_id"]].append((i, raw, obj))
    return {cid: m for cid, m in by_id.items() if len(m) > 1}


def report(rows):
    dups = groups(rows)
    extra = sum(len(m) - 1 for m in dups.values())
    print(f"Lines: {len(rows)} | duplicate chunk_id groups: {len(dups)} | "
          f"collision rows beyond first: {extra}\n")
    for cid in sorted(dups, key=lambda c: (-len(dups[c]), c)):
        members = dups[cid]
        texts = collections.Counter(norm(o.get("text")) for _, _, o in members)
        kind = "TRUE-DUP(identical text)" if any(c > 1 for c in texts.values()) \
            else "distinct-text -> suffix"
        lines = [i for i, _, _ in members]
        print(f"{cid:24} x{len(members)}  {kind}  lines {lines}")
    return dups


def fix(path, rows):
    dups = groups(rows)
    existing = {o["chunk_id"] for _, _, o in rows}
    # appearance-order counter per duplicated base
    counter = collections.Counter()
    removed = renamed = 0
    out = []
    for i, raw, obj in rows:
        cid = obj["chunk_id"]
        members = dups.get(cid)
        if not members:
            out.append(raw)
            continue
        # TRUE duplicate group (some row shares normalized text): keep first, drop rest
        texts = collections.Counter(norm(o.get("text")) for _, _, o in members)
        if any(c > 1 for c in texts.values()):
            seen = counter[("seen-text", cid)]
            key = norm(obj.get("text"))
            dropped_set = counter.setdefault(("dropped", cid), set())
            if key in dropped_set:
                removed += 1
                continue
            dropped_set.add(key)
            out.append(raw)
            continue
        # distinct-text group: suffix in appearance order, skipping any pre-existing id
        n = counter[cid] + 1
        new = f"{cid}-{n}"
        while new in existing and new != cid:
            n += 1
            new = f"{cid}-{n}"
        counter[cid] = n
        existing.add(new)
        new_raw = raw.replace(f'"chunk_id": "{cid}"', f'"chunk_id": "{new}"', 1)
        assert new_raw != raw, f"replacement failed on line {i}"
        out.append(new_raw)
        renamed += 1

    with open(path + ".bak", "w", encoding="utf-8") as fh:
        for _, raw, _ in rows:
            fh.write(raw + "\n")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out) + "\n")
    print(f"\nApplied: renamed {renamed} rows, removed {removed} rows. "
          f"Backup -> {path}.bak")


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = sys.argv[1]
    do_fix = "--fix" in sys.argv[2:]
    rows = load(path)
    report(rows)
    if do_fix:
        fix(path, rows)


if __name__ == "__main__":
    main()
