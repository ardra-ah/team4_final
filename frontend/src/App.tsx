import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { ApiError, decideClaim, deleteClaim, listClaims, resubmitClaim, uploadClaim } from "./api";
import type { ClaimSummary, Decision } from "./types";

type Tone = "success" | "danger" | "warning" | "neutral" | "info";
type View = "queue" | "all" | "completed";
type IconName = "upload" | "trash" | "search" | "refresh" | "queue" | "list" | "check" | "back";

interface Toast {
  id: number;
  tone: Tone;
  text: string;
}

const VIEW_LABEL: Record<View, string> = {
  queue: "Review queue",
  all: "All claims",
  completed: "Completed",
};

const VIEW_HINT: Record<View, string> = {
  queue: "Claims waiting for a reviewer decision.",
  all: "Every claim processed by the assistant.",
  completed: "Claims with a final decision.",
};

const VIEW_ICON: Record<View, IconName> = {
  queue: "queue",
  all: "list",
  completed: "check",
};

const DECISION_LABEL: Record<Decision, string> = {
  APPROVED: "Approved",
  REJECTED: "Rejected",
  PENDING_DOCUMENTS: "Documents requested",
  ESCALATED: "Escalated",
};

const DECISION_TONE: Record<Decision, Tone> = {
  APPROVED: "success",
  REJECTED: "danger",
  PENDING_DOCUMENTS: "warning",
  ESCALATED: "neutral",
};

const ROUTE_LABEL: Record<string, string> = {
  approval: "Approval",
  investigation: "Investigation",
  clarification: "Clarification",
  rejection_review: "Rejection review",
};

const ACTIONS: { label: string; decision: Decision; tone: Tone; hint: string }[] = [
  { label: "Approve", decision: "APPROVED", tone: "success", hint: "Accept the claim for payment" },
  { label: "Reject", decision: "REJECTED", tone: "danger", hint: "Deny the claim" },
  { label: "Request documents", decision: "PENDING_DOCUMENTS", tone: "warning", hint: "Ask for missing information" },
  { label: "Escalate", decision: "ESCALATED", tone: "neutral", hint: "Send to manual investigation" },
];

const ICON_PATHS: Record<IconName, string> = {
  upload: "M12 16V4m0 0l-4 4m4-4l4 4M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2",
  trash: "M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3",
  search: "M21 21l-4.35-4.35M17 10.5a6.5 6.5 0 11-13 0 6.5 6.5 0 0113 0z",
  refresh: "M4 4v6h6M20 20v-6h-6M5.1 15a8 8 0 0013.2 2.6M18.9 9A8 8 0 005.8 6.4L4 10",
  queue: "M4 6h16M4 12h10M4 18h7",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  check: "M5 13l4 4L19 7",
  back: "M15 18l-6-6 6-6",
};

function Icon({ name }: { name: IconName }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="16"
      height="16"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  );
}

function messageOf(e: unknown): string {
  return e instanceof Error ? e.message : "Something went wrong. Please try again.";
}

/** A duplicate or "cannot do this right now" message is a warning, not a failure. */
function toneOf(e: unknown): Tone {
  return e instanceof ApiError && e.status === 409 ? "warning" : "danger";
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function routeLabel(route: string | null): string {
  if (!route) return "-";
  const label = ROUTE_LABEL[route];
  return label ? label : route;
}

function statusOf(claim: ClaimSummary): { label: string; tone: Tone } {
  if (claim.status === "awaiting_review") return { label: "Awaiting review", tone: "warning" };
  if (claim.final_decision) {
    return { label: DECISION_LABEL[claim.final_decision], tone: DECISION_TONE[claim.final_decision] };
  }
  return { label: "Completed", tone: "neutral" };
}

function riskTone(risk: string | null): Tone {
  if (risk === "high") return "danger";
  if (risk === "low") return "success";
  return "neutral";
}

export default function App() {
  const [claims, setClaims] = useState<ClaimSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [view, setView] = useState<View>("queue");
  const [query, setQuery] = useState("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [confirmDelete, setConfirmDelete] = useState<ClaimSummary | null>(null);
  const [deleting, setDeleting] = useState(false);
  const toastSeq = useRef(0);

  const pushToast = useCallback((tone: Tone, text: string) => {
    toastSeq.current += 1;
    const id = toastSeq.current;
    setToasts((prev) => [...prev, { id, tone, text }]);
    setTimeout(() => setToasts((prev) => prev.filter((t) => t.id !== id)), 4500);
  }, []);

  const refresh = useCallback(async () => {
    try {
      setClaims(await listClaims());
      setLoadError(null);
    } catch (e) {
      setLoadError(messageOf(e));
    }
  }, []);

  useEffect(() => {
    refresh();
    const timer = setInterval(refresh, 5000);
    return () => clearInterval(timer);
  }, [refresh]);

  async function handleUpload(file: File) {
    setUploading(true);
    try {
      const created = await uploadClaim(file);
      setSelectedId(created.run_id);
      setView("all");
      setQuery("");
      await refresh();
      pushToast("success", "Claim uploaded and checked.");
    } catch (e) {
      pushToast(toneOf(e), messageOf(e));
    } finally {
      setUploading(false);
    }
  }

  async function handleDelete(claim: ClaimSummary) {
    setDeleting(true);
    try {
      await deleteClaim(claim.run_id);
      setClaims((prev) => prev.filter((c) => c.run_id !== claim.run_id));
      if (selectedId === claim.run_id) setSelectedId(null);
      setConfirmDelete(null);
      pushToast("success", "Claim removed.");
    } catch (e) {
      pushToast(toneOf(e), messageOf(e));
    } finally {
      setDeleting(false);
    }
  }

  const counts = useMemo(
    () => ({
      queue: claims.filter((c) => c.status === "awaiting_review").length,
      all: claims.length,
      completed: claims.filter((c) => c.status === "completed").length,
    }),
    [claims],
  );

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return [...claims]
      .sort((a, b) => b.created_at.localeCompare(a.created_at))
      .filter((c) => {
        if (view === "queue" && c.status !== "awaiting_review") return false;
        if (view === "completed" && c.status !== "completed") return false;
        if (!q) return true;
        return (c.claim_id ?? "").toLowerCase().includes(q) || c.filename.toLowerCase().includes(q);
      });
  }, [claims, view, query]);

  const selected = claims.find((c) => c.run_id === selectedId) ?? null;

  return (
    <div className="shell">
      <aside className="nav">
        <div className="brand">
          <div className="brand-mark">CR</div>
          <div>
            <div className="brand-title">Claim Review</div>
            <div className="brand-sub">Assistant</div>
          </div>
        </div>

        <p className="nav-label">Workspace</p>
        <nav className="nav-list">
          {(Object.keys(VIEW_LABEL) as View[]).map((v) => (
            <button
              key={v}
              className={v === view ? "nav-item active" : "nav-item"}
              onClick={() => setView(v)}
            >
              <Icon name={VIEW_ICON[v]} />
              <span className="nav-text">{VIEW_LABEL[v]}</span>
              <span className="nav-count">{counts[v]}</span>
            </button>
          ))}
        </nav>

        <div className="nav-foot">
          <div className="nav-foot-title">Synthetic data only</div>
          <div className="nav-foot-text">Local PostgreSQL · Gemini explanations · LangSmith tracing</div>
        </div>
      </aside>

      <div className="main">
        <header className="page-header">
          <div>
            <h1>{VIEW_LABEL[view]}</h1>
            <p className="page-sub">{VIEW_HINT[view]}</p>
          </div>
          <div className="page-actions">
            <button className="btn secondary" onClick={refresh}>
              <Icon name="refresh" />
              Refresh
            </button>
            <label className={uploading ? "btn primary disabled" : "btn primary"}>
              <Icon name="upload" />
              {uploading ? "Processing..." : "Upload claim"}
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={uploading}
                hidden
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) handleUpload(file);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        </header>

        <StatsRow claims={claims} />

        {loadError && <div className="banner error">{loadError}</div>}

        <div className="split">
          <section className="list-panel">
            <div className="search">
              <Icon name="search" />
              <input
                type="search"
                placeholder="Search by claim ID or file name"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="list-head">
              <span>Claim</span>
              <span>Status</span>
            </div>
            <ul className="claim-list">
              {visible.length === 0 ? (
                <li className="list-empty">
                  {claims.length === 0 ? "No claims yet. Upload a PDF to begin." : "No claims match this view."}
                </li>
              ) : (
                visible.map((c) => (
                  <ClaimRow
                    key={c.run_id}
                    claim={c}
                    active={c.run_id === selectedId}
                    onSelect={() => setSelectedId(c.run_id)}
                  />
                ))
              )}
            </ul>
          </section>

          <section className="detail-panel">
            {selected ? (
              <ClaimDetail
                key={selected.run_id}
                claim={selected}
                onDecided={(updated) => {
                  setClaims((prev) => prev.map((c) => (c.run_id === updated.run_id ? updated : c)));
                  pushToast("success", "Decision saved.");
                }}
                onError={(e) => pushToast(toneOf(e), messageOf(e))}
                onNavigate={(id) => setSelectedId(id)}
                onResubmitted={(newId) => {
                  refresh();
                  setSelectedId(newId);
                  pushToast("success", "Corrected claim uploaded and checked.");
                }}
                onDelete={() => setConfirmDelete(selected)}
              />
            ) : (
              <EmptyState />
            )}
          </section>
        </div>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete this claim?"
          message={`This permanently removes ${confirmDelete.claim_id ?? "this claim"} from the review history, including its audit trail and stored PDF. Reference data used for duplicate checks is not changed.`}
          confirmLabel="Delete claim"
          busy={deleting}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => handleDelete(confirmDelete)}
        />
      )}

      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.tone}`}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}

function Badge({ tone, children }: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`badge ${tone}`}>
      <span className="dot" />
      {children}
    </span>
  );
}

function StatsRow({ claims }: { claims: ClaimSummary[] }) {
  const awaiting = claims.filter((c) => c.status === "awaiting_review").length;
  const approved = claims.filter((c) => c.final_decision === "APPROVED").length;
  const rejected = claims.filter((c) => c.final_decision === "REJECTED").length;
  const timed = claims.map((c) => c.processing_ms).filter((ms): ms is number => ms !== null);
  const avgMs = timed.length ? Math.round(timed.reduce((a, b) => a + b, 0) / timed.length) : null;
  const errors = claims.filter((c) => c.error).length;
  const tiles: { label: string; value: string; tone: Tone }[] = [
    { label: "Total claims", value: String(claims.length), tone: "info" },
    { label: "Awaiting review", value: String(awaiting), tone: "warning" },
    { label: "Approved", value: String(approved), tone: "success" },
    { label: "Rejected", value: String(rejected), tone: "danger" },
    {
      label: "Avg processing",
      value: avgMs === null ? "-" : avgMs < 1000 ? `${avgMs} ms` : `${(avgMs / 1000).toFixed(1)} s`,
      tone: "neutral",
    },
    { label: "Errors", value: String(errors), tone: errors > 0 ? "danger" : "success" },
  ];
  return (
    <section className="stats">
      {tiles.map((t) => (
        <div className="stat" key={t.label}>
          <div className="stat-label">{t.label}</div>
          <div className="stat-row">
            <span className="stat-value">{t.value}</span>
            <span className={`stat-bar ${t.tone}`} />
          </div>
        </div>
      ))}
    </section>
  );
}

function ClaimRow({ claim, active, onSelect }: { claim: ClaimSummary; active: boolean; onSelect: () => void }) {
  const status = statusOf(claim);
  return (
    <li>
      <button className={active ? "claim-row active" : "claim-row"} onClick={onSelect}>
        <div className="row-main">
          <div className="row-title">{claim.claim_id ?? "Unidentified claim"}</div>
          <div className="row-sub">{claim.filename}</div>
          <div className="row-meta">
            {routeLabel(claim.route)} · {formatDate(claim.created_at)}
          </div>
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </button>
    </li>
  );
}

function EmptyState() {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Icon name="list" />
      </div>
      <div className="empty-title">No claim selected</div>
      <p>Choose a claim from the list to review its findings and audit trail.</p>
    </div>
  );
}

function Section({ title, children, aside }: { title: string; children: ReactNode; aside?: ReactNode }) {
  return (
    <section className="panel">
      <header className="panel-head">
        <h3>{title}</h3>
        {aside}
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}

function ClaimDetail({
  claim,
  onDecided,
  onError,
  onNavigate,
  onResubmitted,
  onDelete,
}: {
  claim: ClaimSummary;
  onDecided: (c: ClaimSummary) => void;
  onError: (e: unknown) => void;
  onNavigate: (runId: string) => void;
  onResubmitted: (newRunId: string) => void;
  onDelete: () => void;
}) {
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const status = statusOf(claim);
  const findings: { title: string; items: string[] }[] = [
    { title: "Missing fields", items: claim.missing_fields },
    { title: "Policy reasons", items: claim.policy_reasons },
    { title: "Policy evidence", items: claim.policy_evidence },
    { title: "Possible duplicates", items: claim.duplicate_of },
  ].filter((f) => f.items.length > 0);

  async function act(decision: Decision) {
    setSaving(true);
    try {
      const updated = await decideClaim(claim.run_id, decision, note);
      onDecided(updated);
      setNote("");
    } catch (e) {
      onError(e);
    } finally {
      setSaving(false);
    }
  }

  return (
    <article className="detail">
      <header className="detail-head">
        <div className="detail-titles">
          <div className="eyebrow">Claim review</div>
          <h2 className="detail-title">{claim.claim_id ?? "Unidentified claim"}</h2>
          <p className="detail-sub">
            {claim.filename} · received {formatDate(claim.created_at)}
          </p>
        </div>
        <div className="detail-actions">
          <Badge tone={status.tone}>{status.label}</Badge>
          <button className="btn danger-ghost" onClick={onDelete}>
            <Icon name="trash" />
            Delete
          </button>
        </div>
      </header>

      {claim.error && <div className="banner error">{claim.error}</div>}

      {claim.parent_run_id && (
        <div className="notice">
          This is a resubmission of an earlier claim.{" "}
          <button className="link" onClick={() => onNavigate(claim.parent_run_id as string)}>
            View original
          </button>
        </div>
      )}
      {claim.resubmitted_as && (
        <div className="notice">
          Corrected documents were submitted as a new claim.{" "}
          <button className="link" onClick={() => onNavigate(claim.resubmitted_as as string)}>
            View resubmission
          </button>
        </div>
      )}

      {claim.claim_summary && (
        <Section title="Claim summary">
          <p className="body-text">{claim.claim_summary}</p>
        </Section>
      )}

      <div className="kpis">
        <Kpi label="Route" value={routeLabel(claim.route)} />
        <Kpi label="Risk level" value={claim.risk_level ?? "-"} tone={riskTone(claim.risk_level)} />
        <Kpi
          label="Recommended"
          value={claim.recommended_decision ? DECISION_LABEL[claim.recommended_decision] : "-"}
        />
        <Kpi label="Final decision" value={claim.final_decision ? DECISION_LABEL[claim.final_decision] : "Pending"} />
      </div>

      {claim.explanation && (
        <Section title="Recommendation">
          <p className="body-text">{claim.explanation}</p>
        </Section>
      )}

      <Section title="Findings">
        {findings.length === 0 ? (
          <p className="ok-note">No issues found. All checks passed.</p>
        ) : (
          <div className="findings">
            {findings.map((f) => (
              <div className="finding" key={f.title}>
                <div className="finding-title">{f.title}</div>
                <ul>
                  {f.items.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Section>

      {claim.status === "awaiting_review" && (
        <Section title="Reviewer decision">
          <textarea
            className="note-input"
            placeholder="Optional note for the audit trail"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={3}
            disabled={saving}
          />
          <div className="action-grid">
            {ACTIONS.map((a) => (
              <button
                key={a.decision}
                className={`action ${a.tone}`}
                disabled={saving}
                onClick={() => act(a.decision)}
                title={a.hint}
              >
                <span className="action-label">{a.label}</span>
                <span className="action-hint">{a.hint}</span>
              </button>
            ))}
          </div>
        </Section>
      )}

      {claim.final_decision === "PENDING_DOCUMENTS" && !claim.resubmitted_as && (
        <ResubmitSection runId={claim.run_id} onSubmitted={onResubmitted} onError={onError} />
      )}

      {claim.reviewer_note && (
        <Section title="Reviewer note">
          <p className="body-text">{claim.reviewer_note}</p>
        </Section>
      )}

      <Section title="Audit trail">
        <ol className="timeline">
          {claim.audit.map((line, i) => (
            <li key={i}>{line}</li>
          ))}
        </ol>
      </Section>
    </article>
  );
}

function ResubmitSection({
  runId,
  onSubmitted,
  onError,
}: {
  runId: string;
  onSubmitted: (newRunId: string) => void;
  onError: (e: unknown) => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <Section title="Corrected documents">
      <p className="muted-text">
        Documents were requested. Upload the corrected or missing claim PDF to run it again. The new run is linked to this
        claim.
      </p>
      <label className={busy ? "dropzone busy" : "dropzone"}>
        <Icon name="upload" />
        <span className="dropzone-title">{busy ? "Processing resubmission..." : "Upload corrected PDF"}</span>
        <input
          type="file"
          accept="application/pdf,.pdf"
          disabled={busy}
          hidden
          onChange={async (e) => {
            const file = e.target.files?.[0];
            e.target.value = "";
            if (!file) return;
            setBusy(true);
            try {
              const created = await resubmitClaim(runId, file);
              onSubmitted(created.run_id);
            } catch (err) {
              onError(err);
            } finally {
              setBusy(false);
            }
          }}
        />
      </label>
    </Section>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone?: Tone }) {
  return (
    <div className="kpi">
      <div className="kpi-label">{label}</div>
      <div className={tone ? `kpi-value ${tone}` : "kpi-value"}>{value}</div>
    </div>
  );
}

function ConfirmDialog({
  title,
  message,
  confirmLabel,
  busy,
  onCancel,
  onConfirm,
}: {
  title: string;
  message: string;
  confirmLabel: string;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="overlay" role="presentation" onClick={onCancel}>
      <div className="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title" onClick={(e) => e.stopPropagation()}>
        <h2 id="dialog-title">{title}</h2>
        <p>{message}</p>
        <div className="dialog-actions">
          <button className="btn secondary" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="btn danger" onClick={onConfirm} disabled={busy}>
            {busy ? "Deleting..." : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
