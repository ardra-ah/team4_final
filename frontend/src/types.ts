export type Decision = "APPROVED" | "REJECTED" | "PENDING_DOCUMENTS" | "ESCALATED";

export interface ClaimSummary {
  run_id: string;
  filename: string;
  created_at: string;
  status: "awaiting_review" | "completed";
  claim_id: string | null;
  claim_summary: string | null;
  route: string | null;
  recommended_decision: Decision | null;
  explanation: string | null;
  final_decision: Decision | null;
  reviewer_note: string | null;
  missing_fields: string[];
  policy_reasons: string[];
  policy_evidence: string[];
  duplicate_of: string[];
  risk_level: string | null;
  error: string | null;
  audit: string[];
  parent_run_id: string | null;
  resubmitted_as: string | null;
  processing_ms: number | null;
}