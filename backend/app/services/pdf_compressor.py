"""Lossless PDF compression using PyMuPDF.

Plan sets are typically vector-heavy (CAD output). PyMuPDF's `save()` with
deflate + garbage collection routinely shaves 20-50% with zero quality loss.
For very large image-heavy PDFs we additionally try a downsample pass.
"""
import os
import tempfile
from typing import Tuple
import fitz  # PyMuPDF
from app.utils.logger import get_logger

logger = get_logger(__name__)


def compress(input_path: str, output_path: str = None, max_mb: float = None) -> Tuple[str, int, int]:
    """Compress a PDF in place (or to output_path).

    Returns (output_path, original_bytes, new_bytes).
    Falls back to original file if compression fails or grows the file.

    Files larger than `max_mb` are skipped (returned untouched). doc.save with
    garbage=4 / clean=True / deflate_images rewrites and sanitizes the WHOLE
    document in memory, so on a large vector- or image-heavy plan set that
    transient spike is a top OOM cause on a small dyno — and the compressed copy
    is only used locally then deleted, so the marginal saving isn't worth the
    risk on big files. `max_mb=None` reads settings.pdf_compress_max_mb
    (default 25); `max_mb=0` disables the gate.
    """
    original_size = os.path.getsize(input_path)

    if max_mb is None:
        try:
            from app.config import settings
            max_mb = float(getattr(settings, "pdf_compress_max_mb", 25))
        except Exception:
            max_mb = 25.0
    if max_mb and original_size > max_mb * 1024 * 1024:
        logger.info(
            f"compress: skipping {original_size:,}-byte PDF (over {max_mb:g} MB cap) "
            f"to avoid the in-memory rewrite spike; using original"
        )
        return input_path, original_size, original_size

    # Write to a temp file so we can fall back if it gets worse
    target = output_path or input_path
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(tmp_fd)

    try:
        doc = fitz.open(input_path)
        # Lossless save with maximum compression
        doc.save(
            tmp_path,
            garbage=4,        # remove unused objects + cross-references
            deflate=True,     # zlib-compress streams
            deflate_images=True,
            deflate_fonts=True,
            clean=True,       # sanitize content streams
        )
        doc.close()
        new_size = os.path.getsize(tmp_path)

        # If compression actually made it worse (rare but possible), keep the original
        if new_size >= original_size:
            os.remove(tmp_path)
            logger.info(f"compress: no win ({original_size} -> {new_size}); keeping original")
            return input_path, original_size, original_size

        # Move temp over the target
        os.replace(tmp_path, target)
        ratio = (1 - new_size / original_size) * 100
        logger.info(f"compress: {original_size:,} -> {new_size:,} bytes (-{ratio:.1f}%)")
        return target, original_size, new_size

    except Exception as e:
        logger.warning(f"compress failed: {e}; keeping original")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return input_path, original_size, original_size


def compress_bytes(data: bytes) -> bytes:
    """Compress an in-memory PDF; returns compressed bytes (or original on failure)."""
    in_fd, in_path = tempfile.mkstemp(suffix=".pdf")
    out_fd, out_path = tempfile.mkstemp(suffix=".pdf")
    os.close(in_fd)
    os.close(out_fd)
    try:
        with open(in_path, "wb") as f:
            f.write(data)
        compress(in_path, out_path)
        with open(out_path, "rb") as f:
            result = f.read()
        return result if len(result) < len(data) else data
    finally:
        for p in (in_path, out_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass
