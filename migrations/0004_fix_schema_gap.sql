-- Migration 0004: Fix schema mismatch between Python orchestrator and DB
-- The orchestrator writes tier1_findings, tier2_findings, total_findings,
-- tier1_duration_ms, tier2_duration_ms, llm_tokens_in, llm_tokens_out
-- to the scans table, but these columns never existed in the schema.

ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS tier1_findings jsonb;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS tier2_findings jsonb;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS total_findings integer DEFAULT 0;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS tier1_duration_ms integer;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS tier2_duration_ms integer;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS llm_tokens_in integer DEFAULT 0;
ALTER TABLE public.scans ADD COLUMN IF NOT EXISTS llm_tokens_out integer DEFAULT 0;
