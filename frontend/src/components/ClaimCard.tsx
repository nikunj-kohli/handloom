import { useState } from "react";
import type { Claim, EvidenceSummary } from "../lib/types";
import { ConfidenceBadge, OriginBadge, STATUS_LABEL, StatusBadge, sourceShort } from "./Badges";

interface Props {
  claim: Claim;
  evidenceById: Record<string, EvidenceSummary>;
  selectedEvidenceId: string | null;
  onSelect: (claimId: string, evidenceId: string) => void;
  onDecide: (
    claimId: string,
    action: string,
    payload: { text?: string; note?: string },
  ) => Promise<void>;
}

export default function ClaimCard({
  claim,
  evidenceById,
  selectedEvidenceId,
  onSelect,
  onDecide,
}: Props) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(claim.final_text ?? claim.text);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState(claim.note ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shownText = claim.status === "edited" && claim.final_text ? claim.final_text : claim.text;
  const reviewed = ["approved", "edited", "rejected", "needs_confirmation"].includes(claim.status);

  async function act(action: string, payload: { text?: string; note?: string } = {}) {
    setError(null);
    setBusy(true);
    try {
      await onDecide(claim.id, action, { note: note.trim() || undefined, ...payload });
      setEditing(false);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save that decision.");
    } finally {
      setBusy(false);
    }
  }

  async function submitEdit() {
    if (draft.trim().length < 8) {
      setError("An edited claim needs at least a few words.");
      return;
    }
    await act("edit", { text: draft.trim() });
  }

  return (
    <article className={`claim claim-${claim.status}`} id={claim.id}>
      <div className="claim-head">
        <span className="claim-id">{claim.id}</span>
        <ConfidenceBadge level={claim.confidence} />
        <OriginBadge origin={claim.origin} />
        <StatusBadge status={claim.status} />
        {claim.verification ? (
          <span className="verify-tag" title={claim.verification_note ?? undefined}>
            {claim.verification}
          </span>
        ) : null}
      </div>

      {editing ? (
        <div className="claim-edit">
          <textarea
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            rows={4}
            maxLength={1200}
            aria-label={`Edit ${claim.id}`}
          />
          <div className="claim-edit-actions">
            <button className="btn btn-primary btn-sm" onClick={submitEdit} disabled={busy}>
              Save edited claim
            </button>
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => {
                setEditing(false);
                setDraft(claim.final_text ?? claim.text);
              }}
              disabled={busy}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <p className="claim-text">{shownText}</p>
      )}

      {claim.status === "edited" && claim.final_text ? (
        <details className="claim-original">
          <summary>Show the draft this replaced</summary>
          <p>{claim.text}</p>
        </details>
      ) : null}

      {claim.note ? <p className="claim-note">Reviewer note: {claim.note}</p> : null}

      <div className="claim-evidence">
        <span className="claim-evidence-label">Source{claim.evidence_ids.length > 1 ? "s" : ""}</span>
        {claim.evidence_ids.map((evidenceId) => {
          const item = evidenceById[evidenceId];
          return (
            <button
              key={evidenceId}
              className={`chip ${selectedEvidenceId === evidenceId ? "chip-active" : ""}`}
              onClick={() => onSelect(claim.id, evidenceId)}
              title={item?.title ?? evidenceId}
            >
              <span className="chip-id">{evidenceId}</span>
              {item ? <span className="chip-type">{sourceShort(item.source_type)}</span> : null}
            </button>
          );
        })}
      </div>

      {claim.verification_note ? (
        <p className="claim-verification">{claim.verification_note}</p>
      ) : null}

      {noteOpen ? (
        <div className="claim-note-editor">
          <label htmlFor={`note-${claim.id}`}>Reviewer note for the audit log</label>
          <input
            id={`note-${claim.id}`}
            value={note}
            maxLength={600}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Why you decided this"
          />
        </div>
      ) : null}

      {error ? <p className="inline-error">{error}</p> : null}

      <div className="claim-actions">
        <button
          className="btn btn-approve"
          onClick={() => act("approve")}
          disabled={busy || claim.status === "approved"}
        >
          Approve
        </button>
        <button className="btn" onClick={() => setEditing(true)} disabled={busy || editing}>
          Edit
        </button>
        <button
          className="btn"
          onClick={() => act("needs_confirmation")}
          disabled={busy || claim.status === "needs_confirmation"}
        >
          Needs leaver to confirm
        </button>
        <button
          className="btn btn-danger"
          onClick={() => act("reject")}
          disabled={busy || claim.status === "rejected"}
        >
          Reject
        </button>
        {reviewed ? (
          <button className="btn btn-ghost" onClick={() => act("reopen")} disabled={busy}>
            Reset
          </button>
        ) : null}
        <button
          className={`btn btn-ghost btn-note ${noteOpen ? "is-open" : ""}`}
          onClick={() => setNoteOpen((open) => !open)}
          disabled={busy}
          aria-expanded={noteOpen}
        >
          Note
        </button>
        <span className="claim-status-hint">{STATUS_LABEL[claim.status]}</span>
      </div>
    </article>
  );
}
