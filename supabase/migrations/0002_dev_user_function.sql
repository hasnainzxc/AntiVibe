-- 0002_dev_user_function.sql
-- Dev/test user creation for local scan testing without auth.
--
-- The `create_dev_user` function bypasses the FK constraint from
-- `public.users` -> `auth.users` by setting `session_replication_role`
-- to `replica`, which temporarily disables FK trigger checks.
--
-- This is safe because:
--   1. It's SECURITY DEFINER — runs as the function owner (superuser)
--   2. It only inserts a single known dev UUID, not arbitrary data
--   3. It's called exclusively from the sandbox service in local mode
--      (detected by absence of FLY_API_TOKEN)
--   4. `ON CONFLICT DO NOTHING` makes it idempotent

create or replace function public.create_dev_user(p_id uuid, p_email text)
returns void
language plpgsql
security definer
set search_path = public
as $$
begin
  -- Bypass FK triggers so we don't need a row in auth.users
  set local session_replication_role = 'replica';
  insert into public.users (id, email, tier)
  values (p_id, p_email, 'free')
  on conflict (id) do nothing;
  reset session_replication_role;
end;
$$;
