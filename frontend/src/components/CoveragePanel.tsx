import type { CoverageGap } from "../lib/types";

interface Props {
  gaps: CoverageGap[];
  onSelect: (evidenceId: string) => void;
}

export default function CoveragePanel({ gaps, onSelect }: Props) {
  return (
    <section className="coverage">
      <div className="coverage-head">
        <h2>Coverage check</h2>
        <span className={`coverage-count ${gaps.length ? "has-gaps" : "clean"}`}>
          {gaps.length ? `${gaps.length} uncovered` : "no gaps found"}
        </span>
      </div>
      <p className="coverage-intro">
        Areas the leaver touched that no claim mentions. This is what the AI missed — a successor can
        ask about it before the last day.
      </p>

      {gaps.length === 0 ? (
        <p className="coverage-clean">
          Every area with recorded activity is represented by at least one claim. That is unusual —
          check the evidence list before you trust it.
        </p>
      ) : (
        <ul className="coverage-list">
          {gaps.map((gap) => (
            <li key={gap.id} className="coverage-item">
              <div className="coverage-item-head">
                <strong>{gap.area.replace(/-/g, " ")}</strong>
                <span className="tag">{gap.evidence_count} records</span>
              </div>
              <p>{gap.reason}</p>
              <div className="coverage-chips">
                {gap.evidence_ids.map((evidenceId) => (
                  <button key={evidenceId} className="chip" onClick={() => onSelect(evidenceId)}>
                    <span className="chip-id">{evidenceId}</span>
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
