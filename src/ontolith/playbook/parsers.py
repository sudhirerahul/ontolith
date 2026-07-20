"""
Playbook ingestion — extracts plain text from retailer playbooks (PDF/txt/md) and
structured rows from product catalogs (JSON/CSV).

PDF extraction is best-effort: some environments have a broken pypdf/cryptography
native dependency chain that raises errors which don't even subclass Exception
(observed: pyo3 PanicException from the `cryptography` backend). We guard with
`except BaseException` and degrade to a plain-text read of the same path so the
whole pipeline never hard-fails on a bad PDF toolchain — matching this project's
"always runnable" convention (see llm/client.py's deterministic fallback).
"""
from __future__ import annotations
import csv
import io
import json
from pathlib import Path
from typing import Any


def ingest_playbook(path: Path | str) -> str:
    """Extract plain text from a retailer playbook file (.pdf/.txt/.md)."""
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        text = _extract_pdf_text(path)
        if text:
            return text
        # Fall through to raw read as a last resort (e.g. text-in-PDF-clothing demo files)
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf_text(path: Path) -> str | None:
    try:
        import pypdf  # lazy import — see module docstring
    except BaseException:
        return None

    try:
        reader = pypdf.PdfReader(str(path))
        pages = [page.extract_text() or "" for page in reader.pages]
        return "\n".join(pages).strip() or None
    except BaseException:
        return None


def ingest_catalog(path: Path | str) -> list[dict[str, Any]]:
    """Load a product catalog from .json or .csv into a list of dicts."""
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("products") or data.get("items") or []
        return data if isinstance(data, list) else []
    if path.suffix.lower() == ".csv":
        with open(path, "r", encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))
    return []


def extract_headings(playbook_text: str) -> list[str]:
    """
    Pull a rough product/topic hierarchy out of numbered/ALL-CAPS section headings.
    Used when the caller doesn't supply an explicit product hierarchy.
    """
    headings: list[str] = []
    for raw_line in playbook_text.splitlines():
        line = raw_line.strip()
        if not line or len(line) > 60:
            continue
        stripped = line.lstrip("0123456789. ").strip()
        looks_like_heading = (
            stripped
            and (line[0].isdigit() or (stripped.isupper() and len(stripped.split()) <= 6))
            and not stripped.endswith((".", ","))
        )
        if looks_like_heading and stripped.upper() not in ("BRAND VOICE",):
            headings.append(stripped.title())
    # Dedupe, preserve order
    seen: set[str] = set()
    unique = []
    for h in headings:
        if h not in seen:
            seen.add(h)
            unique.append(h)
    return unique
