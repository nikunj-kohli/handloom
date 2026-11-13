# Handover Lens — build conventions

Short version for humans. `AGENTS.md` has the agent-facing rules.

## Scope contract (Round 2)
In: sample project, repo + file intake, leaver picker, rule-based extraction, cited claim
drafting, citation verification, review with evidence panel, coverage check, signed export
(Markdown + PDF), read-only share link, confidence tags.
Out: login/accounts, OAuth connectors, Q&A chat, vector search, bus-factor dashboard,
multi-tenancy. Round 3 items stay out; see the "Round 3" section of the README.

## Hard limits enforced in code
| Limit | Value | Where |
|---|---|---|
| Upload size / file | 2 MB | `config.MAX_UPLOAD_BYTES` |
| Upload size / request | 6 MB, 8 files | `config.MAX_TOTAL_UPLOAD_BYTES` |
| Commits read from a repo | 120 | `config.GITHUB_MAX_COMMITS` |
| Pull requests read | 80 | `config.GITHUB_MAX_PULLS` |
| Model calls / UTC day | 400 | `config.DAILY_LLM_CALL_CAP` |
| Generations at once | 2 | `config.MAX_CONCURRENT_GENERATIONS` |
| Heavy endpoint rate | 8/min/IP | `config.HEAVY_RATE_LIMIT_PER_MINUTE` |
| Session lifetime | 72 h | `config.SESSION_TTL_HOURS` |

## Data contract
See `AGENTS.md`. One added rule: a claim is never stored without `evidence_ids`, and the
reviewer always sees the exact evidence text next to the claim.

## Confidence policy
- `high` — rule-derived, or model claim with 2+ independent sources.
- `medium` — single-source claim.
- `low` — model inference with one source, or a claim whose citation check was weak.
The UI shows the basis (`Rule` / `Model`) separately from confidence, so a judge can tell
what the machine asserted from what it computed.

## Privacy
Uploaded chat/task files live in the session row only, expire after the session TTL, and
are never sent anywhere except the configured model provider when drafting. The upload
screen says this in plain language.
