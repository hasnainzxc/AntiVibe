-- 0003_add_duration_ms.sql
-- Add duration_ms column to scans table for dashboard display of scan duration.

alter table public.scans add column if not exists duration_ms integer default 0;
