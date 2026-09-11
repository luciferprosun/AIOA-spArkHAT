from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
MANIFEST_PATH = KNOWLEDGE_ROOT / "manifests" / "library_manifest.yaml"
LEGACY_SOURCE = "runtime/knowledge/source/RHCSA_Command_Library (1).pdf"


@dataclass(frozen=True)
class Provenance:
    source_file: str
    source_page: int | None
    canonical_source: str
    confidence_score: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_file": self.source_file,
            "source_page": self.source_page,
            "canonical_source": self.canonical_source,
            "confidence_score": self.confidence_score,
        }


def _manifest_value(key: str, knowledge_root: Path | None = None) -> str | None:
    path = MANIFEST_PATH if knowledge_root is None else knowledge_root / "manifests/library_manifest.yaml"
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{key}:"):
                return line.split(":", 1)[1].strip()
    except OSError:
        return None
    return None


@lru_cache(maxsize=16)
def canonical_source(knowledge_root: Path | None = None) -> str:
    fallback = LEGACY_SOURCE if knowledge_root is None or knowledge_root == KNOWLEDGE_ROOT else "UNSPECIFIED_LOCAL_SOURCE"
    return _manifest_value("canonical_source", knowledge_root) or fallback


@lru_cache(maxsize=16)
def section_source_map(knowledge_root: Path | None = None) -> dict[str, str]:
    path = (knowledge_root if knowledge_root is not None else KNOWLEDGE_ROOT) / "canonical" / "rhcsa_commands.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    mapping: dict[str, str] = {}
    if not isinstance(payload, list):
        return mapping
    for item in payload:
        if not isinstance(item, dict):
            continue
        command = str(item.get("command", "")).strip()
        source_section = str(item.get("source_section", "")).strip()
        if command and source_section:
            mapping[command] = source_section
    return mapping


def attach_provenance(result: dict[str, Any], confidence_score: int, *, knowledge_root: Path | None = None) -> dict[str, Any]:
    source_file = (
        result.get("source_file")
        or result.get("file_location")
        or result.get("source")
        or "runtime/knowledge/canonical/rhcsa_commands.json"
    )
    enriched = dict(result)
    enriched["provenance"] = Provenance(
        source_file=str(source_file),
        source_page=_coerce_page(result.get("source_page")),
        canonical_source=canonical_source(knowledge_root),
        confidence_score=confidence_score,
    ).to_dict()
    return enriched


def _coerce_page(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None
