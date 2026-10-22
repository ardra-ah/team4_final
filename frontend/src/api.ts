import type { ClaimSummary, Decision } from "./types";

const BASE = "/api";

/** An error with a message that is safe to show to a non-technical user. */
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

const UNREACHABLE = "We could not reach the claim assistant. Check that it is running, then try again.";

async function send(url: string, init?: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init);
  } catch {
    throw new ApiError(UNREACHABLE, 0);
  }
}

async function ensureOk(res: Response): Promise<void> {
  if (res.ok) return;
  throw new ApiError(await plainMessage(res), res.status);
}

/** Turn a failed response into one short sentence a non-technical user can act on. */
async function plainMessage(res: Response): Promise<string> {
  let detail: unknown = null;
  try {
    const body = await res.json();
    detail = body.detail;
  } catch {
    detail = null;
  }

  // The API sends plain-language messages as strings. Anything else (such as a list of
  // validation errors) is technical, so we use a general message for it instead.
  if (typeof detail === "string" && detail.trim() && res.status < 500) {
    return detail;
  }

  switch (res.status) {
    case 400:
    case 422:
      return "Please check the file or details and try again.";
    case 404:
      return "This claim could not be found. It may have been removed.";
    case 409:
      return "This action cannot be completed right now.";
    default:
      return "Something went wrong on our side. Please try again in a moment.";
  }
}

export async function listClaims(): Promise<ClaimSummary[]> {
  const res = await send(`${BASE}/claims`);
  await ensureOk(res);
  return res.json();
}

export async function uploadClaim(file: File): Promise<ClaimSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await send(`${BASE}/claims`, { method: "POST", body: form });
  await ensureOk(res);
  return res.json();
}

export async function resubmitClaim(runId: string, file: File): Promise<ClaimSummary> {
  const form = new FormData();
  form.append("file", file);
  const res = await send(`${BASE}/claims/${runId}/resubmit`, { method: "POST", body: form });
  await ensureOk(res);
  return res.json();
}

export async function deleteClaim(runId: string): Promise<void> {
  const res = await send(`${BASE}/claims/${runId}`, { method: "DELETE" });
  await ensureOk(res);
}

export async function decideClaim(
  runId: string,
  decision: Decision,
  note: string,
): Promise<ClaimSummary> {
  const res = await send(`${BASE}/claims/${runId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision, note }),
  });
  await ensureOk(res);
  return res.json();
}
