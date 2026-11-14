---
title: Handover Lens
emoji: 🔎
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
---

# Handover Lens

Turn scattered engineering activity into a handover that a judge — or a successor — can check.

Scattered activity goes in (commits, pull requests, reviews, issues, chat exports, task CSVs, meeting
notes), a sectioned handover comes out, every claim points at a real record, and a human approves what
ships. No accounts, no OAuth, no walkthrough.

**The 60-second demo:** open the app, press **Try the sample project**. It loads a labelled synthetic
project and produces the full handover with no keys and no setup.

## What is actually different

| Property | How it works |
|---|---|
| Evidence first | A claim is stored only with evidence ids that exist in the session. Unknown ids are dropped. |
| Citation verification | Every claim is checked against the text it cites. Model claims get a second model pass; rule and quote claims get a deterministic check. Failures are dropped **and listed**, never hidden. |
| Coverage check | Areas the leaver touched that no claim mentions are listed with their records — the visible gap list. |
| Human sign-off gate | Approve, edit, reject or "needs the leaver to confirm". The export contains only approved or edited claims, plus an append-only approval log and a content fingerprint. |
| Works with zero keys | With no model key, a deterministic drafter quotes the records that carry rationale. The UI says which path ran. |

## Quick start

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

cd frontend && npm ci && npm run build && cd ..

.venv/bin/python -m uvicorn backend.app.main:app --port 8000
# open http://127.0.0.1:8000
```

Frontend hot reload instead of a build:

```bash
.venv/bin/python -m uvicorn backend.app.main:app --port 8000   # terminal 1
cd frontend && npm run dev                                      # terminal 2, http://127.0.0.1:5173
```

## Verify it (this is the real check)

```bash
.venv/bin/python scripts/smoke_test.py http://127.0.0.1:8000
```

The smoke test drives the scored workflow over HTTP: sample → generate → review decisions → sign →
share link → Markdown → PDF → fingerprint verify. It also exercises the upload parsers, the error
paths, and compares the database counts to the payload the UI renders. It exits non-zero on failure.

## How the pipeline works

```
ingest ──► normalise ──► rule extraction ──► cited drafting ──► verify ──► review ──► signed export
```

1. **Ingest** — GitHub REST (read-only, capped, cached) and uploads (txt, md, csv, WhatsApp export,
   Slack JSON). No clone, no git binary, no writes.
2. **Normalise** — every record becomes one shape: `id, source_type, source_label, external_id, title,
   body, author, occurred_at, url, areas[], metadata`.
3. **Rules** — ownership share per area, open work, people with context, coverage gaps. Deterministic.
4. **Drafting** — `decisions`, `gotchas` and `first_week` come from the configured model when there is a
   key, otherwise from the deterministic extractor. Both paths must cite evidence ids.
5. **Verify** — id validation, then support checking, then confidence from origin + source count.
6. **Review** — the human decision step, with the cited record one click away.
7. **Export** — a snapshot is frozen, fingerprinted and shared read-only as Markdown and PDF.

## Layout

```
backend/app/config.py      env + section list (single source of truth)
backend/app/db.py          engine, schema, query helpers
backend/app/store.py       every read/write; used by the API and the seeder
backend/app/security.py    rate limits, ids, spend guard, concurrency slots
backend/app/llm.py         provider-agnostic wrapper (Groq / Gemini / OpenAI / Anthropic / xAI)
backend/app/ingest/        file parsers + GitHub reader
backend/app/analysis/      taxonomy, rules, claim drafting, verification, export
backend/app/sample/        the synthetic demo dataset
backend/app/api.py         every HTTP route
frontend/src/pages/        Intake, Review, Handover
frontend/src/components/   claim cards, evidence panel, coverage panel, badges
scripts/smoke_test.py      end-to-end HTTP check
```

Conventions and non-regression rules live in `AGENTS.md`; the human-facing limits live in
`CONVENTIONS.md`.

## Configuration

Copy `.env.example` to `.env`. Everything is optional — the app is fully usable without any key.

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `auto` | `auto`, `groq`, `gemini`, `openai`, `anthropic`, `xai` or `offline` |
| `GROQ_API_KEY` / `XAI_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | unset | Server-side only; never sent to the browser. `auto` prefers Groq, then Gemini, OpenAI, Anthropic, xAI |
| `LLM_MODEL` | provider default | Override the model name |
| `DAILY_LLM_CALL_CAP` | `400` | Hard daily spend guard across all users |
| `GITHUB_TOKEN` | unset | Read-only; raises GitHub from 60 to 5,000 requests/hour |
| `DATABASE_URL` | local SQLite | Set to Postgres (Neon) in production |
| `SESSION_TTL_HOURS` | `72` | Uploaded chats and full evidence are deleted when the run expires |

## Limits enforced in code

Uploads 2 MB/file and 6 MB/request (8 files); GitHub reads 120 commits and 80 PRs; 2 concurrent
generations; heavy endpoints 8/minute/IP; 400 model calls/day; 72-hour session lifetime; every API
response is `no-store`. The frontend ships with a strict CSP and no inline event handlers.

## Tests

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q                                  # unit: matching, tagging, citation checks, CSV
.venv/bin/python scripts/smoke_test.py http://127.0.0.1:8000         # end-to-end over HTTP
```

## Deploy (Render, one service)

`render.yaml` builds the frontend and runs FastAPI, so one URL serves both — no CORS. Set
`GROQ_API_KEY`, `GITHUB_TOKEN` and `DATABASE_URL` in the dashboard (never in the repo). Health check
is `/api/health`; free instances sleep, so expect a cold start and keep a ping on it.

## What works, and what does not

Verified by `scripts/smoke_test.py` against a running server:

- sample project and live multi-source intake; upload parsers for txt, md, CSV, WhatsApp and Slack
- rule extraction (ownership share, open work, people) and the coverage check
- cited drafting on both paths, id validation, confidence tags, dropped-claim reporting
- review actions (approve / edit / reject / needs confirmation / reset) with an audit log
- signed export: read-only share link, Markdown, PDF, fingerprint verify
- **evidence search** across titles, text, authors and source labels, with area/source filters and a
  200-row page cap (server-enforced, not a frontend hint)
- **traceability CSV**: one row per claim/evidence pair, available from the live run and from a frozen
  signed snapshot, with spreadsheet formula injection defused
- rate limiting (429 under load), upload caps, error paths, SPA deep links

Known limitations:

- **No live Slack/Jira connectors.** Chats and tasks are imported as files, by design for Round 2.
- **No PDF-to-text ingestion.** PDF uploads are rejected with a clear message.
- **GitHub without a token** is limited to 60 requests/hour and skips commit file detail and review
  history; the UI shows a warning when that happens. Reviewers of *other people's* PRs are only read
  when a token is configured.
- **Single process.** In-memory rate limits and the sequential id allocation assume one web process.
- **No accounts by design.** Whoever holds a run link or a share link can read it; ids are 128-bit
  random. A run's evidence expires after 72 hours, but a signed share link is kept for 14 days so it
  still works after the run is gone. There is no per-user permission model.
- **Model drafting is verified against one live provider** (Groq, `openai/gpt-oss-120b`). Its free
  tier allows 8,000 tokens per minute, so rapid repeat generations fall back to the deterministic
  overlap check; the UI states which check ran. Gemini, OpenAI, Anthropic and xAI share the same
  adapter but have not been exercised with a key here.
- **No visual design or assistive-technology audit has been done.** Inputs are labelled, the search
  panel is keyboard reachable, and there are breakpoints, but nobody has reviewed it in a browser
  against a design reference or a screen reader.

## Round 3 commitments

1. **Gap Checker** — interview the leaver about the uncovered areas this version lists, and turn those
   answers into new cited evidence. Target: the leaver answers at least 8 targeted questions that
   appear as cited claims in the signed handover.
2. **Bus-factor Risk Radar** — team-wide view of single-owner areas, built on the ownership scoring
   already in `analysis/rules.py`. Target: flag every area with one committer and no reviewer in 90 days.
3. **Successor Q&A with citations** — ask the handover questions and get answers that cite records,
   plus a completeness score from successor feedback. This is where embeddings/pgvector land.

## Sample data notice

`backend/app/sample/data.py` is synthetic: a fictional payments team, invented commits, chats, tasks
and notes. It is labelled as sample data on the landing page, in the review screen, in the export and
on the share link. No real person or repository is referenced.

## License

MIT — see `LICENSE`.
