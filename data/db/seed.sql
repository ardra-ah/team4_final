TRUNCATE claims_history, providers, policy_master;

INSERT INTO providers (provider_id, provider_name) VALUES ('PRV-0042', 'Sample City Clinic');
INSERT INTO providers (provider_id, provider_name) VALUES ('PRV-0107', 'Demo General Hospital');
INSERT INTO providers (provider_id, provider_name) VALUES ('PRV-0215', 'Fictional Diagnostics Lab');
INSERT INTO policy_master (policy_number, effective_date, claim_limit_usd, waiting_period_days) VALUES ('POL-HC-5599', '2026-08-01', 5000.0, 30);
INSERT INTO claims_history (claim_id, member_id, policy_number, provider_id, service_date, procedure_code, billed_amount, claimed_amount) VALUES ('CLM-2026-HIST-001', 'MBR-99901', 'POL-HC-5599', 'PRV-0042', '2026-08-14', '99213', 180.0, 180.0);