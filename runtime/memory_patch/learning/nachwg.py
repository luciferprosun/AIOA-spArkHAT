"""Deterministic, bounded Core rules for one current NachwG demonstration.

The statutory check and official commencement check are complementary proof
dimensions, not two independent legal opinions. Both consume Core-admitted,
current source bytes; neither consumes actor assertions of truth or authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

from runtime.core_admission import OwnerScope
from runtime.memory_patch.contracts.serialization import canonical_sha256
from runtime.memory_patch.learning.contracts import VerificationVerdict
from runtime.memory_patch.learning.nachwg_contract import (
    CLAIM_IDS, NACHWG_CASE_ID, NACHWG_HAT, parse_legal_answer,
)
from runtime.mission.contracts import MissionError


SOURCE_IDS = tuple(sorted((
    "nachwg_2", "bgb_126b", "schwarzarbg_2a", "gewo_105",
    "bmas_2025", "bmas_2022",
)))

# These are Core's reviewed rules, never part of the initial actor wrapper.
def expected_claims():
    return {
        "LEGAL_DISTINCTION": {
            "ordinary_oral_agreement_valid": True, "proof_duty_separate": True,
            "all_employment_agreements_form_free": False,
            "proof_duties_2022": "expanded",
        },
        "ELECTRONIC_TEXT_FORM": {
            "electronic_transmission_permitted": True, "proof_form": "text_form",
            "effective_from": "2025-01-01", "signed_paper_always_required": False,
        },
        "ACCESSIBILITY": {"employee_access_required": True},
        "SAVE_AND_PRINT": {"saving_required": True, "printing_required": True},
        "RECEIPT_CONFIRMATION_REQUEST": {"employer_requests_receipt": True},
        "PAPER_REQUEST_SAFEGUARD": {
            "employee_can_request_signed_record": True,
            "employer_provides_without_delay": True,
        },
        "SECTOR_EXCEPTION": {
            "electronic_simplification_excludes_sectors": True,
            "statute": "SchwarzArbG", "section": "2a", "paragraph": 1,
        },
        "CONTROLLING_PROVISION": {"statute": "NachwG", "section": "2", "paragraph": 1},
    }


CLAIM_SOURCES = {
    "LEGAL_DISTINCTION": ("gewo_105", "nachwg_2", "bmas_2022"),
    "ELECTRONIC_TEXT_FORM": ("nachwg_2", "bgb_126b", "bmas_2025"),
    "ACCESSIBILITY": ("nachwg_2",),
    "SAVE_AND_PRINT": ("nachwg_2", "bgb_126b"),
    "RECEIPT_CONFIRMATION_REQUEST": ("nachwg_2",),
    "PAPER_REQUEST_SAFEGUARD": ("nachwg_2",),
    "SECTOR_EXCEPTION": ("nachwg_2", "schwarzarbg_2a"),
    "CONTROLLING_PROVISION": ("nachwg_2",),
}

# Exact German fragments are checked after whitespace normalization. A changed
# source or missing condition fails closed instead of keeping an old answer key.
STATUTORY_ANCHORS = {
    "nachwg_2": (
        "§ 2 Nachweispflicht", "(1) Der Arbeitgeber hat die wesentlichen Vertragsbedingungen",
        "Textform (§ 126b des Bürgerlichen Gesetzbuchs)",
        "abgefasst und elektronisch übermittelt werden",
        "für den Arbeitnehmer zugänglich ist, gespeichert und ausgedruckt werden kann",
        "auffordert, einen Empfangsnachweis zu erteilen",
        "auf Verlangen des Arbeitnehmers", "unverzüglich in der Form der Sätze 1 und 8",
        "Die Sätze 2 bis 5 finden keine Anwendung", "§ 2a Absatz 1 des Schwarzarbeitsbekämpfungsgesetzes",
    ),
    "bgb_126b": ("§ 126b Textform", "lesbare Erklärung", "dauerhaften Datenträger"),
    "gewo_105": ("§ 105 Freie Gestaltung des Arbeitsvertrages", "Form des Arbeitsvertrages",
                 "zwingende gesetzliche Vorschriften", "Nachweisgesetzes"),
    "schwarzarbg_2a": ("§ 2a", "(1)", "Wirtschaftsbereichen", "Wirtschaftszweigen"),
}
COMMENCEMENT_ANCHORS = {
    "bmas_2025": ("zum 1. Januar 2025 in Kraft treten",
                  "Formerfordernisse für Nachweise nach dem Nachweisgesetz"),
    "bmas_2022": ("Erweiterung der bereits in der Nachweisrichtlinie vorgesehenen Pflicht",
                  "Nachweispflichten", "26.07.2022"),
}


def source_text_digest(text):
    return hashlib.sha256(" ".join(text.split()).encode("utf-8")).hexdigest()


def _texts(request, scope, versions, valid_until, text_digests):
    if (request.scope != scope or request.domain_hat != NACHWG_HAT
            or request.task_signature != NACHWG_CASE_ID
            or not datetime(2025, 1, 1, tzinfo=timezone.utc) <= request.at < valid_until
            or tuple((s[0], s[1]) for s in request.sources) != versions
            or tuple(s[0] for s in request.sources) != SOURCE_IDS
            or tuple((s[0], source_text_digest(s[3])) for s in request.sources) != text_digests):
        return None
    return {s[0]: " ".join(s[3].split()) for s in request.sources}


def _anchors_match(texts, requirements):
    return texts is not None and all(
        all(fragment in texts.get(source_id, "") for fragment in fragments)
        for source_id, fragments in requirements.items()
    )


@dataclass(frozen=True, slots=True)
class NachwgStatutoryVerifier:
    scope: OwnerScope
    source_versions: tuple[tuple[str, str], ...]
    valid_until: datetime
    source_text_digests: tuple[tuple[str, str], ...]

    def verify(self, request):
        texts = _texts(request, self.scope, self.source_versions, self.valid_until, self.source_text_digests)
        supported = _anchors_match(texts, STATUTORY_ANCHORS)
        try:
            claims = parse_legal_answer(request.claim).payload()["claims"]
            expected = expected_claims()
            supported = supported and bool(claims) and all(
                values == expected[identifier] for identifier, values in claims.items()
            )
        except (TypeError, ValueError):
            supported = False
        return VerificationVerdict(request.digest, supported)


@dataclass(frozen=True, slots=True)
class NachwgCommencementVerifier:
    """Separate official-source check of the applicable 2022/2025 regime.

    This does not purport to establish each statutory condition on its own.
    NativeLearning requires this AND the complete statutory factual check.
    """
    scope: OwnerScope
    source_versions: tuple[tuple[str, str], ...]
    valid_until: datetime
    source_text_digests: tuple[tuple[str, str], ...]

    def verify(self, request):
        texts = _texts(request, self.scope, self.source_versions, self.valid_until, self.source_text_digests)
        supported = _anchors_match(texts, COMMENCEMENT_ANCHORS)
        try:
            claims = parse_legal_answer(request.claim).payload()["claims"]
            supported = supported and bool(claims)
            if "LEGAL_DISTINCTION" in claims:
                supported = supported and claims["LEGAL_DISTINCTION"].get("proof_duties_2022") == "expanded"
            if "ELECTRONIC_TEXT_FORM" in claims:
                supported = supported and claims["ELECTRONIC_TEXT_FORM"].get("effective_from") == "2025-01-01"
        except (TypeError, ValueError):
            supported = False
        return VerificationVerdict(request.digest, supported)


def require_case(learning):
    if (learning.policy.domain_hat != NACHWG_HAT
            or learning.policy.task_signature != NACHWG_CASE_ID
            or learning.policy.source_ids != SOURCE_IDS
            or {type(v.verifier) for v in learning.verifiers}
            != {NachwgStatutoryVerifier, NachwgCommencementVerifier}
            or len(learning.verifiers) != 2):
        raise MissionError("NACHWG_CORE_BINDINGS_REQUIRED")


def assess(learning, answer):
    """Called by NativeLearning, reusing its native current-evidence boundary."""
    require_case(learning)
    parsed = parse_legal_answer(answer)
    context = learning.memory.retrieve(learning.policy.task_instruction)
    if context.status != "READY":
        raise MissionError("MEMORY_DEGRADED")
    sources = learning._sources(context.eligible, context.canonical_bundle)
    # Reject stale/missing source rules as an evidence failure, not an actor error.
    complete = {"claims": expected_claims()}
    if not learning.verify(json.dumps(complete, sort_keys=True), sources)[0]:
        raise MissionError("NACHWG_CURRENT_EVIDENCE_REQUIRED")
    actual = parsed.payload()["claims"]
    checks = {}
    for identifier, expected in expected_claims().items():
        values = actual.get(identifier, {})
        supported, receipts = learning.verify(
            json.dumps({"claims": {identifier: values}}, sort_keys=True), sources,
        )
        checks[identifier] = {
            "supported": supported,
            "failed_fields": [name for name, value in expected.items()
                              if values.get(name) != value or type(values.get(name)) is not type(value)],
            "source_ids": list(CLAIM_SOURCES[identifier]),
            "proof_receipts": receipts,
        }
    failed = tuple(identifier for identifier in CLAIM_IDS if not checks[identifier]["supported"])
    return {
        "status": "REPAIR_REQUIRED" if failed else "ALL_SUPPORTED",
        "answer": parsed, "checks": checks, "failed_claim_ids": failed,
        "context": context, "sources": sources,
        "source_basis_digest": canonical_sha256(sources),
    }
