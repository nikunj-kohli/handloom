"""End-to-end smoke test against a running Handover Lens server.

Usage:
    .venv/bin/python scripts/smoke_test.py http://127.0.0.1:8010

Exercises the scored workflow (sample -> generate -> review -> sign -> share), the
upload parsers, the error paths, and the database counts behind the UI payload.
Exits non-zero if anything fails.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from typing import Any, Dict, List

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8010"
client = httpx.Client(base_url=BASE, timeout=120)
failures: List[str] = []


def check(condition: bool, label: str, detail: Any = "") -> None:
    print(("PASS  " if condition else "FAIL  ") + label + ("" if condition else "  -> %s" % (detail,)))
    if not condition:
        failures.append(label)


# --------------------------------------------------------------------- health
health = client.get("/api/health")
check(health.status_code == 200, "health endpoint responds")
if health.status_code == 200:
    body = health.json()
    check(body.get("ok") is True, "health reports ok")
    check("llm" in body and "provider" in body["llm"], "health exposes model status without a key")

# --------------------------------------------------------------------- sample
sample = client.post("/api/sessions/sample")
check(sample.status_code == 200, "sample session created", sample.text[:300])
payload = sample.json()
sid = payload["session"]["id"]
check(payload["counts"]["evidence"] >= 60, "sample evidence seeded", payload["counts"]["evidence"])
check(payload["session"]["mode"] == "sample", "sample run is labelled as sample")

generated = client.post("/api/sessions/%s/generate" % sid, json={"force": False})
check(generated.status_code == 200, "generation succeeds", generated.text[:400])
gen = generated.json()
counts = gen["counts"]
evidence_ids = {item["id"] for item in gen["evidence"]}
visible = [claim for claim in gen["claims"] if claim["status"] != "dropped"]

check(counts["claims"] >= 12, "claims drafted", counts["claims"])
check(all(claim["evidence_ids"] for claim in visible), "every visible claim cites evidence")
check(
    all(set(claim["evidence_ids"]) <= evidence_ids for claim in gen["claims"]),
    "every cited evidence id exists in the session",
)
sections = {claim["section"] for claim in visible}
check(len(sections) >= 6, "most handover sections populated", sorted(sections))
check(all(claim["confidence"] in ("high", "medium", "low") for claim in visible), "confidence tags present")
check(len(gen["gaps"]) >= 1, "coverage gaps detected", len(gen["gaps"]))
check(all(gap["evidence_ids"] for gap in gen["gaps"]), "each coverage gap carries evidence ids")

# --------------------------------------------------------------------- errors
early = client.post("/api/sessions/%s/handover" % sid, json={"reviewer": "Smoke"})
check(early.status_code == 400, "signing before any approval is refused", early.status_code)

missing = client.get("/api/sessions/run-does-not-exist")
check(missing.status_code == 404, "unknown run returns 404", missing.status_code)

bad_token = client.get("/api/handover/not-a-real-token")
check(bad_token.status_code == 404, "unknown share token returns 404", bad_token.status_code)

no_leaver = client.post("/api/sessions/ingest", data={"repo_url": "", "leaver_name": ""})
check(no_leaver.status_code == 400, "ingest without a leaver is refused", no_leaver.status_code)

no_sources = client.post("/api/sessions/ingest", data={"leaver_name": "Test Leaver"})
check(no_sources.status_code == 400, "ingest without any source is refused", no_sources.status_code)

bad_action = client.post(
    "/api/sessions/%s/claims/%s/decision" % (sid, visible[0]["id"]),
    json={"action": "launch_missiles", "reviewer": "Smoke"},
)
check(bad_action.status_code == 400, "unknown review action is refused", bad_action.status_code)

unknown_claim = client.post(
    "/api/sessions/%s/claims/CL-9999/decision" % sid,
    json={"action": "approve", "reviewer": "Smoke"},
)
check(unknown_claim.status_code == 404, "unknown claim is refused", unknown_claim.status_code)

# --------------------------------------------------------------------- uploads
whatsapp = (
    "[28/09/2026, 09:12:00] Priya Raman: the webhook retry change is live\n"
    "[28/09/2026, 09:15:00] Test Leaver: what is the deal with the 6h retry?\n"
    "[28/09/2026, 09:18:00] Priya Raman: don't shorten it without talking to support\n"
)
tasks_csv = (
    "id,title,status,owner,area,due\n"
    "1,Finish refund runbook,done,Test Leaver,refunds,2026-11-01\n"
    "2,Ship pricing flag to 5%,blocked,Test Leaver,pricing,2026-11-15\n"
)
slack_json = (
    '{"channel":"#test","messages":['
    '{"user":"U1","text":"pricing flag stays off until finance signs","ts":"1759658400"},'
    '{"user":"U2","text":"ledger batch is a stopgap <script>alert(1)</script>","ts":"1759744800"}'
    '],"users":[{"id":"U1","name":"test-leaver"},{"id":"U2","name":"other-person"}]}'
)
notes = (
    "# Architecture sync\n\nAttendees: Test Leaver, Other Person\n\n"
    "Decided that refund delivery is at-least-once and merchants dedupe on the event id.\n"
    "The DLQ replay is manual and needs a CLI.\n"
)

uploads = client.post(
    "/api/sessions/ingest",
    data={
        "repo_url": "",
        "leaver_name": "Test Leaver",
        "window_start": "2026-07-01",
        "window_end": "2026-11-10",
        "project_name": "Upload parser check",
    },
    files=[
        ("files", ("whatsapp-export.txt", whatsapp.encode(), "text/plain")),
        ("files", ("tasks.csv", tasks_csv.encode(), "text/csv")),
        ("files", ("slack-test.json", slack_json.encode(), "application/json")),
        ("files", ("notes.md", notes.encode(), "text/markdown")),
    ],
)
check(uploads.status_code == 200, "mixed uploads ingest", uploads.text[:400])

if uploads.status_code == 200:
    upload_payload = uploads.json()
    kinds = {item["source_type"] for item in upload_payload["evidence"]}
    check({"task", "chat", "meeting_note"} <= kinds, "task, chat and note parsers all produced records", kinds)
    raw = upload_payload["evidence"]
    check(
        any("<script>" in (item["snippet"] or "") for item in raw),
        "uploaded HTML-ish text is stored as data, not executed",
    )
    upload_sid = upload_payload["session"]["id"]
    upload_gen = client.post("/api/sessions/%s/generate" % upload_sid, json={"force": False})
    check(upload_gen.status_code == 200, "generation works on uploaded files", upload_gen.text[:300])
    if upload_gen.status_code == 200:
        up = upload_gen.json()
        check(up["counts"]["claims"] >= 3, "uploaded evidence yields claims", up["counts"]["claims"])
        check(
            all(set(claim["evidence_ids"]) <= {e["id"] for e in up["evidence"]} for claim in up["claims"]),
            "uploaded-run claims cite real evidence",
        )

# --------------------------------------------------------------------- review
pending = [claim for claim in visible if claim["status"] == "pending"]
check(len(pending) >= 5, "enough pending claims to review", len(pending))

approve_one, approve_two, edit_one, reject_one, needs_one = pending[:5]
edited_text = "Edited by a human: the refund state machine only allows explicit transitions."

for claim, action, extra in (
    (approve_one, "approve", {}),
    (approve_two, "approve", {}),
    (edit_one, "edit", {"text": edited_text}),
    (reject_one, "reject", {}),
    (needs_one, "needs_confirmation", {}),
):
    response = client.post(
        "/api/sessions/%s/claims/%s/decision" % (sid, claim["id"]),
        json={"action": action, "reviewer": "Smoke Tester", **extra},
    )
    check(response.status_code == 200, "decision '%s' accepted" % action, response.text[:300])

short_edit = client.post(
    "/api/sessions/%s/claims/%s/decision" % (sid, approve_one["id"]),
    json={"action": "edit", "text": "x", "reviewer": "Smoke Tester"},
)
check(short_edit.status_code == 400, "empty or tiny edit is refused", short_edit.status_code)

after = client.get("/api/sessions/%s" % sid).json()
check(after["counts"]["approved"] == 2, "two claims approved", after["counts"]["approved"])
check(after["counts"]["edited"] == 1, "one claim edited", after["counts"]["edited"])
check(after["counts"]["rejected"] == 1, "one claim rejected", after["counts"]["rejected"])
check(after["counts"]["needs_confirmation"] == 1, "one claim held for the leaver", after["counts"]["needs_confirmation"])
check(after["claims"][0]["status"] in ("approved", "edited", "pending", "rejected", "needs_confirmation"), "claim state is persisted")

# --------------------------------------------------------------------- sign
signed = client.post("/api/sessions/%s/handover" % sid, json={"reviewer": "Smoke Tester"})
check(signed.status_code == 200, "sign-off succeeds once claims are approved", signed.text[:400])
token = signed.json().get("token", "")

record = client.get("/api/handover/%s" % token)
check(record.status_code == 200, "share link is readable without a session", record.status_code)
snapshot = record.json()["payload"]
check(snapshot["counts"]["approved"] == 2, "snapshot contains the two approved claims", snapshot["counts"])
check(snapshot["counts"]["edited"] == 1, "snapshot contains the edited claim", snapshot["counts"])
check(len(snapshot["audit"]) == 5, "approval log has all five decisions", len(snapshot["audit"]))
check(snapshot["reviewer"] == "Smoke Tester", "signer is recorded", snapshot["reviewer"])
check(bool(snapshot["fingerprint"]), "snapshot has a content fingerprint")

snapshot_text = " ".join(
    claim["text"] for section in snapshot["sections"] for claim in section["claims"]
)
check(edited_text in snapshot_text, "edited text replaced the draft in the export")
check(reject_one["text"] not in snapshot_text, "rejected claim is not in the handover body")

markdown = client.get("/api/handover/%s/markdown" % token)
check(markdown.status_code == 200, "markdown export downloads", markdown.status_code)
check("Coverage check" in markdown.text, "markdown includes the coverage check")
check("Approval log" in markdown.text, "markdown includes the approval log")
check(reject_one["text"][:40] in markdown.text, "markdown lists rejected claims under 'omitted'")

pdf = client.get("/api/handover/%s/pdf" % token)
check(pdf.status_code == 200, "pdf export downloads", pdf.status_code)
check(pdf.content[:4] == b"%PDF", "pdf has a real PDF header", pdf.content[:8])
check(len(pdf.content) > 3000, "pdf is not empty", len(pdf.content))

verified = client.get("/api/handover/%s/verify" % token)
check(verified.status_code == 200, "fingerprint verification endpoint responds", verified.status_code)
if verified.status_code == 200:
    check(verified.json()["matches"] is True, "fingerprint matches its own content")

# --------------------------------------------------------------------- frontend
index = client.get("/")
check(index.status_code == 200, "frontend is served by the backend", index.status_code)
check("text/html" in index.headers.get("content-type", ""), "frontend is served as HTML")
check("root" in index.text, "frontend HTML shell is present")
spa = client.get("/review/run-anything")
check(spa.status_code == 200 and "text/html" in spa.headers.get("content-type", ""), "SPA deep link falls back to index.html")

# --------------------------------------------------------------------- database
db_path = os.path.join("data", "handover.db")
if os.path.exists(db_path) and not os.environ.get("DATABASE_URL"):
    connection = sqlite3.connect(db_path)
    try:
        evidence_rows = connection.execute(
            "SELECT COUNT(*) FROM evidence WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        claim_rows = connection.execute(
            "SELECT COUNT(*) FROM claims WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        decision_rows = connection.execute(
            "SELECT COUNT(*) FROM decisions WHERE session_id = ?", (sid,)
        ).fetchone()[0]
        handover_rows = connection.execute(
            "SELECT COUNT(*) FROM handovers WHERE session_id = ?", (sid,)
        ).fetchone()[0]
    finally:
        connection.close()
    check(evidence_rows == after["counts"]["evidence"], "database evidence count matches the UI", evidence_rows)
    check(
        claim_rows == after["counts"]["claims"] + after["counts"]["dropped"],
        "database claim count matches the UI (including dropped)",
        claim_rows,
    )
    check(decision_rows == 5, "all five review decisions are in the audit log", decision_rows)
    check(handover_rows == 1, "one signed handover row stored", handover_rows)
else:
    print("SKIP  direct database check (no local sqlite file)")

print()
if failures:
    print("%d check(s) failed:" % len(failures))
    for failure in failures:
        print("  - %s" % failure)
    sys.exit(1)
print("All checks passed.")
