# AGENTS.md — Handover Lens conventions

Read this before editing. It is deliberately short.

## Stack (do not swap)
- Backend: Python 3.9+ / FastAPI, SQLAlchemy 2 Core with raw SQL (`text()`), no ORM models.
- Frontend: React 18 + TypeScript + Vite, hand-written CSS (`frontend/src/styles.css`). No UI kit, no Tailwind, no router library.
- Storage: SQLite by default (`data/handover.db`), Postgres when `DATABASE_URL` is set. Schema in `backend/app/db.py::SCHEMA`.
- PDF: reportlab (`backend/app/analysis/export.py`).
- LLM: `backend/app/llm.py` only. Nothing else may call a model provider.

## Layout
```
backend/app/config.py      all env + section list (single source of truth)
backend/app/db.py          engine, schema, query helpers, JSON columns
backend/app/security.py    rate limits, ids, LLM budget, concurrency slots
backend/app/llm.py         provider-agnostic wrapper + offline detection
backend/app/ingest/        file parsers + GitHub reader (network + caps)
backend/app/analysis/      rules, claim drafting, verification, export
backend/app/sample/        synthetic dataset used by "Try the sample project"
backend/app/api.py         every HTTP route (one place)
frontend/src/pages/        Intake, Review, Handover views
frontend/src/components/   ClaimCard, EvidencePanel, CoveragePanel, Badges
```

## Data contract
Evidence item: `id, source_type, source_label, external_id, title, body, author,
occurred_at, url, areas[], metadata`.
Claim: `id, section, text, claim_type, confidence, evidence_ids[], origin,
verification, verification_note, status, final_text, note`.
Sections and their labels live in `config.SECTIONS`. Add a section there, not inline.
Review decisions are append-only rows in `decisions` (audit log).

## Rules that must not regress
1. Secrets are read from env only. Never inline a key, never ship one to `frontend/`.
2. Model output is untrusted: evidence ids are validated, unsupported claims are dropped
   (`analysis/verify.py`). Never render model or uploaded text as HTML — React text nodes only.
3. Every claim must carry at least one evidence id that exists in the session.
   If you add a claim source, add its evidence ids in the same change.
4. Rate limit + size cap every endpoint that does work (see `security.py`).
5. The app must stay fully usable with **no** LLM key and **no** GitHub token.
   The offline drafter in `analysis/claims.py` is a product feature, not a test stub.
6. Reuse helpers: `db.query/execute`, `security.new_id`, `security.client_key`,
   `analysis.rules` for counting, `config.SECTIONS` for labels. Search before writing a new one.
7. Cited evidence must be quoted, never paraphrased into a stronger claim.

## Verification (actually run it)
```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m uvicorn backend.app.main:app --port 8000   # backend
cd frontend && npm install && npm run build                     # frontend typecheck+build
```
Then exercise the workflow over HTTP — `/api/sessions/sample` → `/generate` →
`/claims/{id}/decision` → `/handover` → `/api/handover/{token}` — and confirm the
counts on screen match the database. "It compiles" is not verification.
