-- Operational schema for the Healthcare Insurance Claim Review Assistant.
-- All data is synthetic.

CREATE TABLE IF NOT EXISTS providers (
    provider_id    VARCHAR(20) PRIMARY KEY,
    provider_name  VARCHAR(200) NOT NULL
);

CREATE TABLE IF NOT EXISTS policy_master (
    policy_number       VARCHAR(30) PRIMARY KEY,
    effective_date      DATE NOT NULL,
    claim_limit_usd     NUMERIC(12, 2) NOT NULL,
    waiting_period_days INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS claims_history (
    claim_id        VARCHAR(40) PRIMARY KEY,
    member_id       VARCHAR(20) NOT NULL,
    policy_number   VARCHAR(30),
    provider_id     VARCHAR(20) REFERENCES providers(provider_id),
    service_date    DATE NOT NULL,
    procedure_code  VARCHAR(10) NOT NULL,
    billed_amount   NUMERIC(12, 2) NOT NULL,
    claimed_amount  NUMERIC(12, 2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_claims_duplicate
    ON claims_history (member_id, provider_id, service_date, procedure_code);

-- Workflow runs (used by the API in Day 3; created now so the schema is complete).
CREATE TABLE IF NOT EXISTS claim_runs (
    run_id       VARCHAR(40) PRIMARY KEY,
    claim_id     VARCHAR(40) NOT NULL,
    status       VARCHAR(30) NOT NULL,
    decision     VARCHAR(30),
    created_at   TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP NOT NULL DEFAULT NOW()
);
