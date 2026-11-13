import { useEffect, useState } from "react";
import type { EvidenceDetail, EvidenceSummary } from "../lib/types";
import { SourceBadge, sourceShort } from "./Badges";

interface Props {
  items: EvidenceSummary[];
  selectedId: string | null;
  detail: EvidenceDetail | null;
  loading: boolean;
  title: string;
  onSelect: (evidenceId: string) => void;
  onClose: () => void;
}

function formatMeta(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) {
    return value.map((item) => String(item)).join(", ").slice(0, 200);
  }
  if (typeof value === "object") {
    try {
      return JSON.stringify(value).slice(0, 200);
    } catch {
      return "—";
    }
  }
  return String(value).slice(0, 200);
}

export default function EvidencePanel({
  items,
  selectedId,
  detail,
  loading,
  title,
  onSelect,
  onClose,
}: Props) {
  const [copyState, setCopyState] = useState<"idle" | "ok" | "fail">("idle");

  useEffect(() => {
    setCopyState("idle");
  }, [selectedId]);

  async function copyBody() {
    if (!detail) return;
    try {
      await navigator.clipboard.writeText(detail.body);
      setCopyState("ok");
      window.setTimeout(() => setCopyState("idle"), 1600);
    } catch {
      setCopyState("fail");
    }
  }

  return (
    <div className="evidence-panel">
      <div className="evidence-panel-head">
        <div>
          <h2>{title}</h2>
          <p className="evidence-panel-sub">
            {items.length
              ? `${items.length} cited record${items.length > 1 ? "s" : ""} — click one to read the original`
              : "Every claim in this handover points at a record like these."}
          </p>
        </div>
        <button className="icon-btn" onClick={onClose} aria-label="Close evidence panel">
          ×
        </button>
      </div>

      {items.length === 0 ? (
        <div className="evidence-empty">
          <p>
            Select a claim to see the commits, messages, tasks or notes behind it. Nothing here is
            summarised without a citation.
          </p>
        </div>
      ) : (
        <div className="evidence-list">
          {items.map((item) => (
            <button
              key={item.id}
              className={`evidence-item ${selectedId === item.id ? "is-selected" : ""}`}
              onClick={() => onSelect(item.id)}
            >
              <span className="evidence-item-top">
                <SourceBadge type={item.source_type} />
                <span className="evidence-item-id">{item.id}</span>
                <span className="evidence-item-date">{(item.occurred_at ?? "").slice(0, 10)}</span>
              </span>
              <span className="evidence-item-title">{item.title ?? item.external_id ?? "Untitled record"}</span>
              <span className="evidence-item-meta">
                {item.author ?? "unattributed"}
                {item.source_label ? ` · ${item.source_label}` : ""}
              </span>
            </button>
          ))}
        </div>
      )}

      {selectedId ? (
        <div className="evidence-detail">
          {loading ? (
            <p className="muted">Loading the original record…</p>
          ) : detail ? (
            <>
              <div className="evidence-detail-head">
                <h3>{detail.title ?? detail.external_id ?? detail.id}</h3>
                <div className="evidence-detail-tags">
                  <SourceBadge type={detail.source_type} />
                  <span className="evidence-item-id">{detail.id}</span>
                  {detail.area_labels.map((area) => (
                    <span key={area} className="tag">
                      {area}
                    </span>
                  ))}
                </div>
                <p className="evidence-detail-meta">
                  {detail.author ?? "unattributed"} · {(detail.occurred_at ?? "no date").slice(0, 10)} ·{" "}
                  {detail.source_label ?? "unknown source"}
                </p>
              </div>

              <pre className="evidence-body">{detail.body}</pre>

              <div className="evidence-detail-actions">
                {detail.url ? (
                  <a className="btn btn-sm" href={detail.url} target="_blank" rel="noopener noreferrer">
                    Open original ↗
                  </a>
                ) : (
                  <span className="tag tag-muted">
                    {detail.source_type === "git_commit" ? "commit" : sourceShort(detail.source_type)} record,
                    quoted in full above
                  </span>
                )}
                <button className="btn btn-sm btn-ghost" onClick={copyBody}>
                  {copyState === "ok" ? "Copied" : copyState === "fail" ? "Copy blocked" : "Copy text"}
                </button>
              </div>

              <dl className="evidence-meta">
                <div>
                  <dt>Source</dt>
                  <dd>{detail.source_label ?? "—"}</dd>
                </div>
                <div>
                  <dt>External id</dt>
                  <dd>{detail.external_id ?? "—"}</dd>
                </div>
                {Object.entries(detail.metadata)
                  .slice(0, 5)
                  .map(([key, value]) => (
                    <div key={key}>
                      <dt>{key.replace(/_/g, " ")}</dt>
                      <dd>{formatMeta(value)}</dd>
                    </div>
                  ))}
              </dl>
            </>
          ) : (
            <p className="inline-error">That record could not be loaded.</p>
          )}
        </div>
      ) : null}
    </div>
  );
}
