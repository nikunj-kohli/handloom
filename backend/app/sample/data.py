"""Synthetic sample project: fictional people, commits, chats, tasks and notes.

Everything here is invented for the demo — no real repository or person is referenced.
It exists so a judge can see the whole workflow with no token, no key and no setup.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..analysis import taxonomy

REPO = "helios-payments/api"
PROJECT_NAME = "Helios Payments — payments platform handover"
LEAVER_NAME = "Priya Raman"
LEAVER_EMAIL = "priya.raman@helios.example"
WINDOW_START = "2026-07-15T00:00:00Z"
WINDOW_END = "2026-11-08T23:59:59Z"
SAMPLE_NOTE = (
    "Synthetic dataset: a fictional payments team, invented commits, chats and tasks. "
    "It is labelled as sample data everywhere it appears."
)


def _commit(
    sha: str,
    day: str,
    title: str,
    body: str,
    files: List[str],
    areas: Optional[List[str]] = None,
    author: str = "Priya Raman",
    login: str = "priya-raman",
) -> Dict[str, Any]:
    return {
        "source_type": "git_commit",
        "source_label": REPO,
        "external_id": sha,
        "title": title,
        "body": body,
        "author": author,
        "occurred_at": "%sT10:00:00Z" % day,
        "url": None,
        "areas": areas or taxonomy.infer_areas(title + " " + body, files),
        "metadata": {"sha": sha, "login": login, "files": files, "branch": "main"},
    }


def _pr(
    number: int,
    day: str,
    title: str,
    body: str,
    state: str,
    author: str = "Priya Raman",
    login: str = "priya-raman",
    areas: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "source_type": "pull_request",
        "source_label": REPO,
        "external_id": "PR #%d" % number,
        "title": title,
        "body": body,
        "author": author,
        "occurred_at": "%sT09:30:00Z" % day,
        "url": None,
        "areas": areas or taxonomy.infer_areas(title + " " + body),
        "metadata": {"number": number, "state": state, "login": login, "labels": [], "base": "main"},
    }


def _review(
    number: int,
    day: str,
    pr_title: str,
    body: str,
    review_state: str,
    author: str = "Priya Raman",
    login: str = "priya-raman",
) -> Dict[str, Any]:
    return {
        "source_type": "review",
        "source_label": REPO,
        "external_id": "review:%d:%s" % (number, day),
        "title": "Review on PR #%d: %s" % (number, pr_title),
        "body": body,
        "author": author,
        "occurred_at": "%sT16:20:00Z" % day,
        "url": None,
        "areas": taxonomy.infer_areas(pr_title + " " + body),
        "metadata": {"pr": number, "state": review_state, "login": login},
    }


def _issue(
    number: int,
    day: str,
    title: str,
    body: str,
    state: str,
    assignees: List[str],
    author: str = "Priya Raman",
) -> Dict[str, Any]:
    return {
        "source_type": "issue",
        "source_label": REPO,
        "external_id": "Issue #%d" % number,
        "title": title,
        "body": body,
        "author": author,
        "occurred_at": "%sT11:00:00Z" % day,
        "url": None,
        "areas": taxonomy.infer_areas(title + " " + body),
        "metadata": {"number": number, "state": state, "assignees": assignees, "labels": []},
    }


def _task(
    title: str,
    status: str,
    owner: str,
    area: str,
    due: Optional[str] = None,
    notes: str = "",
) -> Dict[str, Any]:
    body = "Status: %s; Owner: %s; Area: %s" % (status, owner, area)
    if due:
        body += "; Due: %s" % due
    if notes:
        body += ".\n" + notes
    return {
        "source_type": "task",
        "source_label": "tasks.csv",
        "external_id": "tasks.csv:%s" % title.replace(" ", "-").lower()[:50],
        "title": title,
        "body": body,
        "author": owner,
        "occurred_at": None,
        "url": None,
        "areas": taxonomy.infer_areas("%s %s" % (area, title)),
        "metadata": {"parser": "tasks-csv", "status": status, "owner": owner, "area": area, "due": due},
    }


def _chat(day: str, time: str, author: str, body: str, label: str, channel: str) -> Dict[str, Any]:
    return {
        "source_type": "chat",
        "source_label": label,
        "external_id": "%s#%s-%s" % (label, day, time.replace(":", "")),
        "title": body[:110],
        "body": body,
        "author": author,
        "occurred_at": "%sT%s:00Z" % (day, time),
        "url": None,
        "areas": taxonomy.infer_areas(body),
        "metadata": {"parser": "whatsapp" if "WhatsApp" in label else "slack", "channel": channel},
    }


def _note(day: str, title: str, body: str, attendees: List[str]) -> Dict[str, Any]:
    return {
        "source_type": "meeting_note",
        "source_label": "meeting-notes.md",
        "external_id": "meeting-notes.md:%s" % day,
        "title": title,
        "body": body,
        "author": attendees[0] if attendees else None,
        "occurred_at": "%sT15:00:00Z" % day,
        "url": None,
        "areas": taxonomy.infer_areas(title + " " + body),
        "metadata": {"parser": "text", "attendees": attendees},
    }


def _doc(day: str, title: str, body: str, path: str) -> Dict[str, Any]:
    return {
        "source_type": "document",
        "source_label": path,
        "external_id": path,
        "title": title,
        "body": body,
        "author": "Priya Raman",
        "occurred_at": "%sT12:00:00Z" % day,
        "url": None,
        "areas": taxonomy.infer_areas(title + " " + body, [path]),
        "metadata": {"parser": "docs", "path": path},
    }


EVIDENCE: List[Dict[str, Any]] = [
    # ---------------------------------------------------------------- commits
    _commit(
        "a1f9c2e",
        "2026-07-18",
        "Add idempotency keys to charge capture",
        "Charges can be retried by the merchant gateway, so capture now writes a Redis SETNX key "
        "per merchant and idempotency key before touching the ledger, with a 24 hour TTL.\n"
        "Tradeoff: a database unique index would be durable, but the write latency on the capture "
        "path was unacceptable (p99 +40ms). Known limit: after the 24 hour TTL a late retry can "
        "double-capture, so support has to check before refunding.",
        ["services/billing/charge.py", "services/billing/idempotency.py"],
    ),
    _commit(
        "b7d4e10",
        "2026-07-29",
        "Fix rounding drift in proration estimator",
        "Proration used floating point cents and lost a cent on some annual plans. It now works in "
        "integer minor units with banker's rounding at line level. Two merchants were under-billed "
        "by one cent per cycle, so no customer refunds were needed.",
        ["services/billing/proration.py"],
    ),
    _commit(
        "c3a8f52",
        "2026-08-04",
        "Refunds: make state transitions explicit",
        "Implicit transitions were reachable from the admin tool, which let an operator jump "
        "straight to settled. The refund state machine now only allows requested -> approved -> "
        "settled and requested -> rejected. Anything else raises, deliberately.",
        ["services/refunds/state_machine.py"],
    ),
    _commit(
        "d9b1c07",
        "2026-08-11",
        "Add double-entry guard for refund postings",
        "Every refund posting writes a debit and a credit leg in one transaction. The guard rejects "
        "unbalanced entries, because a single-leg posting silently breaks ledger reconciliation.",
        ["services/ledger/entries.py"],
    ),
    _commit(
        "e4c7a31",
        "2026-08-19",
        "Backfill currency metadata for legacy invoices",
        "One-off job that fills currency for invoices created before the multi-currency migration. "
        "It is idempotent by invoice id and safe to re-run; it skips rows that already carry currency.",
        ["jobs/backfill_currency.py"],
    ),
    _commit(
        "f2e6b48",
        "2026-09-02",
        "Webhook delivery: retry with exponential backoff",
        "Retries at 1m, 5m, 30m, 2h and 6h, then dead-letter. Six hours is deliberate: after that a "
        "merchant has usually reconciled by hand, and a late delivery does more harm than a missing one.",
        ["services/webhooks/dispatch.py"],
    ),
    _commit(
        "08a5d73",
        "2026-09-10",
        "Add dead-letter queue for failed webhooks",
        "DLQ rows keep the full payload and the failure reason. Replay is manual through a script, "
        "there is no UI yet, and that is the open operational gap.",
        ["services/webhooks/dlq.py"],
    ),
    _commit(
        "19c2f86",
        "2026-09-15",
        "Tighten webhook signature tolerance to 5 minutes",
        "During the September key rotation the old 15 minute tolerance let stale signed payloads "
        "through. It is 5 minutes now, and the rotation runbook has to be followed carefully because "
        "the old key must stay valid for one full tolerance window.",
        ["services/webhooks/signature.py"],
        areas=["webhooks", "infra"],
    ),
    _commit(
        "2ad8e94",
        "2026-09-24",
        "Pricing: introduce tier resolver behind pricing_v2 flag",
        "Tiers resolve at request time and are cached for 60 seconds. The flag defaults to off; "
        "finance sign-off is the gate, not engineering.",
        ["services/pricing/tiers.py"],
        areas=["pricing"],
    ),
    _commit(
        "3be1f45",
        "2026-10-07",
        "Fix tax rounding on partial refunds",
        "Tax is computed per line item and then summed, not on the refund total. Legal signed off on "
        "this order of operations, so do not simplify it to a total-level calculation.",
        ["services/refunds/settlement.py"],
    ),
    _commit(
        "4cf6a28",
        "2026-10-14",
        "Alert when webhook DLQ depth exceeds 100",
        "Terraform alert on DLQ depth. If it fires the replay is still manual, so the alert routes to "
        "the on-call channel and points at the runbook.",
        ["infra/alerts/webhooks.tf"],
        areas=["infra", "webhooks"],
    ),
    _commit(
        "5da3b71",
        "2026-10-21",
        "Reduce ledger write batch to 500",
        "A batch of 2000 caused lock contention at month end, so the batch is 500 while we wait. "
        "That is a stopgap; the real fix is partitioning postings by account id, which needs a "
        "migration and has not been run in production.",
        ["services/ledger/batch.py"],
        areas=["ledger"],
    ),
    _commit(
        "6eb9c04",
        "2026-10-30",
        "Add refund runbook and on-call playbook",
        "Documents the refund state machine, the DLQ replay and the month-end checklist. The state "
        "machine diagram in the old wiki is out of date, trust the code.",
        ["docs/refund-runbook.md", "docs/oncall-playbook.md"],
        areas=["refunds", "docs"],
    ),
    _commit(
        "7fc2d66",
        "2026-11-04",
        "Document pricing v2 rollout and grandfathering gap",
        "Memo for finance covering the tier model, the rollout flag and the grandfathering open item. "
        "Annual contracts signed before July are not covered by the tier model yet.",
        ["docs/pricing-v2.md"],
        areas=["pricing", "docs"],
    ),
    _commit(
        "8ad4e39",
        "2026-08-26",
        "Add admin credit issuance endpoint",
        "Adds a POST endpoint that issues account credits from the admin tool. Audit logging is not "
        "included in this change.",
        ["services/admin/credits.py"],
        areas=["admin-tools"],
        author="Arjun Mehta",
        login="arjun-mehta",
    ),
    _commit(
        "9be5f12",
        "2026-09-08",
        "Route ledger reads to replica",
        "Ledger reads go to the replica to take pressure off the primary. Replication lag is about "
        "two seconds, which is fine for reporting and not fine for read-after-write.",
        ["services/ledger/replica.py"],
        areas=["ledger"],
        author="Dana Osei",
        login="dana-osei",
    ),
    _commit(
        "0cf7a85",
        "2026-10-05",
        "Batch email digests per tenant",
        "Batches notification digests per tenant to cut provider calls. No throttling yet, so a large "
        "tenant can still burst through the provider limit.",
        ["services/notifications/digest.py"],
        areas=["notifications"],
        author="Tomas Ruiz",
        login="tomas-ruiz",
    ),
    _commit(
        "1da8b96",
        "2026-10-19",
        "Partition ledger postings by account (WIP)",
        "Work in progress behind a flag. The migration exists but has not been run in production; "
        "month-end contention is still handled by the smaller batch size.",
        ["services/ledger/partition.py"],
        areas=["ledger"],
        author="Dana Osei",
        login="dana-osei",
    ),
    # ---------------------------------------------------------------- pull requests
    _pr(
        412,
        "2026-07-17",
        "Idempotency keys for charge capture",
        "Charges get a per-merchant idempotency key before the ledger write. We chose Redis SETNX "
        "over a database unique index because capture latency matters more than durability here. "
        "The 24 hour TTL is a known limit and is documented in the runbook.",
        "merged",
        areas=["billing-engine"],
    ),
    _pr(
        428,
        "2026-08-03",
        "Refund state machine v2",
        "Makes refund transitions explicit and rejects anything the diagram does not allow. "
        "Reviewed by Arjun Mehta and Dana Osei. The admin tool must not write refund states directly.",
        "merged",
        areas=["refunds"],
    ),
    _pr(
        455,
        "2026-09-01",
        "Webhook retries and dead-letter queue",
        "Delivery is at-least-once, so merchants must dedupe on the event id we send. "
        "Five retries then DLQ; replay stays manual until ops gets a CLI.",
        "merged",
        areas=["webhooks"],
    ),
    _pr(
        431,
        "2026-10-06",
        "Tax rounding fix for partial refunds",
        "Rounds tax per line item and then sums. Legal confirmed this order of operations for partial "
        "refunds; changing it needs their sign-off again.",
        "merged",
        areas=["refunds"],
    ),
    _pr(
        470,
        "2026-09-26",
        "Tier resolver behind pricing_v2 flag",
        "Adds the resolver and the flag, default off. Do not enable it until finance signs the pricing "
        "memo; the blocking item is grandfathering for annual contracts signed before July.",
        "open",
        areas=["pricing"],
    ),
    _pr(
        402,
        "2026-08-18",
        "Backfill currency metadata",
        "One-off backfill, idempotent by invoice id, safe to re-run. Ran on staging twice with no "
        "duplicate rows.",
        "merged",
        areas=["billing-engine"],
    ),
    # ---------------------------------------------------------------- reviews by the leaver
    _review(
        458,
        "2026-08-27",
        "Admin tool: manual credit issuance",
        "Requesting changes: this needs an audit trail before it ships. Every manual credit has to "
        "record who issued it and why, otherwise finance cannot reconcile the account.",
        "CHANGES_REQUESTED",
    ),
    _review(
        461,
        "2026-09-09",
        "Ledger read replica routing",
        "Approved with one condition: refund reads stay on the primary. Replicas lag about two "
        "seconds and a stale read right after a refund write will confuse support.",
        "APPROVED",
    ),
    _review(
        476,
        "2026-10-06",
        "Notifications: email digest batching",
        "Requesting changes: throttle per tenant or the email provider will rate limit us during "
        "month end, when digests and receipts collide.",
        "CHANGES_REQUESTED",
    ),
    # ---------------------------------------------------------------- issues
    _issue(
        398,
        "2026-09-12",
        "Webhook DLQ replay is manual-only",
        "Ops asked for a CLI so they can replay a DLQ batch without waking an engineer. Right now the "
        "script takes a raw JSON file and nobody outside the team has run it.",
        "open",
        ["Priya Raman"],
    ),
    _issue(
        405,
        "2026-09-27",
        "Pricing v2: finance sign-off pending",
        "Meera from finance needs the tier memo and an answer on grandfathering before the flag can be "
        "enabled. Engineering work is done.",
        "open",
        ["Priya Raman"],
    ),
    _issue(
        410,
        "2026-08-21",
        "Legacy currency backfill left dangling rows",
        "Some invoices had a currency code but no rate. Fixed by making the backfill idempotent and "
        "re-running it; no manual cleanup was needed.",
        "closed",
        ["Priya Raman"],
    ),
    _issue(
        418,
        "2026-10-20",
        "Ledger lock contention spikes at month end",
        "A batch of 2000 is too large. The smaller batch is a stopgap; partitioning by account id is the "
        "real fix and the migration is not run in production.",
        "open",
        [],
        author="Dana Osei",
    ),
    _issue(
        422,
        "2026-10-22",
        "Admin credit issuance has no audit trail",
        "Manual credits from the admin tool cannot be traced back to an operator. Raised in review on "
        "PR #458 and still open.",
        "open",
        ["Arjun Mehta"],
        author="Dana Osei",
    ),
    # ---------------------------------------------------------------- tasks
    _task(
        "Ship pricing v2 flag to 5% of accounts",
        "blocked",
        "Priya Raman",
        "pricing",
        "2026-11-15",
        "Blocked on finance sign-off (Meera) and the grandfathering decision for annual contracts.",
    ),
    _task(
        "Webhook DLQ replay CLI",
        "in_progress",
        "Priya Raman",
        "webhooks",
        "2026-11-20",
        "Script works; needs a safer input path before ops can use it.",
    ),
    _task("Finish refund runbook", "done", "Priya Raman", "docs", None, "Published in docs/refund-runbook.md."),
    _task(
        "Month-end ledger load test",
        "open",
        "Priya Raman",
        "ledger",
        "2026-11-30",
        "Needed before the partition migration can ship.",
    ),
    _task("On-call handover doc", "done", "Priya Raman", "docs", None, "Covers DLQ replay and the month-end checklist."),
    _task(
        "Finance sign-off on tier pricing",
        "waiting",
        "Priya Raman",
        "pricing",
        "2026-11-12",
        "Meera needs the memo and the grandfathering answer.",
    ),
    _task("Admin audit trail", "in_progress", "Arjun Mehta", "admin-tools", "2026-11-25", "Requested in review on PR #458."),
    _task("Currency backfill verification", "done", "Priya Raman", "billing-engine", None, "Re-ran twice, no duplicates."),
    # ---------------------------------------------------------------- WhatsApp export
    _chat(
        "2026-09-28",
        "09:12",
        "Priya Raman",
        "the webhook retry change is live, watch the DLQ tomorrow morning",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-09-28",
        "09:15",
        "Arjun Mehta",
        "will do. what's the deal with the 6h last retry?",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-09-28",
        "09:18",
        "Priya Raman",
        "deliberate. after 6h the merchant has usually reconciled manually. don't shorten it without talking to support",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-10-03",
        "18:40",
        "Priya Raman",
        "pricing v2 flag is off by default, finance sign off is the gate, not engineering",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-10-03",
        "18:42",
        "Arjun Mehta",
        "who signs?",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-10-03",
        "18:44",
        "Priya Raman",
        "Meera in finance. she wants the refund edge cases documented first",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-10-15",
        "11:05",
        "Priya Raman",
        "don't touch ledger batch size without a load test, month end is the only time it matters",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat("2026-10-15", "11:07", "Arjun Mehta", "noted", "whatsapp-export.txt", "WhatsApp · Priya and Arjun"),
    _chat(
        "2026-10-15",
        "11:09",
        "Priya Raman",
        "also the currency backfill job is safe to rerun, it's idempotent by invoice id",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-10-22",
        "14:31",
        "Arjun Mehta",
        "admin credit tool shipped without audit trail btw",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-11-02",
        "08:50",
        "Priya Raman",
        "refund runbook is in docs/. the state machine diagram is out of date, trust the code",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    _chat(
        "2026-11-05",
        "19:22",
        "Priya Raman",
        "last thing: tax rounding is per line item then summed. legal signed off on that",
        "whatsapp-export.txt",
        "WhatsApp · Priya and Arjun",
    ),
    # ---------------------------------------------------------------- Slack
    _chat(
        "2026-09-11",
        "10:04",
        "Dana Osei",
        "month-end ledger lock contention again, batch of 2000 was too big",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-09-11",
        "10:11",
        "Priya Raman",
        "dropping to 500, it's a stopgap. real fix is partitioning by account id, needs a migration",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-07",
        "12:20",
        "Tomas Ruiz",
        "notifications digest is hammering the email provider",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-07",
        "12:26",
        "Priya Raman",
        "throttle per tenant, I left comments on #476",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-14",
        "17:02",
        "Priya Raman",
        "added DLQ depth alert at 100, if it fires the replay is manual",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-20",
        "09:35",
        "Dana Osei",
        "who owns pricing v2 rollout?",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-20",
        "09:38",
        "Priya Raman",
        "me until the 21st, then it's open. flag stays off until finance signs",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-28",
        "15:44",
        "Arjun Mehta",
        "read replica routing: saw a stale read right after refund write",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-10-28",
        "15:47",
        "Priya Raman",
        "expected, replicas lag about 2s. route refund reads to primary",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-11-04",
        "11:12",
        "Meera Iyer",
        "we need the tier pricing memo before enabling anything",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-11-04",
        "11:20",
        "Priya Raman",
        "memo is in docs/pricing-v2.md, the open item is grandfathering for annual contracts",
        "slack-payments-platform.json",
        "#payments-platform",
    ),
    _chat(
        "2026-11-06",
        "16:05",
        "Tomas Ruiz",
        "refund webhook to merchants doesn't fire for partial refunds under 1 unit",
        "slack-incidents.json",
        "#incidents",
    ),
    _chat(
        "2026-11-06",
        "16:09",
        "Priya Raman",
        "known, it's the minimum-amount guard. documented in the runbook, not fixed",
        "slack-incidents.json",
        "#incidents",
    ),
    # ---------------------------------------------------------------- meeting notes
    _note(
        "2026-09-17",
        "Architecture sync — webhook delivery",
        "Attendees: Priya Raman, Dana Osei, Arjun Mehta, Tomas Ruiz.\n"
        "Decided that webhook delivery is at-least-once and merchants dedupe on the event id we send.\n"
        "DLQ replay stays manual for now; a CLI is the follow-up (issue #398).\n"
        "Action: Priya to document the retry ladder and the signature tolerance in the runbook.",
        ["Priya Raman", "Dana Osei", "Arjun Mehta", "Tomas Ruiz"],
    ),
    _note(
        "2026-10-09",
        "Incident retro — webhook backlog",
        "Attendees: Priya Raman, Dana Osei, Tomas Ruiz.\n"
        "Cause: signature verification was too strict during the key rotation window, so valid payloads "
        "were rejected and retried into the DLQ.\n"
        "Fix shipped: tolerance widened to 5 minutes and the rotation runbook updated.\n"
        "Open action: a key rotation runbook that does not depend on one engineer (Priya).",
        ["Priya Raman", "Dana Osei", "Tomas Ruiz"],
    ),
    _note(
        "2026-10-01",
        "Pricing v2 kickoff",
        "Attendees: Priya Raman, Meera Iyer, Dana Osei.\n"
        "Tiers resolve at request time with a 60 second cache; that staleness is acceptable to finance.\n"
        "Grandfathering for annual contracts signed before July is unresolved and blocks enablement.\n"
        "Decided the rollout gate is finance sign-off, not an engineering decision.",
        ["Priya Raman", "Meera Iyer", "Dana Osei"],
    ),
    # ---------------------------------------------------------------- documents
    _doc(
        "2026-10-30",
        "Refund runbook",
        "Refund state machine\n"
        "Only requested -> approved -> settled and requested -> rejected are allowed. The admin tool must "
        "not write refund states directly.\n\n"
        "Tax rounding\n"
        "Tax is computed per line item then summed. Legal signed off on this; do not change the order "
        "without legal review.\n\n"
        "Known gaps\n"
        "Merchant refund webhooks do not fire for partial refunds under one minor unit. This is the "
        "minimum-amount guard and it is documented here rather than fixed.",
        "docs/refund-runbook.md",
    ),
    _doc(
        "2026-11-04",
        "Pricing v2 memo",
        "Tier resolution happens at request time and is cached for 60 seconds.\n"
        "Open item: annual contracts signed before July are not covered by the tier model, and "
        "grandfathering needs a finance decision.\n"
        "Finance (Meera Iyer) must sign the memo before the pricing_v2 flag is enabled for any account.",
        "docs/pricing-v2.md",
    ),
    _doc(
        "2026-10-30",
        "On-call playbook",
        "Month end checklist: watch ledger lock contention, keep the write batch at 500, and check the "
        "DLQ depth alert threshold of 100.\n"
        "Webhook DLQ replay is manual. The script takes a JSON file and is documented in the refund runbook.\n"
        "Key rotation: rotate, keep the old key valid for one full five minute tolerance window, then remove it.",
        "docs/oncall-playbook.md",
    ),
]


def describe() -> Dict[str, Any]:
    from collections import Counter

    counts = Counter(item["source_type"] for item in EVIDENCE)
    return {
        "project_name": PROJECT_NAME,
        "repo": REPO,
        "leaver_name": LEAVER_NAME,
        "window_start": WINDOW_START,
        "window_end": WINDOW_END,
        "note": SAMPLE_NOTE,
        "record_count": len(EVIDENCE),
        "by_source": dict(counts),
    }
