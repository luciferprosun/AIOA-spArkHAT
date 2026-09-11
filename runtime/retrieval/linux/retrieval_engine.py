from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from retrieval.linux.graph_loader import load_command_graph
from retrieval.linux.provenance_attach import attach_provenance
from retrieval.linux.query_normalizer import command_key, normalize_query, normalize_text
from retrieval.linux.scoring import (
    ALIAS_MATCH_SCORE,
    CATEGORY_MATCH_SCORE,
    EXACT_MATCH_SCORE,
    FAMILY_MATCH_SCORE,
    KEYWORD_MATCH_SCORE,
    LOW_CONFIDENCE_SCORE,
    SUBCOMMAND_MATCH_SCORE,
    ScoreDecision,
    score_decision,
    should_refuse,
)
from tools.rhcsa_search import exact_command_lookup, search_by_tag, search_commands, search_rhcsa


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KNOWLEDGE_ROOT = PROJECT_ROOT / "knowledge"
GENERIC_QUERY_TOKENS = {
    "a",
    "about",
    "command",
    "commands",
    "for",
    "how",
    "jak",
    "linux",
    "mi",
    "not",
    "o",
    "rhcsa",
    "rhce",
    "show",
    "the",
    "to",
    "use",
    "w",
}


@dataclass(frozen=True)
class LinuxRetrievalResponse:
    query: str
    normalized_query: str
    status: str
    match_type: str
    confidence: str
    confidence_score: int
    results: tuple[dict[str, Any], ...]
    message: str

    @property
    def answered(self) -> bool:
        return self.status == "answered"

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "normalized_query": self.normalized_query,
            "status": self.status,
            "match_type": self.match_type,
            "confidence": self.confidence,
            "confidence_score": self.confidence_score,
            "results": list(self.results),
            "message": self.message,
        }


class LinuxRetrievalEngine:
    """Deterministic evidence-backed Linux/RHCSA retrieval.

    This is an infrastructure layer: it does not call models, does not infer
    missing commands, and refuses low-confidence queries.
    """

    def __init__(self, project_dir: Path | None = None, max_results: int = 5) -> None:
        self.project_dir = Path(project_dir).resolve() if project_dir is not None else PROJECT_ROOT
        self.knowledge_root = self.project_dir / "knowledge"
        self.max_results = max_results

    def retrieve(self, query: str) -> LinuxRetrievalResponse:
        normalized = normalize_query(query)
        if not self.knowledge_root.is_dir():
            return self._refusal(query, normalized.normalized, "missing_resource", 0)
        if not normalized.normalized:
            return self._refusal(query, "", "unresolved", 0)

        candidates: list[dict[str, Any]]
        decision: ScoreDecision

        if normalized.candidate_command:
            exact = self._exact_lookup(normalized.candidate_command)
            if exact:
                decision = score_decision("exact", EXACT_MATCH_SCORE, len(exact))
                return self._answer(query, normalized.normalized, exact, decision)

        if normalized.alias_target:
            alias = self._exact_lookup(normalized.alias_target)
            if alias:
                decision = score_decision("alias", ALIAS_MATCH_SCORE, len(alias))
                return self._answer(query, normalized.normalized, alias, decision)

        if normalized.candidate_command:
            subcommand = self._subcommand_lookup(normalized.candidate_command)
            if subcommand:
                decision = score_decision("subcommand", SUBCOMMAND_MATCH_SCORE, len(subcommand))
                return self._answer(query, normalized.normalized, subcommand, decision)

        if normalized.category_hint:
            category = search_by_tag(normalized.category_hint, limit=self.max_results, knowledge_root=self.knowledge_root)
            if not category:
                category = search_rhcsa(normalized.category_hint, limit=self.max_results, topic_filter=normalized.category_hint, knowledge_root=self.knowledge_root)
            if category:
                decision = score_decision("category", CATEGORY_MATCH_SCORE, len(category))
                return self._answer(query, normalized.normalized, category, decision)

        family = self._family_lookup(normalized.candidate_command)
        if family:
            decision = score_decision("command_family", FAMILY_MATCH_SCORE, len(family))
            return self._answer(query, normalized.normalized, family, decision)

        keyword_query = self._keyword_query(normalized.tokens)
        if not keyword_query:
            return self._refusal(query, normalized.normalized, "unresolved", 0)

        candidates = search_rhcsa(keyword_query, limit=self.max_results, knowledge_root=self.knowledge_root)
        if candidates:
            decision = score_decision("keyword", KEYWORD_MATCH_SCORE, len(candidates))
            return self._answer(query, normalized.normalized, candidates, decision)

        weak = search_commands(keyword_query, limit=1, knowledge_root=self.knowledge_root)
        if weak:
            decision = score_decision("low_confidence", LOW_CONFIDENCE_SCORE, len(weak))
            if should_refuse(decision.score):
                return self._refusal(query, normalized.normalized, decision.match_type, decision.score)
            return self._answer(query, normalized.normalized, weak, decision)

        return self._refusal(query, normalized.normalized, "unresolved", 0)

    def _exact_lookup(self, command: str) -> list[dict[str, Any]]:
        results = exact_command_lookup(command, limit=self.max_results, knowledge_root=self.knowledge_root)
        if results:
            return results
        command_record = self.command_records_by_key.get(command_key(command))
        if not command_record:
            return []
        return [self._command_record_result(command_record)]

    def _subcommand_lookup(self, command: str) -> list[dict[str, Any]]:
        key = command_key(command)
        if " " not in key:
            return []
        results = [
            self._command_record_result(record)
            for record_key, record in self.command_records_by_key.items()
            if record_key.startswith(f"{key} ") or key.startswith(f"{record_key} ")
        ]
        return self._dedupe(results)[: self.max_results]

    def _family_lookup(self, command: str) -> list[dict[str, Any]]:
        if not command:
            return []
        family = command.split()[0].lower()
        graph_node = self.command_graph.get("nodes", {}).get(family)
        results: list[dict[str, Any]] = []
        if isinstance(graph_node, dict):
            results.append(
                {
                    "topic": family,
                    "category": graph_node.get("kind", "command_family"),
                    "file_location": self._source_location("command_graph.json"),
                    "summary": f"Command graph family for {family}.",
                    "related_commands": graph_node.get("commands", [])[:8],
                    "tags": graph_node.get("related", [])[:8],
                    "preview": ", ".join(graph_node.get("commands", [])[:5]),
                    "score": FAMILY_MATCH_SCORE,
                }
            )
        for item in search_commands(family, limit=self.max_results, knowledge_root=self.knowledge_root):
            if item.get("command_name", "").lower() == family:
                results.append(item)
        return self._dedupe(results)[: self.max_results]

    def _answer(
        self,
        query: str,
        normalized_query: str,
        raw_results: list[dict[str, Any]],
        decision: ScoreDecision,
    ) -> LinuxRetrievalResponse:
        if should_refuse(decision.score):
            return self._refusal(query, normalized_query, decision.match_type, decision.score)
        bounded = self._dedupe(raw_results)[: self.max_results]
        results = tuple(attach_provenance(result, decision.score, knowledge_root=self.knowledge_root) for result in bounded)
        return LinuxRetrievalResponse(
            query=query,
            normalized_query=normalized_query,
            status="answered",
            match_type=decision.match_type,
            confidence=decision.confidence,
            confidence_score=decision.score,
            results=results,
            message=self._format_message(results, decision),
        )

    def _refusal(
        self,
        query: str,
        normalized_query: str,
        match_type: str,
        score: int,
    ) -> LinuxRetrievalResponse:
        return LinuxRetrievalResponse(
            query=query,
            normalized_query=normalized_query,
            status="refused",
            match_type=match_type,
            confidence="none",
            confidence_score=score,
            results=(),
            message=(
                "I do not have enough local RHCSA/Linux evidence to answer deterministically. "
                "Please clarify the command, category, or Linux task."
            ),
        )

    @staticmethod
    def _format_message(results: tuple[dict[str, Any], ...], decision: ScoreDecision) -> str:
        lines = [
            "Local Linux/RHCSA retrieval hit.",
            f"Match: {decision.match_type}",
            f"Confidence: {decision.confidence} ({decision.score})",
            "Evidence-backed results:",
        ]
        for result in results:
            topic = result.get("topic") or result.get("command") or "unknown"
            source = result.get("provenance", {}).get("source_file", "")
            commands = result.get("related_commands") or result.get("commands") or []
            command_text = ", ".join(str(item) for item in commands[:5])
            lines.append(f"- {topic}: {command_text}".rstrip())
            lines.append(f"  source: {source}")
        return "\n".join(lines)

    @staticmethod
    def _dedupe(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        deduped: dict[str, dict[str, Any]] = {}
        for result in results:
            key = "|".join(
                str(result.get(part, ""))
                for part in ("file_location", "source_file", "topic", "command", "summary")
            )
            deduped.setdefault(key, result)
        return list(deduped.values())

    @staticmethod
    def _keyword_query(tokens: tuple[str, ...]) -> str:
        meaningful = [
            token
            for token in tokens
            if token not in GENERIC_QUERY_TOKENS and not token.startswith("zzzz")
        ]
        if not meaningful:
            return ""
        if len(meaningful) == 1 and "-" in meaningful[0] and meaningful[0].count("-") >= 3:
            return ""
        return " ".join(meaningful[:4])

    @cached_property
    def command_records_by_key(self) -> dict[str, dict[str, Any]]:
        path = self.knowledge_root / "canonical" / "rhcsa_commands.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        records: dict[str, dict[str, Any]] = {}
        if not isinstance(payload, list):
            return records
        for item in payload:
            if not isinstance(item, dict):
                continue
            command = str(item.get("command", "")).strip()
            if not command:
                continue
            records.setdefault(command_key(command), item)
        return records

    @cached_property
    def command_graph(self) -> dict[str, Any]:
        return load_command_graph(self.project_dir)

    def _source_location(self, relative: str) -> str:
        return ("runtime/knowledge/" + relative) if self.knowledge_root == KNOWLEDGE_ROOT else str(self.knowledge_root / relative)

    def _command_record_result(self, record: dict[str, Any]) -> dict[str, Any]:
        command = str(record.get("command", "")).strip()
        category = str(record.get("category", "")).strip() or "canonical"
        source_section = str(record.get("source_section", "")).strip()
        examples = [str(item).strip() for item in record.get("examples", []) if str(item).strip()]
        return {
            "topic": source_section or category,
            "category": category,
            "file_location": self._source_location("canonical/rhcsa_commands.json"),
            "summary": str(record.get("description", "")).strip() or command,
            "related_commands": [command, *examples][:8],
            "tags": [normalize_text(category), normalize_text(source_section)],
            "preview": command,
            "score": EXACT_MATCH_SCORE,
        }
