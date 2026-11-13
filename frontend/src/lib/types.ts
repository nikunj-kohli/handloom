export type Confidence = "high" | "medium" | "low";

export type ClaimStatus =
  | "pending"
  | "approved"
  | "edited"
  | "rejected"
  | "needs_confirmation"
  | "dropped";

export interface Section {
  key: string;
  label: string;
  blurb: string;
}

export interface EvidenceSummary {
  id: string;
  source_type: string;
  source_label: string | null;
  external_id: string | null;
  title: string | null;
  author: string | null;
  occurred_at: string | null;
  url: string | null;
  areas: string[];
  snippet: string;
}

export interface EvidenceSearchResult {
  items: EvidenceSummary[];
  total: number;
  limit: number;
  offset: number;
  query: string;
}

export interface EvidenceDetail extends EvidenceSummary {
  body: string;
  area_labels: string[];
  metadata: Record<string, unknown>;
}

export interface Claim {
  id: string;
  session_id?: string;
  section: string;
  text: string;
  claim_type: string;
  confidence: Confidence;
  evidence_ids: string[];
  origin: "rules" | "model";
  verification: string;
  verification_note: string | null;
  status: ClaimStatus;
  final_text: string | null;
  note: string | null;
}

export interface CoverageGap {
  id: string;
  area: string;
  evidence_count: number;
  reason: string;
  evidence_ids: string[];
}

export interface Decision {
  id: string;
  claim_id: string;
  action: string;
  at: string;
  reviewer: string;
  note: string | null;
}

export interface Counts {
  evidence: number;
  claims: number;
  approved: number;
  edited: number;
  rejected: number;
  needs_confirmation: number;
  pending: number;
  dropped: number;
  reviewed: number;
}

export interface WarningsSummary {
  warnings?: string[];
  origin?: string;
  note?: string;
  repo?: {
    repo_full_name?: string;
    description?: string;
    commits_read?: number;
    pulls_read?: number;
    reviews_read?: number;
    has_token?: boolean;
    leaver_matched?: boolean;
  };
  stored_records?: number;
  generation?: {
    at?: string;
    llm_used?: boolean;
    dropped?: number;
    verification_note?: string;
    supporting?: {
      stats?: {
        commits?: number;
        pull_requests?: number;
        reviews?: number;
        tasks?: number;
        chats?: number;
        areas?: string[];
      };
    };
  };
}

export interface RunSession {
  id: string;
  created_at: string;
  updated_at: string;
  mode: "sample" | "live";
  project_name: string;
  repo_full_name: string | null;
  leaver_name: string;
  leaver_email: string;
  window_start: string | null;
  window_end: string | null;
  status: string;
  llm_status: string;
  llm_note: string | null;
  expires_at: string | null;
  summary: WarningsSummary;
}

export interface SessionPayload {
  session: RunSession;
  sections: Section[];
  evidence: EvidenceSummary[];
  claims: Claim[];
  gaps: CoverageGap[];
  decisions: Decision[];
  handovers: {
    token: string;
    created_at: string;
    reviewer: string;
    fingerprint: string;
    approved_count: number;
  }[];
  counts: Counts;
  cached?: boolean;
}

export interface Health {
  ok: boolean;
  app: string;
  version: string;
  storage: string;
  llm: {
    provider: string;
    model: string;
    configured: boolean;
    calls_today: number;
    daily_call_cap: number;
  };
  github_token: boolean;
  limits: {
    upload_mb_per_file: number;
    upload_mb_per_request: number;
    upload_files: number;
    commits_read: number;
    pulls_read: number;
    session_ttl_hours: number;
    heavy_requests_per_minute: number;
  };
  sections: Section[];
}

export interface SampleInfo {
  project_name: string;
  repo: string;
  leaver_name: string;
  window_start: string;
  window_end: string;
  note: string;
  record_count: number;
  by_source: Record<string, number>;
}

export interface SnapshotEvidence {
  id: string;
  source_type: string;
  source_label: string | null;
  external_id: string | null;
  title: string | null;
  author: string | null;
  occurred_at: string | null;
  url: string | null;
  areas: string[];
  excerpt: string;
}

export interface SnapshotClaim {
  id: string;
  text: string;
  original_text: string | null;
  confidence: Confidence;
  claim_type: string;
  origin: string;
  verification: string | null;
  verification_note: string | null;
  reviewer_note: string | null;
  status: ClaimStatus;
  evidence: SnapshotEvidence[];
}

export interface Snapshot {
  project: string;
  leaver: string;
  repo: string | null;
  window: { start: string | null; end: string | null };
  mode: string;
  session_id: string;
  generated_at: string | null;
  signed_at: string;
  reviewer: string;
  fingerprint: string;
  sections: { key: string; label: string; claims: SnapshotClaim[] }[];
  gaps: {
    area: string;
    label: string;
    reason: string;
    evidence_count: number;
    evidence: SnapshotEvidence[];
  }[];
  audit: { claim_id: string; action: string; at: string; reviewer: string; note: string | null }[];
  counts: {
    approved: number;
    edited: number;
    rejected: number;
    pending: number;
    dropped: number;
    sections: number;
    gaps: number;
  };
  omitted: { id: string; section: string; text: string; status: string; reason: string | null }[];
  sample_data: boolean;
}

export interface HandoverRecord {
  token: string;
  created_at: string;
  reviewer: string;
  fingerprint: string;
  counts: { approved: number; rejected: number; pending: number };
  payload: Snapshot;
}

export interface DecisionResponse {
  claim: Claim;
  counts: Omit<Counts, "evidence" | "claims">;
  decisions: Decision[];
}
