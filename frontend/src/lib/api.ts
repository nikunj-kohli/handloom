import type {
  DecisionResponse,
  EvidenceDetail,
  EvidenceSearchResult,
  HandoverRecord,
  Health,
  SampleInfo,
  SessionPayload,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and try again.", 0);
  }

  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      detail = "";
    }
    if (response.status === 429 && !detail) {
      detail = "That action is rate limited. Wait a minute and try again.";
    }
    throw new ApiError(detail || `Request failed (${response.status}).`, response.status);
  }
  return (await response.json()) as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Something went wrong.";
}

export const api = {
  health: () => request<Health>("/api/health"),
  sampleInfo: () => request<SampleInfo>("/api/sample"),
  createSample: () => request<SessionPayload>("/api/sessions/sample", { method: "POST" }),
  ingest: (form: FormData) =>
    request<SessionPayload>("/api/sessions/ingest", { method: "POST", body: form }),
  session: (id: string) => request<SessionPayload>(`/api/sessions/${encodeURIComponent(id)}`),
  searchEvidence: (id: string, params: URLSearchParams) =>
    request<EvidenceSearchResult>(
      `/api/sessions/${encodeURIComponent(id)}/evidence?${params.toString()}`,
    ),
  evidence: (id: string, evidenceId: string) =>
    request<EvidenceDetail>(
      `/api/sessions/${encodeURIComponent(id)}/evidence/${encodeURIComponent(evidenceId)}`,
    ),
  generate: (id: string, force: boolean) =>
    request<SessionPayload>(`/api/sessions/${encodeURIComponent(id)}/generate`, {
      method: "POST",
      body: JSON.stringify({ force }),
    }),
  decide: (
    id: string,
    claimId: string,
    body: { action: string; text?: string; note?: string; reviewer?: string },
  ) =>
    request<DecisionResponse>(
      `/api/sessions/${encodeURIComponent(id)}/claims/${encodeURIComponent(claimId)}/decision`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  sign: (id: string, reviewer: string) =>
    request<{ token: string; fingerprint: string; url: string }>(
      `/api/sessions/${encodeURIComponent(id)}/handover`,
      { method: "POST", body: JSON.stringify({ reviewer }) },
    ),
  handover: (token: string) => request<HandoverRecord>(`/api/handover/${encodeURIComponent(token)}`),
  verify: (token: string) =>
    request<{
      stored_fingerprint: string;
      recomputed_fingerprint: string;
      matches: boolean;
      signed_at: string;
      reviewer: string;
    }>(`/api/handover/${encodeURIComponent(token)}/verify`),
};

export function markdownUrl(token: string): string {
  return `/api/handover/${encodeURIComponent(token)}/markdown`;
}

export function pdfUrl(token: string): string {
  return `/api/handover/${encodeURIComponent(token)}/pdf`;
}

export function traceabilityUrl(token: string): string {
  return `/api/handover/${encodeURIComponent(token)}/traceability.csv`;
}

export function sessionTraceabilityUrl(id: string): string {
  return `/api/sessions/${encodeURIComponent(id)}/traceability.csv`;
}
