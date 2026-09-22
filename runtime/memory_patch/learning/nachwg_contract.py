"""Bounded factual answer DTOs for the architect's one NachwG case.

This module describes possible actor answers, including wrong ones. It contains
no expected answer, verification result, consent, or effect authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json

from runtime.memory_patch.contract import parse_request


NACHWG_OUTPUT_SCHEMA = "aioa-nachwg-claims-v1"
NACHWG_CASE_ID = "g07-nachwg-current-architect-v1"
NACHWG_HAT = "german-employment-law"
HISTORICAL_QUESTION = (
    "As of today, can an employer in Germany validly hire an employee under an oral "
    "employment agreement? Must the essential employment terms be provided on paper "
    "and signed, or can they be sent electronically? Explain the rules introduced in 2022, "
    "the change effective from 1 January 2025, all important conditions and exceptions, "
    "and cite the controlling provisions."
)
MAX_ANSWER_BYTES = 4096

# Types describe facts, not whether the actor believes its answer is supported.
# Every boolean accepts either value. Dates, provisions, and form names are not
# prefilled; Core alone compares the actor's choices with admitted source rules.
CLAIM_FIELDS = (
    ("LEGAL_DISTINCTION", (
        ("ordinary_oral_agreement_valid", bool),
        ("proof_duty_separate", bool),
        ("all_employment_agreements_form_free", bool),
        ("proof_duties_2022", str),
    )),
    ("ELECTRONIC_TEXT_FORM", (
        ("electronic_transmission_permitted", bool),
        ("proof_form", str),
        ("effective_from", str),
        ("signed_paper_always_required", bool),
    )),
    ("ACCESSIBILITY", (("employee_access_required", bool),)),
    ("SAVE_AND_PRINT", (("saving_required", bool), ("printing_required", bool))),
    ("RECEIPT_CONFIRMATION_REQUEST", (("employer_requests_receipt", bool),)),
    ("PAPER_REQUEST_SAFEGUARD", (
        ("employee_can_request_signed_record", bool),
        ("employer_provides_without_delay", bool),
    )),
    ("SECTOR_EXCEPTION", (
        ("electronic_simplification_excludes_sectors", bool),
        ("statute", str), ("section", str), ("paragraph", int),
    )),
    ("CONTROLLING_PROVISION", (
        ("statute", str), ("section", str), ("paragraph", int),
    )),
)
CLAIM_IDS = tuple(identifier for identifier, _ in CLAIM_FIELDS)


@dataclass(frozen=True, slots=True)
class TypedLegalClaim:
    claim_id: str
    values: tuple[tuple[str, object], ...]


@dataclass(frozen=True, slots=True)
class TypedLegalAnswer:
    claims: tuple[TypedLegalClaim, ...]

    def payload(self):
        return {"claims": {c.claim_id: dict(c.values) for c in self.claims}}

    def canonical(self):
        return json.dumps(self.payload(), ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False)


def parse_legal_answer(value) -> TypedLegalAnswer:
    """Validate shape only. Missing factual values remain omissions for Core.

    Shared parse_request rejects duplicate JSON keys, NaN, and Infinity. No free
    text or unknown fields are accepted, so unrelated prose cannot be silently
    certified alongside the bounded facts. Wrong, well-typed answers remain
    valid input to the factual verifier; this parser does not know the key.
    """
    if type(value) is str:
        if len(value.encode("utf-8")) > MAX_ANSWER_BYTES:
            raise ValueError("NACHWG_ANSWER_TOO_LARGE")
        value = parse_request(value)
    if not isinstance(value, Mapping) or set(value) != {"claims"}:
        raise ValueError("NACHWG_ANSWER_SCHEMA")
    claims = value["claims"]
    if not isinstance(claims, Mapping) or set(claims) - set(CLAIM_IDS):
        raise ValueError("NACHWG_CLAIM_SCHEMA")
    parsed = []
    for identifier, fields in CLAIM_FIELDS:
        if identifier not in claims:
            continue
        values = claims[identifier]
        allowed = dict(fields)
        if not isinstance(values, Mapping) or set(values) - set(allowed):
            raise ValueError("NACHWG_FACT_SCHEMA")
        pairs = []
        for name, expected_type in fields:
            if name not in values:
                continue
            item = values[name]
            if item is not None:
                if type(item) is not expected_type:
                    raise ValueError("NACHWG_FACT_TYPE")
                if expected_type is str and (
                    not item or len(item) > 96 or any(ord(c) < 32 for c in item)
                ):
                    raise ValueError("NACHWG_FACT_STRING")
                if expected_type is int and not 0 <= item <= 999:
                    raise ValueError("NACHWG_FACT_INTEGER")
            pairs.append((name, item))
        parsed.append(TypedLegalClaim(identifier, tuple(pairs)))
    result = TypedLegalAnswer(tuple(parsed))
    if len(result.canonical().encode("utf-8")) > MAX_ANSWER_BYTES:
        raise ValueError("NACHWG_ANSWER_TOO_LARGE")
    return result


def actor_output_contract():
    """Answer-neutral formatting wrapper; never contains the Core answer key."""
    types = {bool: "boolean", str: "string", int: "integer"}
    definitions = {}
    for identifier, fields in CLAIM_FIELDS:
        properties = {}
        for name, kind in fields:
            prop = {"type": [types[kind], "null"]}
            if kind is str:
                prop["maxLength"] = 96
            if kind is int:
                prop.update(minimum=0, maximum=999)
            properties[name] = prop
        definitions[identifier] = {
            "type": "object", "additionalProperties": False,
            "properties": properties, "required": [name for name, _ in fields],
        }
    return {
        "type": "object", "additionalProperties": False, "required": ["claims"],
        "properties": {"claims": {
            "type": "object", "additionalProperties": False,
            "properties": definitions, "required": list(CLAIM_IDS),
        }},
        "format_notes": {
            "proof_duties_2022": "Use expanded, unchanged, removed, or unknown.",
            "proof_form": "Use text_form, signed_paper_only, qualified_electronic_form_only, none, or unknown.",
            "effective_from": "Use an ISO date YYYY-MM-DD, or null if unknown.",
            "statute": "Use the German statute's standard abbreviation.",
            "section": "Use the section number as a string, without the section sign.",
            "unknown_facts": "Use null, never a claimed verification verdict.",
        },
    }
