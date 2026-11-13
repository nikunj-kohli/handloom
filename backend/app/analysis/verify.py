"""Citation verification.

Two passes, both required before a claim reaches a reviewer:
1. Every cited evidence id must exist in this session (exact, no fuzzy matching).
2. The claim must be supported by the cited text — a model check when a key is
   configured, otherwise a deterministic overlap check that is labelled as such.
Claims that fail are dropped, and the drop is visible in the UI (never silent).
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence, Tuple

from .. import llm
from . import taxonomy

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "was", "were", "are", "is", "be", "been",
    "a", "an", "of", "to", "in", "on", "at", "by", "as", "it", "its", "or", "but", "not", "no",
    "we", "they", "he", "she", "them", "their", "our", "you", "i", "if", "then", "than", "so",
    "has", "have", "had", "do", "does", "did", "will", "would", "can", "could", "should", "may",
    "about", "after", "before", "into", "over", "under", "up", "down", "out", "only", "also",
}

WORD_RE = re.compile(r"[a-z0-9][a-z0-9_+.-]{1,}")


def tokens(text: str) -> set:
    return {word for word in WORD_RE.findall((text or "").lower()) if word not in STOPWORDS and len(word) > 2}


def support_score(claim_text: str, cited: Sequence[Dict[str, Any]]) -> float:
    claim_tokens = tokens(claim_text)
    if not claim_tokens or not cited:
        return 0.0
    evidence_tokens = set()
    for item in cited:
        evidence_tokens |= tokens(item.get("title") or "")
        evidence_tokens |= tokens(item.get("body") or "")
    if not evidence_tokens:
        return 0.0
    return round(len(claim_tokens & evidence_tokens) / len(claim_tokens), 3)


def validate_ids(claims: List[Dict[str, Any]], known_ids: set) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for claim in claims:
        ids = [evidence_id for evidence_id in (claim.get("evidence_ids") or []) if evidence_id in known_ids]
        if not ids:
            dropped.append(dict(claim, drop_reason="No cited evidence id exists in this session."))
            continue
        claim["evidence_ids"] = ids[:4]
        kept.append(claim)
    return kept, dropped


STRONGER_LABELS = {"verbatim", "template", "rules", "id-check"}


def heuristic_pass(claims: List[Dict[str, Any]], index: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Score every claim against its citations, without weakening stronger labels."""
    for claim in claims:
        cited = [index[eid] for eid in claim.get("evidence_ids", []) if eid in index]
        score = support_score(claim.get("text") or "", cited)
        claim["_support"] = score
        if claim.get("verification") in STRONGER_LABELS:
            continue
        claim["verification"] = "heuristic"
        claim["verification_note"] = (
            "Deterministic overlap check (%.0f%% of claim terms appear in the cited records)." % (score * 100)
        )
    return claims


VERIFIER_SYSTEM = (
    "You are a strict citation auditor for a knowledge handover tool. "
    "You decide whether a claim is fully supported by the evidence text it cites. "
    "Be conservative: a claim that adds a number, name, date, cause or recommendation not "
    "present in the cited text is NOT supported. Reply with JSON only."
)


def _llm_pass_chunk(
    claims: List[Dict[str, Any]], index: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Verify one batch of claims. Falls back to the overlap check on any failure."""
    if not claims:
        return claims, [], "No model claims to verify."

    blocks: List[str] = []
    for position, claim in enumerate(claims, start=1):
        excerpts = []
        for evidence_id in claim.get("evidence_ids", [])[:2]:
            item = index.get(evidence_id)
            if not item:
                continue
            excerpts.append(
                "[%s] (%s, %s) %s" % (evidence_id, item.get("source_type"), item.get("occurred_at") or "no date", (item.get("body") or "")[:350])
            )
        blocks.append("CLAIM C%d:\n%s\nEVIDENCE:\n%s" % (position, claim.get("text"), "\n".join(excerpts)))

    prompt = (
        "For each claim below, decide if the cited evidence supports it as written.\n"
        "Answer with JSON: {\"verdicts\":[{\"n\":1,\"supported\":true,\"reason\":\"short\"}]}\n\n"
        + "\n\n".join(blocks)
    )
    result = llm.complete(VERIFIER_SYSTEM, prompt, max_tokens=700)
    if not result.ok:
        return heuristic_pass(claims, index), [], "Model verification unavailable (%s); used the deterministic overlap check." % (
            result.error or "no key"
        )

    parsed = llm.parse_json_object(result.text)
    verdicts = parsed.get("verdicts") if isinstance(parsed, dict) else None
    if not isinstance(verdicts, list):
        return heuristic_pass(claims, index), [], "Verifier returned an unusable response; used the overlap check."

    by_number: Dict[int, Dict[str, Any]] = {}
    for verdict in verdicts:
        if not isinstance(verdict, dict):
            continue
        try:
            number = int(verdict.get("n"))
        except (TypeError, ValueError):
            continue
        by_number[number] = verdict

    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    for position, claim in enumerate(claims, start=1):
        verdict = by_number.get(position)
        if verdict is None:
            claim["verification"] = "llm"
            claim["verification_note"] = "Verifier returned no verdict for this claim; kept as low confidence."
            claim["confidence"] = "low"
            kept.append(claim)
            continue
        if bool(verdict.get("supported")):
            claim["verification"] = "llm"
            reason = str(verdict.get("reason") or "Supported by the cited text.")[:240]
            claim["verification_note"] = "Model check: %s" % reason
            kept.append(claim)
        else:
            reason = str(verdict.get("reason") or "Not supported by the cited text.")[:240]
            # Record who rejected it: the model, not the wording overlap check.
            dropped.append(
                dict(claim, drop_reason="Citation verifier rejected it: %s" % reason, verification="llm")
            )
    return kept, dropped, "Model verified %d claims; dropped %d." % (len(claims), len(dropped))


def llm_pass(
    claims: List[Dict[str, Any]], index: Dict[str, Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str]:
    """Verify in small batches so a per-minute token limit cannot fail the whole pass."""
    if not claims:
        return claims, [], "No model claims to verify."
    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    fallback_batches = 0
    for start in range(0, len(claims), 8):
        chunk = claims[start : start + 8]
        chunk_kept, chunk_dropped, note = _llm_pass_chunk(chunk, index)
        kept.extend(chunk_kept)
        dropped.extend(chunk_dropped)
        if not note.startswith("Model verified"):
            fallback_batches += 1
    summary = "Model verified %d claims; dropped %d." % (len(claims), len(dropped))
    if fallback_batches:
        summary += " %d batch(es) fell back to the deterministic overlap check." % fallback_batches
    return kept, dropped, summary


def confidence_for(claim: Dict[str, Any]) -> str:
    """Rule claims are high (a template plan is medium). Model claims need two sources for
    high. Only model text is downgraded by lexical overlap: a computed count or ownership
    share is supported by the cited set even though its wording is not quoted from it."""
    sources = len({eid for eid in claim.get("evidence_ids") or []})
    if claim.get("origin") == "rules":
        return "medium" if claim.get("verification") == "template" else "high"

    base = "high" if sources >= 2 else ("medium" if sources == 1 else "low")
    support = claim.get("_support")
    if support is not None and support < 0.35:
        base = {"high": "medium", "medium": "low", "low": "low"}[base]
        claim["low_evidence"] = True
    return base


def describe_evidence(item: Dict[str, Any]) -> str:
    return "%s · %s" % (taxonomy.label((item.get("areas") or ["unclassified"])[0]), item.get("source_type"))
