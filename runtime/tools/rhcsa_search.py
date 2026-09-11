#!/usr/bin/env python3
from __future__ import annotations

"""INTERNAL LOW-LEVEL SEARCH API.

Do not call directly from coordinators, routers, kernels, or runtime paths.
Use runtime.retrieval.facade instead.
"""

import argparse
import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from retrieval.linux.scoring import (
    EXAMPLE_EXACT_MATCH_SCORE,
    EXAMPLE_TAG_MATCH_SCORE,
    EXACT_MATCH_SCORE,
    GREP_MATCH_UNIT_SCORE,
    TAG_MATCH_SCORE,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
TOPIC_DIRECTORIES = (
    "filesystem",
    "networking",
    "users",
    "permissions",
    "selinux",
    "systemd",
    "storage",
    "lvm",
    "podman",
    "bash",
    "troubleshooting",
)


@dataclass(frozen=True)
class KnowledgeModule:
    title: str
    topic: str
    source_section: str
    file_path: Path
    tags: tuple[str, ...]
    summary: str
    commands: tuple[str, ...]
    examples: tuple[str, ...]
    content: str


@dataclass(frozen=True)
class ExampleEntry:
    entry_id: str
    command: str
    category: str
    tags: tuple[str, ...]
    risk: str
    notes: str
    related_commands: tuple[str, ...]
    examples: tuple[str, ...]
    file_path: Path


def detect_rhcsa_library() -> Path:
    """Return the deterministic local RHCSA knowledge root."""
    return KNOWLEDGE_ROOT


def _normalize_text(value: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", " ", normalized).strip()


def _tokenize(value: str) -> list[str]:
    return [token for token in _normalize_text(value).split() if token]


def _normalized_command(value: str) -> str:
    return " ".join(value.strip().split())


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    raw_frontmatter = parts[1]
    body = parts[2].lstrip("\n")
    payload: dict[str, str] = {}
    for line in raw_frontmatter.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = value.strip()
    return payload, body


def _parse_tags(raw: str) -> tuple[str, ...]:
    text = raw.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]
    return tuple(tag.strip() for tag in text.split(",") if tag.strip())


def _extract_section(body: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)"
    match = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def _extract_summary(body: str) -> str:
    match = re.search(r"^# .+\n\n(.*?)(?=^## |\Z)", body, flags=re.MULTILINE | re.DOTALL)
    if not match:
        return ""
    return " ".join(match.group(1).strip().split())


def _extract_commands(body: str) -> tuple[str, ...]:
    matches = re.findall(r"^### `([^`]+)`", body, flags=re.MULTILINE)
    return tuple(dict.fromkeys(match.strip() for match in matches if match.strip()))


def _extract_examples(body: str) -> tuple[str, ...]:
    section = _extract_section(body, "Examples")
    matches = re.findall(r"- `([^`]+)`", section)
    return tuple(dict.fromkeys(match.strip() for match in matches if match.strip()))


def _snippet(text: str, pattern: str, max_chars: int = 280) -> str:
    if not pattern:
        return " ".join(text.split())[:max_chars]
    lowered_text = text.lower()
    lowered_pattern = pattern.lower()
    position = lowered_text.find(lowered_pattern)
    if position < 0:
        return " ".join(text.split())[:max_chars]
    start = max(0, position - 120)
    end = min(len(text), position + max_chars)
    return " ".join(text[start:end].split())


@lru_cache(maxsize=16)
def _module_index(knowledge_root: Path | None = None) -> tuple[KnowledgeModule, ...]:
    modules: list[KnowledgeModule] = []
    for topic in TOPIC_DIRECTORIES:
        directory = (knowledge_root if knowledge_root is not None else KNOWLEDGE_ROOT) / topic
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            if path.name == "README.md":
                continue
            text = path.read_text(encoding="utf-8")
            frontmatter, body = _parse_frontmatter(text)
            module = KnowledgeModule(
                title=frontmatter.get("title", path.stem),
                topic=frontmatter.get("topic", topic).strip() or topic,
                source_section=frontmatter.get("source_section", frontmatter.get("title", path.stem)),
                file_path=path,
                tags=_parse_tags(frontmatter.get("tags", "")),
                summary=_extract_summary(body),
                commands=_extract_commands(body),
                examples=_extract_examples(body),
                content=text,
            )
            modules.append(module)
    return tuple(modules)


@lru_cache(maxsize=16)
def _example_index(knowledge_root: Path | None = None) -> tuple[ExampleEntry, ...]:
    entries: list[ExampleEntry] = []
    examples_root = (knowledge_root if knowledge_root is not None else KNOWLEDGE_ROOT) / "examples"
    for path in sorted(examples_root.glob("*.json")):
        payload = _read_json(path, {})
        if not isinstance(payload, dict):
            continue
        example_inputs = []
        for example in payload.get("examples", []):
            if isinstance(example, dict):
                value = str(example.get("input", "")).strip()
                if value:
                    example_inputs.append(value)
        entries.append(
            ExampleEntry(
                entry_id=str(payload.get("id", path.stem)).strip() or path.stem,
                command=str(payload.get("command", "")).strip(),
                category=str(payload.get("category", "")).strip(),
                tags=tuple(str(tag).strip() for tag in payload.get("tags", []) if str(tag).strip()),
                risk=str(payload.get("risk", "")).strip(),
                notes=str(payload.get("notes", "")).strip(),
                related_commands=tuple(
                    str(item).strip() for item in payload.get("related_commands", []) if str(item).strip()
                ),
                examples=tuple(example_inputs),
                file_path=path,
            )
        )
    return tuple(entries)


def _keyword_score(query: str, module: KnowledgeModule) -> int:
    normalized_query = _normalize_text(query)
    tokens = _tokenize(query)
    if not normalized_query or not tokens:
        return 0

    title = _normalize_text(module.title)
    topic = _normalize_text(module.topic)
    tags = {_normalize_text(tag) for tag in module.tags}
    summary = _normalize_text(module.summary)
    commands = [_normalize_text(command) for command in module.commands]
    examples = [_normalize_text(example) for example in module.examples]

    score = 0
    if normalized_query in title:
        score += 35
    if normalized_query in topic:
        score += 30
    if any(normalized_query == tag for tag in tags):
        score += 28
    if any(normalized_query == command for command in commands):
        score += 40

    for token in tokens:
        if token in title.split():
            score += 12
        if token == topic:
            score += 10
        if token in tags:
            score += 10
        if any(token in command.split() for command in commands):
            score += 8
        if any(token in example.split() for example in examples):
            score += 5
        if token in summary.split():
            score += 4
    return score


def _source_location(path: Path) -> str:
    """Keep bundled paths compatible; never misattribute an explicit corpus."""
    return str(path.relative_to(PROJECT_ROOT)) if path.is_relative_to(PROJECT_ROOT) else str(path)


def _module_result(module: KnowledgeModule, score: int, preview_seed: str) -> dict[str, Any]:
    return {
        "score": score,
        "topic": module.title,
        "category": module.topic,
        "file_location": _source_location(module.file_path),
        "summary": module.summary,
        "related_commands": list(module.commands[:8]),
        "tags": list(module.tags),
        "preview": _snippet(module.content, preview_seed),
    }


def _example_result(entry: ExampleEntry, score: int) -> dict[str, Any]:
    preview_source = entry.notes or (entry.examples[0] if entry.examples else entry.command)
    return {
        "score": score,
        "topic": entry.entry_id,
        "category": entry.category or "examples",
        "file_location": _source_location(entry.file_path),
        "summary": entry.notes or entry.command,
        "related_commands": [entry.command, *entry.related_commands][:8],
        "tags": list(entry.tags),
        "preview": _snippet(preview_source, entry.command or entry.entry_id),
    }


def _topic_filter_match(topic_filter: str | None, module_topic: str) -> bool:
    if not topic_filter:
        return True
    return _normalize_text(topic_filter) == _normalize_text(module_topic)


def search_rhcsa(query: str, limit: int = 10, topic_filter: str | None = None, *, knowledge_root: Path | None = None) -> list[dict[str, Any]]:
    """Deterministic keyword search over the local markdown RHCSA knowledge base."""
    query = query.strip()
    if not query:
        return []

    results: list[dict[str, Any]] = []
    for module in _module_index(knowledge_root):
        if not _topic_filter_match(topic_filter, module.topic):
            continue
        score = _keyword_score(query, module)
        if score:
            results.append(_module_result(module, score, query))

    for entry in _example_index(knowledge_root):
        if topic_filter and _normalize_text(topic_filter) != _normalize_text(entry.category):
            continue
        search_space = " ".join([entry.entry_id, entry.command, entry.category, " ".join(entry.tags), entry.notes])
        token_hits = 0
        normalized_search_space = _normalize_text(search_space)
        normalized_query = _normalize_text(query)
        if normalized_query and normalized_query in normalized_search_space:
            token_hits += 20
        for token in _tokenize(query):
            if token in normalized_search_space.split():
                token_hits += 6
        if token_hits:
            results.append(_example_result(entry, token_hits))

    deduped: dict[str, dict[str, Any]] = {}
    for result in sorted(results, key=lambda item: (-item["score"], item["file_location"])):
        deduped.setdefault(result["file_location"], result)
    return list(deduped.values())[:limit]


def search_by_tag(tag: str, limit: int = 20, topic_filter: str | None = None, *, knowledge_root: Path | None = None) -> list[dict[str, Any]]:
    """Exact tag search without semantic expansion."""
    normalized_tag = _normalize_text(tag)
    if not normalized_tag:
        return []

    results: list[dict[str, Any]] = []
    for module in _module_index(knowledge_root):
        if not _topic_filter_match(topic_filter, module.topic):
            continue
        if normalized_tag in {_normalize_text(item) for item in module.tags}:
            results.append(_module_result(module, TAG_MATCH_SCORE, tag))

    for entry in _example_index(knowledge_root):
        if topic_filter and _normalize_text(topic_filter) != _normalize_text(entry.category):
            continue
        if normalized_tag in {_normalize_text(item) for item in entry.tags}:
            results.append(_example_result(entry, EXAMPLE_TAG_MATCH_SCORE))

    return sorted(results, key=lambda item: (-item["score"], item["file_location"]))[:limit]


def exact_command_lookup(command: str, limit: int = 20, *, knowledge_root: Path | None = None) -> list[dict[str, Any]]:
    """Match commands by exact normalized string only."""
    normalized_query = _normalized_command(command)
    if not normalized_query:
        return []

    results: list[dict[str, Any]] = []
    for module in _module_index(knowledge_root):
        for candidate in module.commands:
            if _normalized_command(candidate) == normalized_query:
                results.append(_module_result(module, EXACT_MATCH_SCORE, candidate))
                break

    for entry in _example_index(knowledge_root):
        if _normalized_command(entry.command) == normalized_query:
            results.append(_example_result(entry, EXAMPLE_EXACT_MATCH_SCORE))

    deduped: dict[str, dict[str, Any]] = {}
    for result in results:
        deduped.setdefault(result["file_location"], result)
    return list(deduped.values())[:limit]


def grep_rhcsa(pattern: str, limit: int = 20, topic_filter: str | None = None) -> list[dict[str, Any]]:
    """Literal grep-style retrieval over markdown content."""
    pattern = pattern.strip()
    if not pattern:
        return []
    lowered = pattern.lower()

    results: list[dict[str, Any]] = []
    for module in _module_index():
        if not _topic_filter_match(topic_filter, module.topic):
            continue
        match_count = module.content.lower().count(lowered)
        if match_count:
            result = _module_result(module, match_count * GREP_MATCH_UNIT_SCORE, pattern)
            result["match_count"] = match_count
            results.append(result)

    return sorted(results, key=lambda item: (-item["score"], item["file_location"]))[:limit]


def filter_by_topic(topic: str, query: str, limit: int = 10) -> list[dict[str, Any]]:
    """Keyword search restricted to one topic directory."""
    return search_rhcsa(query, limit=limit, topic_filter=topic)


def load_topic(topic: str, max_chars: int = 12000) -> str:
    """Load markdown for an exact topic directory or exact module title."""
    normalized_query = _normalize_text(topic)
    if not normalized_query:
        return ""

    if normalized_query in {_normalize_text(topic_name) for topic_name in TOPIC_DIRECTORIES}:
        topic_name = next(
            topic_name for topic_name in TOPIC_DIRECTORIES
            if _normalize_text(topic_name) == normalized_query
        )
        readme_path = KNOWLEDGE_ROOT / topic_name / "README.md"
        chunks: list[str] = []
        if readme_path.exists():
            chunks.append(readme_path.read_text(encoding="utf-8"))
        for module in _module_index():
            if module.topic == topic_name:
                chunks.append(module.content)
        text = "\n\n".join(chunks)
        return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]...\n"

    exact_modules = [
        module for module in _module_index()
        if normalized_query in {
            _normalize_text(module.topic),
            _normalize_text(module.title),
            _normalize_text(module.source_section),
            _normalize_text(module.file_path.stem),
        }
    ]
    if exact_modules:
        text = "\n\n".join(module.content for module in exact_modules)
        return text if len(text) <= max_chars else text[:max_chars] + "\n...[truncated]...\n"
    return ""


def suggest_related_commands(query: str | None = None, limit: int = 20, *, knowledge_root: Path | None = None) -> list[dict[str, Any]]:
    """Deterministic command list filtered by exact token matches."""
    normalized_query = _normalize_text(query or "")
    tokens = set(_tokenize(query or ""))
    results: list[dict[str, Any]] = []

    seen_commands: set[tuple[str, str]] = set()
    for module in _module_index(knowledge_root):
        for command in module.commands:
            command_norm = _normalize_text(command)
            if normalized_query:
                if normalized_query != command_norm and normalized_query not in command_norm:
                    if not tokens.intersection(command_norm.split()):
                        continue
            key = (command, module.title)
            if key in seen_commands:
                continue
            seen_commands.add(key)
            results.append(
                {
                    "command_name": command.split()[0],
                    "command": command,
                    "topic": module.title,
                    "file_location": _source_location(module.file_path),
                    "summary": module.summary,
                }
            )

    for entry in _example_index(knowledge_root):
        command_norm = _normalize_text(entry.command)
        if normalized_query:
            if normalized_query != command_norm and normalized_query not in command_norm:
                if not tokens.intersection(command_norm.split()):
                    continue
        key = (entry.command, entry.entry_id)
        if key in seen_commands:
            continue
        seen_commands.add(key)
        results.append(
            {
                "command_name": entry.command.split()[0],
                "command": entry.command,
                "topic": entry.entry_id,
                "file_location": _source_location(entry.file_path),
                "summary": entry.notes,
            }
        )
    return results[:limit]


def search_commands(query: str = "", limit: int = 20, *, knowledge_root: Path | None = None) -> list[dict[str, Any]]:
    return suggest_related_commands(query, limit=limit, knowledge_root=knowledge_root)


def search_workflows(query: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """Return module-level operational flows as deterministic workflow results."""
    query = query.strip()
    results: list[dict[str, Any]] = []
    for module in _module_index():
        if query and _keyword_score(query, module) == 0:
            continue
        results.append(
            {
                "topic": module.title,
                "summary": module.summary,
                "commands": list(module.commands[:8]),
                "keywords": list(module.tags),
                "source_file": str(module.file_path.relative_to(PROJECT_ROOT)),
                "score": _keyword_score(query, module) if query else 1,
            }
        )
    return sorted(results, key=lambda item: (-item["score"], item["source_file"]))[:limit]


def retrieve_examples(query: str = "", limit: int = 10) -> list[dict[str, Any]]:
    """Return deterministic example entries from local JSON examples."""
    query = query.strip()
    results: list[dict[str, Any]] = []
    for entry in _example_index():
        searchable = " ".join([entry.entry_id, entry.command, entry.category, " ".join(entry.tags), entry.notes])
        score = 1 if not query else 0
        if query:
            normalized_query = _normalize_text(query)
            normalized_searchable = _normalize_text(searchable)
            if normalized_query and normalized_query in normalized_searchable:
                score += 20
            for token in _tokenize(query):
                if token in normalized_searchable.split():
                    score += 6
        if score:
            results.append(
                {
                    "topic": entry.entry_id,
                    "summary": entry.notes or entry.command,
                    "commands": [entry.command, *entry.related_commands][:8],
                    "keywords": list(entry.tags),
                    "source_file": str(entry.file_path.relative_to(PROJECT_ROOT)),
                    "score": score,
                }
            )
    return sorted(results, key=lambda item: (-item["score"], item["source_file"]))[:limit]


def library_status() -> dict[str, Any]:
    library = detect_rhcsa_library()
    files = [path for path in library.rglob("*") if path.is_file()] if library.exists() else []
    modules = _module_index()
    examples = _example_index()
    unique_commands = {command.split()[0] for module in modules for command in module.commands if command.strip()}
    command_examples = sum(len(module.commands) for module in modules) + len(examples)
    return {
        "path": str(library),
        "exists": library.exists(),
        "files": len(files),
        "indexed_topics": len(modules),
        "indexed_command_names": len(unique_commands),
        "indexed_command_examples": command_examples,
        "indexed_workflows": len(modules),
        "indexed_examples": len(examples),
        "size_bytes": sum(path.stat().st_size for path in files),
    }


def _format_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "No RHCSA results found."
    lines: list[str] = []
    for result in results:
        lines.append(f"{result['topic']} [{result['category']}]")
        lines.append(f"  file: {result['file_location']}")
        if result.get("tags"):
            lines.append(f"  tags: {', '.join(result['tags'][:10])}")
        if result.get("related_commands"):
            lines.append(f"  commands: {', '.join(result['related_commands'][:8])}")
        if result.get("summary"):
            lines.append(f"  summary: {result['summary']}")
        if result.get("preview"):
            lines.append(f"  preview: {result['preview']}")
        lines.append("")
    return "\n".join(lines).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the local deterministic RHCSA knowledge base.")
    parser.add_argument(
        "mode",
        choices=[
            "status",
            "search",
            "topic",
            "commands",
            "workflows",
            "examples",
            "tag",
            "exact",
            "grep",
            "filter",
        ],
    )
    parser.add_argument("query", nargs="*", help="Search query or topic name")
    args = parser.parse_args()
    query = " ".join(args.query)

    if args.mode == "status":
        print(json.dumps(library_status(), indent=2, ensure_ascii=False))
    elif args.mode == "search":
        print(_format_results(search_rhcsa(query)))
    elif args.mode == "topic":
        print(load_topic(query) or "Topic not found.")
    elif args.mode == "commands":
        print(json.dumps(suggest_related_commands(query), indent=2, ensure_ascii=False))
    elif args.mode == "workflows":
        print(json.dumps(search_workflows(query), indent=2, ensure_ascii=False))
    elif args.mode == "examples":
        print(json.dumps(retrieve_examples(query), indent=2, ensure_ascii=False))
    elif args.mode == "tag":
        print(_format_results(search_by_tag(query)))
    elif args.mode == "exact":
        print(_format_results(exact_command_lookup(query)))
    elif args.mode == "grep":
        print(_format_results(grep_rhcsa(query)))
    elif args.mode == "filter":
        parts = query.split(maxsplit=1)
        if len(parts) != 2:
            print("Usage: rhcsa_search.py filter TOPIC QUERY")
        else:
            print(_format_results(filter_by_topic(parts[0], parts[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
