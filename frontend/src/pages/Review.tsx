import { useCallback, useEffect, useMemo, useState } from "react";
import { navigate } from "../App";
import ClaimCard from "../components/ClaimCard";
import CoveragePanel from "../components/CoveragePanel";
import EvidencePanel from "../components/EvidencePanel";
import EvidenceSearch from "../components/EvidenceSearch";
import { sessionTraceabilityUrl } from "../lib/api";
import { api, errorMessage } from "../lib/api";
import type { EvidenceDetail, EvidenceSummary, SessionPayload } from "../lib/types";

const REVIEWER_KEY = "handover-lens.reviewer";

function readReviewer(): string {
  try {
    return window.localStorage.getItem(REVIEWER_KEY) ?? "Anonymous reviewer";
  } catch {
    return "Anonymous reviewer";
  }
}

function prettyDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "—";
}

interface Props {
  sessionId: string;
}

export default function Review({ sessionId }: Props) {
  const [data, setData] = useState<SessionPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [activeClaimId, setActiveClaimId] = useState<string | null>(null);
  const [selectedEvidence, setSelectedEvidence] = useState<string | null>(null);
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filter, setFilter] = useState<"all" | "pending">("all");
  const [reviewer, setReviewer] = useState(readReviewer);
  const [signing, setSigning] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [showDropped, setShowDropped] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .session(sessionId)
      .then((payload) => {
        if (cancelled) return;
        setData(payload);
        setError(null);
      })
      .catch((caught) => {
        if (!cancelled) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  useEffect(() => {
    if (!selectedEvidence) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    api
      .evidence(sessionId, selectedEvidence)
      .then((value) => {
        if (!cancelled) setDetail(value);
      })
      .catch(() => {
        if (!cancelled) setDetail(null);
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedEvidence, sessionId]);

  useEffect(() => {
    try {
      window.localStorage.setItem(REVIEWER_KEY, reviewer);
    } catch {
      /* storage can be blocked; the export still records the typed name */
    }
  }, [reviewer]);

  const evidenceById = useMemo(() => {
    const map: Record<string, EvidenceSummary> = {};
    data?.evidence.forEach((item) => {
      map[item.id] = item;
    });
    return map;
  }, [data]);

  const activeClaim = useMemo(
    () => data?.claims.find((claim) => claim.id === activeClaimId) ?? null,
    [data, activeClaimId],
  );

  const panelItems = useMemo(() => {
    if (!data) return [];
    if (activeClaim) {
      return data.evidence.filter((item) => activeClaim.evidence_ids.includes(item.id));
    }
    if (selectedEvidence) {
      return data.evidence.filter((item) => item.id === selectedEvidence);
    }
    return [];
  }, [data, activeClaim, selectedEvidence]);

  const droppedClaims = useMemo(
    () => (data ? data.claims.filter((claim) => claim.status === "dropped") : []),
    [data],
  );

  const handleSelect = useCallback((claimId: string, evidenceId: string) => {
    setActiveClaimId(claimId);
    setSelectedEvidence(evidenceId);
  }, []);

  const handleDecide = useCallback(
    async (claimId: string, action: string, payload: { text?: string; note?: string }) => {
      if (!data) return;
      const result = await api.decide(data.session.id, claimId, {
        ...payload,
        action,
        reviewer: reviewer.trim() || "Anonymous reviewer",
      });
      setData((previous) =>
        previous
          ? {
              ...previous,
              claims: previous.claims.map((claim) =>
                claim.id === result.claim.id ? result.claim : claim,
              ),
              decisions: result.decisions,
              counts: { ...previous.counts, ...result.counts },
            }
          : previous,
      );
    },
    [data, reviewer],
  );

  async function handleSign() {
    if (!data) return;
    setSigning(true);
    setNotice(null);
    try {
      const result = await api.sign(data.session.id, reviewer.trim() || "Anonymous reviewer");
      navigate(`/handover/${result.token}`);
    } catch (caught) {
      setNotice(errorMessage(caught));
    } finally {
      setSigning(false);
    }
  }

  async function handleRegenerate() {
    if (!data) return;
    const confirmed = window.confirm(
      "Re-running the analysis replaces every claim and discards the review decisions in this run. Continue?",
    );
    if (!confirmed) return;
    setRegenerating(true);
    setNotice(null);
    try {
      await api.generate(data.session.id, true);
      const refreshed = await api.session(data.session.id);
      setData(refreshed);
      setActiveClaimId(null);
      setSelectedEvidence(null);
      setNotice("Analysis re-run. All claims are back to pending.");
    } catch (caught) {
      setNotice(errorMessage(caught));
    } finally {
      setRegenerating(false);
    }
  }

  if (loading) {
    return (
      <div className="page centered-state">
        <div className="spinner" aria-hidden="true" />
        <p>Loading the run…</p>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="page centered-state">
        <h1>This run is not available</h1>
        <p className="muted">{error ?? "Unknown error."}</p>
        <button className="btn btn-primary" onClick={() => navigate("/")}>
          Start a new handover
        </button>
      </div>
    );
  }

  const approvedTotal = data.counts.approved + data.counts.edited;
  const progress = data.counts.claims
    ? Math.round((data.counts.reviewed / data.counts.claims) * 100)
    : 0;
  const warnings = data.session.summary.warnings ?? [];
  const panelOpen = Boolean(activeClaim || selectedEvidence);

  return (
    <div className="page review-page">
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
            <small>review and sign-off</small>
          </span>
        </a>
        <div className="site-head-meta">
          {data.session.mode === "sample" ? <span className="badge sample">Sample data</span> : null}
          <span className={`pill ${data.session.llm_status === "offline" ? "pill-soft" : "pill-ok"}`}>
            {data.session.llm_status === "offline"
              ? "Rule drafter · no model key"
              : `Model: ${data.session.llm_status}`}
          </span>
          <span className="pill">
            {data.counts.evidence} records · {data.counts.claims} claims
          </span>
        </div>
      </header>

      <div className="run-strip">
        <div>
          <h1>{data.session.project_name}</h1>
          <p className="run-sub">
            {data.session.leaver_name} · {prettyDate(data.session.window_start)} →{" "}
            {prettyDate(data.session.window_end)}
            {data.session.repo_full_name ? ` · ${data.session.repo_full_name}` : ""}
          </p>
        </div>
        <div className="run-controls">
          <label className="reviewer-field">
            <span>Signing as</span>
            <input
              value={reviewer}
              onChange={(event) => setReviewer(event.target.value.slice(0, 80))}
              placeholder="Your name"
            />
          </label>
          <button className="btn btn-ghost btn-sm" onClick={handleRegenerate} disabled={regenerating}>
            {regenerating ? "Re-running…" : "Re-run analysis"}
          </button>
        </div>
      </div>

      <div className="review-progress">
        <div className="review-progress-bar" aria-hidden="true">
          <span style={{ width: `${progress}%` }} />
        </div>
        <p>
          <strong>{data.counts.reviewed}</strong> of {data.counts.claims} claims reviewed ·{" "}
          {approvedTotal} going into the handover · {data.counts.needs_confirmation} awaiting the leaver
        </p>
      </div>

      {warnings.length > 0 ? (
        <details className="alert alert-warn">
          <summary>
            {warnings.length} ingestion note{warnings.length > 1 ? "s" : ""} — read before trusting the
            coverage
          </summary>
          <ul>
            {warnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </details>
      ) : null}

      {data.counts.dropped > 0 ? (
        <div className="alert alert-warn">
          <div className="alert-row">
            <div>
              <strong>
                {data.counts.dropped} claim{data.counts.dropped > 1 ? "s" : ""} dropped by the citation
                verifier before review.
              </strong>
              <p>They are listed here rather than deleted silently.</p>
            </div>
            <button className="btn btn-ghost btn-sm" onClick={() => setShowDropped((open) => !open)}>
              {showDropped ? "Hide" : "Show"} dropped
            </button>
          </div>
          {showDropped ? (
            <ul className="dropped-list">
              {droppedClaims.map((claim) => (
                <li key={claim.id}>
                  <code>{claim.id}</code> {claim.text}
                  <em>{claim.verification_note}</em>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {notice ? <div className="alert alert-info">{notice}</div> : null}

      <div className={`workspace ${panelOpen ? "panel-open" : ""}`}>
        <main className="review-column">
          <CoveragePanel
            gaps={data.gaps}
            onSelect={(evidenceId) => {
              setActiveClaimId(null);
              setSelectedEvidence(evidenceId);
            }}
          />

          <div className="filter-row">
            <h2>Claims</h2>
            <div className="segmented">
              <button className={filter === "all" ? "is-active" : ""} onClick={() => setFilter("all")}>
                All {data.counts.claims}
              </button>
              <button
                className={filter === "pending" ? "is-active" : ""}
                onClick={() => setFilter("pending")}
              >
                Pending {data.counts.pending}
              </button>
            </div>
          </div>

          {data.sections.map((section) => {
            const claims = data.claims.filter(
              (claim) =>
                claim.section === section.key &&
                claim.status !== "dropped" &&
                (filter === "pending" ? claim.status === "pending" : true),
            );
            if (claims.length === 0) return null;
            return (
              <section className="claim-section" key={section.key}>
                <div className="claim-section-head">
                  <h3>{section.label}</h3>
                  <span className="tag">{claims.length}</span>
                  <p>{section.blurb}</p>
                </div>
                <div className="claim-list">
                  {claims.map((claim) => (
                    <ClaimCard
                      key={claim.id}
                      claim={claim}
                      evidenceById={evidenceById}
                      selectedEvidenceId={selectedEvidence}
                      onSelect={handleSelect}
                      onDecide={handleDecide}
                    />
                  ))}
                </div>
              </section>
            );
          })}

          {data.counts.claims === 0 ? (
            <div className="empty-state">
              <h3>No claims were produced</h3>
              <p>
                The run has evidence but no usable claims. Re-run the analysis, or start again with a
                wider date window.
              </p>
              <button className="btn" onClick={handleRegenerate} disabled={regenerating}>
                Re-run analysis
              </button>
            </div>
          ) : null}

          <div className="signbar">
            <div>
              <strong>
                {approvedTotal} approved · {data.counts.rejected} rejected · {data.counts.pending} pending
              </strong>
              <p className="muted">
                {approvedTotal === 0
                  ? "Approve or edit at least one claim — the export only contains decisions you made."
                  : `The signed handover will contain ${approvedTotal} claim${
                      approvedTotal === 1 ? "" : "s"
                    }, the coverage gaps, and the full approval log.`}
              </p>
            </div>
            <button
              className="btn btn-primary"
              onClick={handleSign}
              disabled={approvedTotal === 0 || signing}
            >
              {signing ? "Signing…" : "Sign off & export"}
            </button>
            <a className="btn btn-ghost" href={sessionTraceabilityUrl(data.session.id)} download>
              Traceability CSV
            </a>
          </div>

          {data.handovers.length > 0 ? (
            <div className="previous-links">
              <h3>Already signed</h3>
              <ul>
                {data.handovers.map((handover) => (
                  <li key={handover.token}>
                    <a
                      href={`/handover/${handover.token}`}
                      onClick={(event) => {
                        event.preventDefault();
                        navigate(`/handover/${handover.token}`);
                      }}
                    >
                      {handover.approved_count} claims · {handover.fingerprint}
                    </a>
                    <span className="muted"> {handover.created_at.slice(0, 16).replace("T", " ")}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </main>

        <aside className="evidence-column">
          <EvidenceSearch sessionId={data.session.id} />
          <EvidencePanel
            items={panelItems}
            selectedId={selectedEvidence}
            detail={detail}
            loading={detailLoading}
            title={activeClaim ? `Sources for ${activeClaim.id}` : "Evidence"}
            onSelect={(evidenceId) => setSelectedEvidence(evidenceId)}
            onClose={() => {
              setActiveClaimId(null);
              setSelectedEvidence(null);
            }}
          />
        </aside>
      </div>
    </div>
  );
}
