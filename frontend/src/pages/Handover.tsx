import { useEffect, useState } from "react";
import { navigate } from "../App";
import { ConfidenceBadge, OriginBadge } from "../components/Badges";
import { api, errorMessage, markdownUrl, pdfUrl, traceabilityUrl } from "../lib/api";
import type { HandoverRecord, SnapshotEvidence } from "../lib/types";

interface Props {
  token: string;
}

function prettyDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "—";
}

function prettyStamp(value: string | null | undefined): string {
  if (!value) return "—";
  return `${value.slice(0, 10)} ${value.slice(11, 16)} UTC`;
}

function EvidenceRow({ item }: { item: SnapshotEvidence }) {
  return (
    <li className="paper-evidence">
      <div className="paper-evidence-head">
        <span className="tag">{item.source_type.replace(/_/g, " ")}</span>
        <span className="paper-evidence-id">{item.id}</span>
        <span className="muted">
          {item.author ?? "unattributed"} · {prettyDate(item.occurred_at)}
        </span>
      </div>
      <p className="paper-evidence-title">{item.title ?? item.external_id ?? "Record"}</p>
      {item.excerpt ? <blockquote>{item.excerpt}</blockquote> : null}
      {item.url ? (
        <a href={item.url} target="_blank" rel="noopener noreferrer">
          Open the original ↗
        </a>
      ) : (
        <span className="muted">Original text shown above (sample record).</span>
      )}
    </li>
  );
}

export default function Handover({ token }: Props) {
  const [record, setRecord] = useState<HandoverRecord | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [verification, setVerification] = useState<{ matches: boolean } | null>(null);
  const [verifying, setVerifying] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .handover(token)
      .then((value) => {
        if (!cancelled) setRecord(value);
      })
      .catch((caught) => {
        if (!cancelled) setError(errorMessage(caught));
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  async function verify() {
    setVerifying(true);
    try {
      const result = await api.verify(token);
      setVerification({ matches: result.matches });
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setVerifying(false);
    }
  }

  if (error) {
    return (
      <div className="page centered-state">
        <h1>That handover is not available</h1>
        <p className="muted">{error}</p>
        <button className="btn btn-primary" onClick={() => navigate("/")}>
          Start a new handover
        </button>
      </div>
    );
  }

  if (!record) {
    return (
      <div className="page centered-state">
        <div className="spinner" aria-hidden="true" />
        <p>Loading the signed handover…</p>
      </div>
    );
  }

  const payload = record.payload;

  return (
    <div className="page handover-page">
      <header className="site-head">
        <a
          className="brand"
          href="/"
          onClick={(event) => {
            event.preventDefault();
            navigate("/");
          }}
        >
          <span className="brand-mark" aria-hidden="true">
            HL
          </span>
          <span>
            Handover Lens
            <small>signed handover</small>
          </span>
        </a>
        <div className="site-head-meta">
          <span className="pill pill-ok">Read-only</span>
          <span className="pill">Fingerprint {record.fingerprint}</span>
        </div>
      </header>

      <main className="paper">
        <div className="paper-head">
          <p className="eyebrow">Signed handover {payload.sample_data ? "· sample data" : ""}</p>
          <h1>{payload.project}</h1>
          <p className="paper-sub">
            {payload.leaver ? `${payload.leaver} is leaving. ` : ""}
            This handover was assembled from cited records, reviewed by a human, and frozen at sign-off.
            Only approved and edited claims appear below.
          </p>
        </div>

        <dl className="paper-meta">
          <div>
            <dt>Leaving</dt>
            <dd>{payload.leaver || "—"}</dd>
          </div>
          <div>
            <dt>Period</dt>
            <dd>
              {prettyDate(payload.window.start)} → {prettyDate(payload.window.end)}
            </dd>
          </div>
          <div>
            <dt>Repository</dt>
            <dd>{payload.repo ?? "mixed sources"}</dd>
          </div>
          <div>
            <dt>Signed by</dt>
            <dd>{payload.reviewer}</dd>
          </div>
          <div>
            <dt>Signed at</dt>
            <dd>{prettyStamp(payload.signed_at)}</dd>
          </div>
          <div>
            <dt>Content</dt>
            <dd>
              {payload.counts.approved + payload.counts.edited} claims · {payload.counts.gaps} coverage
              gaps · {payload.counts.rejected} rejected · {payload.counts.dropped} dropped
            </dd>
          </div>
        </dl>

        {payload.sample_data ? (
          <div className="alert alert-info">
            This is the synthetic sample project: fictional people, commits, chats and tasks. It exists
            so the workflow can be judged without any setup.
          </div>
        ) : null}

        <div className="paper-actions">
          <a className="btn btn-primary" href={markdownUrl(token)} download>
            Download Markdown
          </a>
          <a className="btn" href={pdfUrl(token)} download>
            Download PDF
          </a>
          <a className="btn" href={traceabilityUrl(token)} download>
            Download traceability CSV
          </a>
          <button className="btn btn-ghost" onClick={() => window.print()}>
            Print
          </button>
          <button className="btn btn-ghost" onClick={verify} disabled={verifying}>
            {verifying ? "Verifying…" : "Verify fingerprint"}
          </button>
          {payload.session_id ? (
            <a
              className="btn btn-ghost"
              href={`/review/${payload.session_id}`}
              onClick={(event) => {
                event.preventDefault();
                navigate(`/review/${payload.session_id}`);
              }}
            >
              Back to the review run
            </a>
          ) : null}
        </div>

        {verification ? (
          <div className={`alert ${verification.matches ? "alert-ok" : "alert-error"}`}>
            {verification.matches
              ? "Fingerprint matches: the claim text, period and coverage list are unchanged since sign-off."
              : "Fingerprint mismatch — this snapshot no longer matches its signed content."}
          </div>
        ) : null}

        {payload.sections.map((section) => (
          <section className="paper-section" key={section.key}>
            <h2>{section.label}</h2>
            <ul className="paper-claims">
              {section.claims.map((claim) => (
                <li key={claim.id} className="paper-claim">
                  <div className="paper-claim-head">
                    <span className="claim-id">{claim.id}</span>
                    <ConfidenceBadge level={claim.confidence} />
                    <OriginBadge origin={claim.origin} />
                    {claim.status === "edited" ? <span className="tag">edited</span> : null}
                  </div>
                  <p className="paper-claim-text">{claim.text}</p>
                  {claim.original_text ? (
                    <details className="claim-original">
                      <summary>Draft this replaced</summary>
                      <p>{claim.original_text}</p>
                    </details>
                  ) : null}
                  {claim.reviewer_note ? (
                    <p className="paper-note">Reviewer note: {claim.reviewer_note}</p>
                  ) : null}
                  <ul className="paper-evidence-list">
                    {claim.evidence.map((item) => (
                      <EvidenceRow key={item.id} item={item} />
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          </section>
        ))}

        <section className="paper-section">
          <h2>Coverage check</h2>
          {payload.gaps.length === 0 ? (
            <p>Every area with recorded activity is represented by an approved claim.</p>
          ) : (
            <>
              <p className="muted">
                Areas the leaver touched that no approved claim covers. The successor should ask about
                these explicitly.
              </p>
              <ul className="paper-gaps">
                {payload.gaps.map((gap) => (
                  <li key={gap.area}>
                    <strong>{gap.label}</strong>
                    <p>{gap.reason}</p>
                    <ul className="paper-evidence-list">
                      {gap.evidence.map((item) => (
                        <EvidenceRow key={`${gap.area}-${item.id}`} item={item} />
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>

        <section className="paper-section">
          <h2>Approval log</h2>
          {payload.audit.length === 0 ? (
            <p>No individual decisions were logged.</p>
          ) : (
            <table className="audit-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Reviewer</th>
                  <th>Claim</th>
                  <th>Decision</th>
                  <th>Note</th>
                </tr>
              </thead>
              <tbody>
                {payload.audit.map((row, index) => (
                  <tr key={`${row.claim_id}-${index}`}>
                    <td>{prettyStamp(row.at)}</td>
                    <td>{row.reviewer}</td>
                    <td>{row.claim_id}</td>
                    <td>{row.action.replace(/_/g, " ")}</td>
                    <td>{row.note ?? ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {payload.omitted.length > 0 ? (
          <section className="paper-section">
            <h2>Omitted from this handover</h2>
            <p className="muted">
              Kept visible so nobody mistakes a rejected or unverified claim for an approved one.
            </p>
            <ul className="paper-omitted">
              {payload.omitted.map((row) => (
                <li key={row.id}>
                  <code>{row.id}</code> <span className="tag">{row.status}</span>
                  <p>{row.text}</p>
                  {row.reason ? <p className="muted">{row.reason}</p> : null}
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <footer className="paper-foot">
          <p>
            Fingerprint <code>{payload.fingerprint}</code> — sha256 over the approved claim text, the
            period and the coverage list.
          </p>
          <p>
            Generated by Handover Lens. Every claim above cites at least one record; claims the verifier
            could not support never reached the reviewer.
          </p>
        </footer>
      </main>
    </div>
  );
}
