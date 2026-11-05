# MIT, Copyright (c) 2026 Lukasz Zuchowski.
# Selective port from 8f9b14b7ea0f7d5a963244c62d27d3f3dcbeb26c:runtime/cpt/schema.py
# Pure preview only; historical audit writer and provider boundary excluded.
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import ClassVar


ALLOWED_CANONICAL_STATUS = frozenset({"DRAFT", "NOT_CANONICAL"})


@dataclass(frozen=True)
class CriticTransformationRecord:
    schema_version: str
    transformation_id: str
    created_at: str
    original_prompt: str
    sanitized_original_prompt: str
    transformed_prompt: str
    critic_mode: str
    template_version: str
    transformation_version: str
    required_sections: tuple[str, ...]
    forbidden_behaviors: tuple[str, ...]
    provider_call_permitted: bool
    execution_permitted: bool
    browser_action_permitted: bool
    human_review_required: bool
    canonical_status: str
    original_prompt_hash: str
    transformed_prompt_hash: str
    provenance_note: str

    CPT_A1_MODE: ClassVar[str] = "balanced_critic"

    def __post_init__(self) -> None:
        self._require_non_empty("schema_version", self.schema_version)
        self._require_non_empty("transformation_id", self.transformation_id)
        self._require_non_empty("created_at", self.created_at)
        self._require_non_empty("original_prompt", self.original_prompt)
        self._require_non_empty("sanitized_original_prompt", self.sanitized_original_prompt)
        self._require_non_empty("transformed_prompt", self.transformed_prompt)
        self._require_non_empty("template_version", self.template_version)
        self._require_non_empty("transformation_version", self.transformation_version)
        self._require_non_empty("original_prompt_hash", self.original_prompt_hash)
        self._require_non_empty("transformed_prompt_hash", self.transformed_prompt_hash)
        self._require_non_empty("provenance_note", self.provenance_note)

        if self.critic_mode != self.CPT_A1_MODE:
            raise ValueError("CPT-A1 supports only critic_mode='balanced_critic'")
        if self.provider_call_permitted is not False:
            raise ValueError("provider_call_permitted must be False")
        if self.execution_permitted is not False:
            raise ValueError("execution_permitted must be False")
        if self.browser_action_permitted is not False:
            raise ValueError("browser_action_permitted must be False")
        if self.human_review_required is not True:
            raise ValueError("human_review_required must be True")
        if self.canonical_status not in ALLOWED_CANONICAL_STATUS:
            raise ValueError("canonical_status must be DRAFT or NOT_CANONICAL")
        if not self.required_sections:
            raise ValueError("required_sections must not be empty")
        if not self.forbidden_behaviors:
            raise ValueError("forbidden_behaviors must not be empty")

    @staticmethod
    def _require_non_empty(field_name: str, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must be a non-empty string")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False)
