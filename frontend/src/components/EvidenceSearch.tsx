import { useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../lib/api";
import type { EvidenceSummary } from "../lib/types";

const SOURCES = [
  "pull_request",
  "git_commit",
  "review",
  "issue",
  "document",
  "chat",
  "meeting_note",
  "task",
];

interface Props {
  sessionId: string;
}

export default function EvidenceSearch({ sessionId }: Props) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [source, setSource] = useState("");
  const [items, setItems] = useState<EvidenceSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(0);

  useEffect(() => {
    if (!open) return;
    const handle = window.setTimeout(async () => {
      const current = ++requestId.current;
      setBusy(true);
      setError("");
      try {
        const params = new URLSearchParams({ limit: "25" });
        if (query.trim()) params.set("q", query.trim());
        if (source) params.set("source", source);
        const result = await api.searchEvidence(sessionId, params);
        if (current !== requestId.current) return;
        setItems(result.items);
        setTotal(result.total);
      } catch (err) {
        if (current === requestId.current) setError(errorMessage(err));
      } finally {
        if (current === requestId.current) setBusy(false);
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [open, query, source, sessionId]);

  return (
    <section className="evidence-search">
      <button
        type="button"
        className="evidence-search-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide evidence search" : "Search all evidence"}
      </button>

      {open ? (
        <div className="evidence-search-body">
          <label className="sr-only" htmlFor="evidence-query">
            Search titles, text, authors and sources
          </label>
          <input
            id="evidence-query"
            className="input"
            type="search"
            placeholder="Search titles, text, authors…"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          <label className="sr-only" htmlFor="evidence-source">
            Filter by source type
          </label>
          <select
            id="evidence-source"
            className="input"
            value={source}
            onChange={(event) => setSource(event.target.value)}
          >
            <option value="">All sources</option>
            {SOURCES.map((name) => (
              <option key={name} value={name}>
                {name.replace(/_/g, " ")}
              </option>
            ))}
          </select>

          <p className="muted" aria-live="polite">
            {busy ? "Searching…" : `${total} matching record${total === 1 ? "" : "s"}`}
          </p>
          {error ? <p className="alert alert-error">{error}</p> : null}

          <ul className="evidence-search-results">
            {items.map((item) => (
              <li key={item.id}>
                <div className="evidence-search-meta">
                  <span className="badge">{item.source_type.replace(/_/g, " ")}</span>
                  <span className="muted">
                    {item.author || "unattributed"}
                    {item.occurred_at ? ` · ${item.occurred_at.slice(0, 10)}` : ""}
                  </span>
                </div>
                <strong>{item.title || item.external_id || item.id}</strong>
                <p className="muted">{item.snippet}</p>
                <div className="evidence-search-foot">
                  <code>{item.id}</code>
                  {item.url ? (
                    <a href={item.url} target="_blank" rel="noopener noreferrer">
                      Open source
                    </a>
                  ) : null}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}