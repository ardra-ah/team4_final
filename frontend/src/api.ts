import type { ClaimSummary, Decision } from "./types";

const BASE = "/api";

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body.detail === "string") return body.detail;
    return JSON.stringify(body.detail ?? body);
  } catch {
    return `Request failed with status ${res.status}`;
  }
}

export async function listClaims(): Promise<ClaimSummary[]> {
  const res = await fetch(`${BASE}/claims`);
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function uploadClaim(file: File): Promise<ClaimSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/claims`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function resubmitClaim(runId: string, file: File): Promise<ClaimSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}/claims/${runId}/resubmit`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}

export async function deleteClaim(runId: string): Promise<void> {
  const res = await fetch(`${BASE}/claims/${runId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await readError(res));
}

export async function decideClaim(
  runId: string,
  decision: Decision,
  note: string,
): Promise<ClaimSummary> {
  const res = await fetch(`${BASE}/claims/${runId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  });
  if (!res.ok) throw new Error(await readError(res));
  return res.json();
}