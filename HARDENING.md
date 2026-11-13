# The 20 mistakes vibe-coded projects make, and where this repo stands

Each row is a mistake that ships broken demos. The third column is what this repository actually
does, so a reviewer can check the claim instead of trusting it.

| # | Mistake | What this repo does |
|---|---|---|
| 1 | Secrets committed to the repo | `.env` is gitignored and never tracked; the committed tree is scanned for key patterns before each push. `.env.example` lists names only. |
| 2 | Secrets shipped in the frontend bundle | The browser never receives a key. `frontend/` calls only `/api/*`; the model and GitHub keys live in the FastAPI process. |
| 3 | Missing `.gitignore` | Ignores `.env`, `data/`, `*.db`, `__pycache__`, `.venv`, `node_modules`, `frontend/dist`, `.DS_Store`. |
| 4 | No `.env.example` | Committed, with every variable documented and blank values. The app runs with none of them set. |
| 5 | No lockfile | `frontend/package-lock.json` is committed and `build.sh` uses `npm ci`, not `npm install`. |
| 6 | No auth, or auth that trusts the client | Deliberately no accounts. A run is addressed by a 128-bit random capability id that cannot be enumerated; there is no admin surface, and every state-changing route is rate limited. |
| 7 | Wildcard CORS | No CORS middleware at all. Frontend and API share one origin, so a foreign origin gets no `Access-Control-Allow-Origin`. |
| 8 | No server-side validation | Pydantic request models plus explicit limits: `MAX_CLAIM_CHARS`, `MAX_NOTE_CHARS`, `MAX_EVIDENCE_BODY_CHARS`, date parsing that rejects nonsense with a readable message. |
| 9 | SQL injection | Every query binds parameters through SQLAlchemy `text()`. The new evidence search binds `q`, `area` and `source` as values and allowlists the columns it filters on. |
| 10 | No rate limits and uncapped model spend | Per-IP sliding windows on general and heavy routes, 2 concurrent generations, and a hard daily model-call cap with a reservation row in the database. |
| 11 | Unbounded uploads | 2 MB per file, 6 MB per request, 8 files; oversized bodies are rejected with 413 before Starlette spools them to disk. |
| 12 | Swallowed errors, no 404 page | One handler per error class: 404, 422 and 500 return a readable sentence, the detail goes to the server log, and no stack trace or SQL message reaches the browser. |
| 13 | Hardcoded `localhost` in shipped code | The backend reads its own origin and data paths from the environment. Only the Vite dev proxy mentions `127.0.0.1`, and it is not part of the build. |
| 14 | README that does not work, or no license | The clone steps in `README.md` were executed against a fresh clone of the public repo: install, build, run, smoke. MIT `LICENSE` included. |
| 15 | No tests | `tests/test_core.py` covers name matching, area tagging, citation validation, confidence and the CSV export; `scripts/smoke_test.py` exercises the whole workflow over HTTP. Both run in this repo's verification. |
| 16 | Claiming mocked success as real | The sample project is labelled as synthetic in the UI, the export and the share link. Live GitHub ingestion and one live model provider were exercised with real credentials, and the README says which providers were not. |
| 17 | List endpoints without pagination | `GET /api/sessions/{id}/evidence` takes `limit`/`offset`, caps `limit` at 200 server-side, and returns the total so the UI can page. |
| 18 | Inaccessible controls | Inputs have real labels (`sr-only` where the design hides them), the search result count is an `aria-live` region, and interactive elements are native `button`/`a`/`input`. |
| 19 | No responsive layout | Four breakpoints in `styles.css`; the review column and evidence panel stack instead of overflowing on narrow screens. |
| 20 | Missing security headers, HTTPS, invented dependencies | CSP, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy` and `Cache-Control: no-store` on API responses; HTTPS terminates at the host. Every dependency is a real, installed package — nothing is imported that is not in `requirements.txt` or `package-lock.json`. |

## Verify it yourself

```bash
git clone https://github.com/nikunj-kohli/handloom && cd handloom
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
.venv/bin/python -m uvicorn backend.app.main:app --port 8000

# in another shell
.venv/bin/python -m pytest tests -q
.venv/bin/python scripts/smoke_test.py http://127.0.0.1:8000
```

The clone has no `.env`, so it runs the deterministic drafter: that is the intended zero-setup path,
not a degraded mode.