import type { ClaimStatus, Confidence } from "../lib/types";

const CONFIDENCE_LABEL: Record<Confidence, string> = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

export function ConfidenceBadge({ level }: { level: Confidence }) {
  return <span className={`badge conf-${level}`}>{CONFIDENCE_LABEL[level] ?? level}</span>;
}

export function OriginBadge({ origin }: { origin: string }) {
  return (
    <span className={`badge origin-${origin === "model" ? "model" : "rules"}`}>
      {origin === "model" ? "Model drafted" : "Rule derived"}
    </span>
  );
}

const SOURCE_SHORT: Record<string, string> = {
  git_commit: "commit",
  pull_request: "PR",
  review: "review",
  issue: "issue",
  task: "task",
  chat: "chat",
  meeting_note: "notes",
  document: "doc",
};

export function sourceShort(type: string): string {
  return SOURCE_SHORT[type] ?? type.replace(/_/g, " ");
}

export function SourceBadge({ type }: { type: string }) {
  return <span className={`badge source source-${type}`}>{sourceShort(type)}</span>;
}

export const STATUS_LABEL: Record<ClaimStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  edited: "Edited",
  rejected: "Rejected",
  needs_confirmation: "Needs confirmation",
  dropped: "Dropped",
};

export function StatusBadge({ status }: { status: ClaimStatus }) {
  return <span className={`badge status status-${status}`}>{STATUS_LABEL[status]}</span>;
}
