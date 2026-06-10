"""Run manifest — stamp every benchmark run with exactly what produced it.

A metric is meaningless without knowing the code, model, and corpus that made
it. This binds each run to a git SHA, the model ids, and a hash of the corpus
content, so a number in `results/` is always reproducible and regressions are
attributable. (BENCHMARK_DESIGN §7.)
"""
from __future__ import annotations

import hashlib
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parent.parent


def _git(args: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(ROOT), *args],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except Exception:
        return ""


def git_sha() -> str:
    return _git(["rev-parse", "--short", "HEAD"]) or "unknown"


def git_dirty() -> bool:
    return bool(_git(["status", "--porcelain"]))


def corpus_sha() -> str:
    """Stable 16-char hash of the JSONL corpus content, so a metric is tied to
    the exact corpus that produced it. 'unknown' if it can't be read."""
    try:
        from app.code_library.corpus_loader import CORPUS_DIR
        h = hashlib.sha256()
        for fp in sorted(Path(CORPUS_DIR).glob("*.jsonl")):
            h.update(fp.read_bytes())
        return h.hexdigest()[:16]
    except Exception:
        return "unknown"


def model_ids() -> Dict[str, str]:
    try:
        from app.config import settings
        return {
            "primary": getattr(settings, "anthropic_model", ""),
            "cheap": getattr(settings, "anthropic_model_cheap", ""),
            "code_store": getattr(settings, "code_store", "disk"),
        }
    except Exception:
        return {}


def corpus_source() -> str:
    """What the corpus was ACTUALLY loaded from this run ('disk'/'postgres'),
    or the configured intent if it hasn't loaded yet. NOTE: corpus_sha hashes
    the on-disk JSONL — in 'postgres' mode the DB is authoritative, so that hash
    is not the served corpus."""
    try:
        from app.code_library.corpus_loader import get_corpus_source
        from app.config import settings
        return get_corpus_source() or getattr(settings, "code_store", "disk")
    except Exception:
        return "unknown"


def build_manifest(mode: str, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Assemble the run manifest. `now` is injectable for deterministic tests."""
    ts = now or datetime.utcnow()
    return {
        "run_id": ts.strftime("%Y%m%dT%H%M%SZ"),
        "timestamp": ts.isoformat() + "Z",
        "mode": mode,
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "corpus_sha": corpus_sha(),          # hash of the on-disk JSONL
        "corpus_source": corpus_source(),    # what actually served the findings
        "models": model_ids(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
    }
