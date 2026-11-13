"""Unit tests for the parts that carry the product's promises: matching, tagging,
citation checks and the audit export. No server or network needed.
"""
from __future__ import annotations

from backend.app.analysis import taxonomy, verify
from backend.app.analysis.export import render_traceability_csv, traceability_rows
from backend.app.analysis.rules import normalise


def test_normalise_folds_accents() -> None:
    assert normalise("Sebastián Ramírez") == normalise("Sebastian Ramirez")
    assert normalise("  PRIYA   Raman ") == "priya raman"


def test_taxonomy_keeps_unrelated_paths_out_of_billing() -> None:
    assert taxonomy.areas_from_paths(["scripts/build.sh"]) == ["infra"]
    assert taxonomy.areas_from_paths(["docs/index.md"]) == ["docs"]
    assert taxonomy.areas_from_paths(["services/billing/charge.py"]) == ["billing-engine"]


def test_taxonomy_infer_areas_mentions_billing_only_on_billing_words() -> None:
    assert taxonomy.infer_areas("Remove obsolete docs snippet commands") == []
    assert "billing-engine" in taxonomy.infer_areas("Fix charge capture retry")


def _claim(text: str, evidence_ids: list, origin: str = "model") -> dict:
    return {
        "id": "CL-0001",
        "section": "gotchas",
        "text": text,
        "final_text": None,
        "confidence": "high",
        "claim_type": "rule",
        "origin": origin,
        "verification": "llm",
        "verification_note": None,
        "status": "pending",
        "evidence_ids": evidence_ids,
    }


def test_validate_ids_drops_unknown_evidence() -> None:
    claims = [_claim("The DLQ replay is manual.", ["EV-0001", "EV-9999"])]
    kept, dropped = verify.validate_ids(claims, {"EV-0001"})
    assert len(kept) == 1
    assert kept[0]["evidence_ids"] == ["EV-0001"]
    assert dropped == []

    kept, dropped = verify.validate_ids([_claim("Invented claim.", ["EV-9999"])], {"EV-0001"})
    assert kept == []
    assert len(dropped) == 1
    assert "no cited evidence" in dropped[0]["drop_reason"].lower()


def test_confidence_never_upgrades_model_text_without_two_sources() -> None:
    single = _claim("A claim with one source.", ["EV-0001"])
    assert verify.confidence_for(single) == "medium"
    double = _claim("A claim with two sources.", ["EV-0001", "EV-0002"])
    assert verify.confidence_for(double) == "high"


def test_traceability_export_defuses_spreadsheet_formulas() -> None:
    claims = [_claim("=HYPERLINK(\"http://evil\",\"click\")", ["EV-0001"])]
    index = {
        "EV-0001": {
            "id": "EV-0001",
            "source_type": "pull_request",
            "source_label": "PR",
            "title": "Replay script",
            "body": "Replay is manual.",
            "author": "Priya Raman",
            "occurred_at": "2026-09-01T10:00:00+00:00",
            "url": "https://example.test/1",
        }
    }
    csv_text = render_traceability_csv(traceability_rows(claims, index))
    assert csv_text.splitlines()[0].startswith("claim_id,section,section_label")
    assert "'=HYPERLINK" in csv_text
    assert "EV-0001" in csv_text


def test_traceability_marks_claims_without_citations() -> None:
    rows = traceability_rows([_claim("No citation here.", [])], {})
    assert len(rows) == 1
    assert rows[0]["evidence_excerpt"] == "(no evidence cited)"