import { useEffect, useRef, useState } from "react";
import { navigate } from "../App";
import BusyOverlay from "../components/BusyOverlay";
import { api, errorMessage } from "../lib/api";
import type { Health, SampleInfo } from "../lib/types";
import { sourceShort } from "../components/Badges";

const STEPS = [
  "Reading the repository and uploaded files",
  "Extracting ownership, open work and people",
  "Drafting claims that cite their sources",
  "Verifying every citation",
];

function isoDate(offsetDays: number): string {
  const date = new Date();
  date.setDate(date.getDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

function prettyDate(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : "—";
}

export default function Intake() {
  const [health, setHealth] = useState<Health | null>(null);
  const [sample, setSample] = useState<SampleInfo | null>(null);
  const [repo, setRepo] = useState("");
  const [leaver, setLeaver] = useState("");
  const [email, setEmail] = useState("");
  const [projectName, setProjectName] = useState("");
  const [start, setStart] = useState(isoDate(-120));
  const [end, setEnd] = useState(isoDate(0));
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState<{ label: string; step: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .health()
      .then((value) => {
        if (!cancelled) setHealth(value);
      })
      .catch(() => undefined);
    api
      .sampleInfo()
      .then((value) => {
        if (!cancelled) setSample(value);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  function startProgress(label: string) {
    setBusy({ label, step: 0 });
    if (timer.current) window.clearInterval(timer.current);
    timer.current = window.setInterval(() => {
      setBusy((current) => (current ? { ...current, step: Math.min(current.step + 1, 2) } : current));
    }, 2200);
  }

  function stopProgress() {
    if (timer.current) {
      window.clearInterval(timer.current);
      timer.current = null;
    }
  }

  async function runSample() {
    setError(null);
    startProgress("Loading the sample project");
    try {
      const created = await api.createSample();
      setBusy({ label: "Drafting and verifying claims", step: 2 });
      await api.generate(created.session.id, false);
      stopProgress();
      navigate(`/review/${created.session.id}`);
    } catch (caught) {
      stopProgress();
      setBusy(null);
      setError(errorMessage(caught));
    }
  }

  async function runLive(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    if (!leaver.trim()) {
      setError("Name the person who is leaving — it is how their activity is matched.");
      return;
    }
    if (!repo.trim() && files.length === 0) {
      setError("Add a public repo URL or at least one file.");
      return;
    }

    const form = new FormData();
    form.append("repo_url", repo.trim());
    form.append("leaver_name", leaver.trim());
    form.append("leaver_email", email.trim());
    form.append("window_start", start);
    form.append("window_end", end);
    form.append("project_name", projectName.trim());
    files.forEach((file) => form.append("files", file));

    startProgress("Reading sources");
    try {
      const created = await api.ingest(form);
      setBusy({ label: "Drafting and verifying claims", step: 2 });
      await api.generate(created.session.id, false);
      stopProgress();
      navigate(`/review/${created.session.id}`);
    } catch (caught) {
      stopProgress();
      setBusy(null);
      setError(errorMessage(caught));
    }
  }

  const sourceEntries = sample ? Object.entries(sample.by_source).sort((a, b) => b[1] - a[1]) : [];

  return (
    <div className="page intake-page">
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
            <small>cited engineering handovers</small>
          </span>
        </a>
        <div className="site-head-meta">
          <span className={`pill ${health?.llm.configured ? "pill-ok" : ""}`}>
            {health
              ? health.llm.configured
                ? `Model: ${health.llm.provider} · ${health.llm.model}`
                : "No model key · rule drafter active"
              : "checking…"}
          </span>
          <span className="pill">
            {health ? (health.github_token ? "GitHub token set" : "GitHub anonymous") : "—"}
          </span>
          <span className="pill pill-soft">No sign-in</span>
        </div>
      </header>

      <main>
        <section className="hero">
          <p className="eyebrow">Round 2 — working demo</p>
          <h1>A handover a judge can check.</h1>
          <p className="hero-sub">
            Handover Lens reads what a leaving engineer actually did — commits, pull requests, reviews,
            chat exports, task lists and meeting notes — then drafts a handover where every claim points
            at its source. Claims it cannot cite are dropped before you see them. You make the final call.
          </p>
          <div className="hero-points">
            <span>Every claim traces to a commit, message or note</span>
            <span>A coverage check shows what the AI missed</span>
            <span>Only approved claims reach the signed export</span>
          </div>
        </section>

        <section className="start-grid">
          <div className="card card-sample">
            <div className="card-kicker">No setup · works with zero API keys</div>
            <h2>Try the sample project</h2>
            <p className="card-lead">
              A fictional payments team, preloaded with a planned leaver, so the whole workflow runs even
              if GitHub or a model provider is having a bad day.
            </p>
            {sample ? (
              <>
                <dl className="sample-facts">
                  <div>
                    <dt>Project</dt>
                    <dd>{sample.project_name}</dd>
                  </div>
                  <div>
                    <dt>Leaving</dt>
                    <dd>
                      {sample.leaver_name} · {prettyDate(sample.window_start)} →{" "}
                      {prettyDate(sample.window_end)}
                    </dd>
                  </div>
                  <div>
                    <dt>Records</dt>
                    <dd>
                      {sample.record_count} across {sourceEntries.length} source types
                    </dd>
                  </div>
                </dl>
                <div className="source-chips">
                  {sourceEntries.map(([type, count]) => (
                    <span key={type} className="tag">
                      {count} × {sourceShort(type)}
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <p className="muted">Loading sample details…</p>
            )}
            <button className="btn btn-primary btn-lg" onClick={runSample} disabled={Boolean(busy)}>
              Try the sample project
            </button>
            <p className="fineprint">
              Clearly labelled as sample data throughout. Nothing here is a real person or repository.
            </p>
          </div>

          <form className="card card-live" onSubmit={runLive}>
            <div className="card-kicker">Use your own sources</div>
            <h2>Read a real leaver</h2>
            <p className="card-lead">
              A public GitHub repo plus any chat exports, task CSV or meeting notes you have. Private
              repos need a server-side token; uploaded files stay in this run only.
            </p>

            <label className="field">
              <span>Leaving engineer</span>
              <input
                value={leaver}
                onChange={(event) => setLeaver(event.target.value)}
                placeholder="e.g. Priya Raman"
                autoComplete="off"
                maxLength={120}
              />
            </label>

            <div className="field-row">
              <label className="field">
                <span>Email (optional, improves matching)</span>
                <input
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="priya@company.com"
                  autoComplete="off"
                  maxLength={160}
                />
              </label>
              <label className="field">
                <span>Label (optional)</span>
                <input
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="Payments platform"
                  autoComplete="off"
                  maxLength={160}
                />
              </label>
            </div>

            <label className="field">
              <span>Public repository</span>
              <input
                value={repo}
                onChange={(event) => setRepo(event.target.value)}
                placeholder="https://github.com/owner/repo"
                autoComplete="off"
                maxLength={200}
              />
              <em>
                Read-only, capped at {health?.limits.commits_read ?? 120} commits and{" "}
                {health?.limits.pulls_read ?? 80} pull requests.
              </em>
            </label>

            <div className="field-row">
              <label className="field">
                <span>From</span>
                <input type="date" value={start} onChange={(event) => setStart(event.target.value)} />
              </label>
              <label className="field">
                <span>To</span>
                <input type="date" value={end} onChange={(event) => setEnd(event.target.value)} />
              </label>
            </div>

            <label className="field">
              <span>Files — txt, md, csv, WhatsApp export, Slack JSON</span>
              <input
                type="file"
                multiple
                accept=".txt,.md,.markdown,.csv,.json,.log,.text"
                onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
              />
              <em>
                Up to {health?.limits.upload_files ?? 8} files,{" "}
                {health?.limits.upload_mb_per_file ?? 2} MB each. Files are used for this run and deleted
                after {health?.limits.session_ttl_hours ?? 72} hours.
              </em>
            </label>

            {files.length > 0 ? (
              <ul className="file-list">
                {files.map((file) => (
                  <li key={`${file.name}-${file.size}`}>
                    <span>{file.name}</span>
                    <span className="muted">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                  </li>
                ))}
              </ul>
            ) : null}

            {error ? <div className="alert alert-error">{error}</div> : null}

            <button className="btn btn-primary btn-lg" type="submit" disabled={Boolean(busy)}>
              Build the handover
            </button>
          </form>
        </section>

        <section className="explain">
          <div className="explain-block">
            <h2>How the pipeline works</h2>
            <ol className="steps">
              <li>
                <strong>Ingest</strong>
                <span>Repo history, PRs, reviews and issues, plus uploaded chats, tasks and notes.</span>
              </li>
              <li>
                <strong>Rule extraction</strong>
                <span>Ownership share, open work and people are computed, not guessed.</span>
              </li>
              <li>
                <strong>Cited drafting</strong>
                <span>Decisions, gotchas and the first week are drafted only from records that exist.</span>
              </li>
              <li>
                <strong>Verify, then review</strong>
                <span>Unknown ids are dropped, each citation is checked, and you approve what ships.</span>
              </li>
            </ol>
          </div>

          <div className="explain-block">
            <h2>What makes it checkable</h2>
            <div className="trust-grid">
              <article>
                <h3>Evidence first</h3>
                <p>
                  A claim without a real evidence id never reaches the review screen. Dropped claims are
                  counted and shown, not hidden.
                </p>
              </article>
              <article>
                <h3>Coverage check</h3>
                <p>
                  Areas the leaver touched that no claim mentions are listed with their records, so you
                  can see the gaps before the last day.
                </p>
              </article>
              <article>
                <h3>Human sign-off</h3>
                <p>
                  Approve, edit, reject or mark for confirmation. The export contains only approved
                  claims, with an append-only approval log and a content fingerprint.
                </p>
              </article>
            </div>
          </div>
        </section>

        <section className="anatomy">
          <h2>What the handover contains</h2>
          <div className="anatomy-grid">
            {(health?.sections ?? []).map((section) => (
              <div key={section.key}>
                <strong>{section.label}</strong>
                <p>{section.blurb}</p>
              </div>
            ))}
          </div>
        </section>
      </main>

      <footer className="site-foot">
        <p>
          Handover Lens · no accounts, no OAuth. A run id is an unguessable link that expires after{" "}
          {health?.limits.session_ttl_hours ?? 72} hours.
        </p>
        <p className="muted">
          {health
            ? `Storage: ${health.storage} · heavy actions limited to ${health.limits.heavy_requests_per_minute}/minute/IP · model calls capped daily`
            : "Checking server limits…"}
        </p>
      </footer>

      {busy ? <BusyOverlay label={busy.label} step={busy.step} steps={STEPS} /> : null}
    </div>
  );
}
