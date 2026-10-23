-- ============================================================
-- Migration 036: move the QuickBooks refresh token into Supabase Vault
-- (bug list Oct 21 2026 #13)
-- ============================================================
-- ORDER MATTERS. Apply this ONLY AFTER the updated qb_connector.py is
-- pushed and one daily sync has run with it. The new connector reads
-- Vault first and falls back to the table, so it works before and after
-- this migration; the OLD connector only reads the table, so applying
-- this first would strand it with a blank token.
-- ============================================================

begin;

create or replace function public.qb_get_refresh_token(p_realm_id text)
returns text language sql security definer set search_path to '' as $f$
  select decrypted_secret from vault.decrypted_secrets
   where name = 'qb_refresh_token_' || p_realm_id
   order by updated_at desc limit 1;
$f$;

create or replace function public.qb_set_refresh_token(p_realm_id text, p_token text)
returns void language plpgsql security definer set search_path to '' as $f$
declare v_id uuid;
begin
  select id into v_id from vault.secrets where name = 'qb_refresh_token_' || p_realm_id;
  if v_id is null then
    perform vault.create_secret(p_token, 'qb_refresh_token_' || p_realm_id, 'QuickBooks OAuth refresh token (rotates every sync)');
  else
    perform vault.update_secret(v_id, p_token);
  end if;
  update public.qb_oauth_credentials set updated_at = now() where realm_id = p_realm_id;
end; $f$;

revoke all on function public.qb_get_refresh_token(text) from public, anon, authenticated;
revoke all on function public.qb_set_refresh_token(text, text) from public, anon, authenticated;
grant execute on function public.qb_get_refresh_token(text) to service_role;
grant execute on function public.qb_set_refresh_token(text, text) to service_role;

-- Copy the current token into Vault, then blank the plaintext column.
select public.qb_set_refresh_token(realm_id, refresh_token)
  from public.qb_oauth_credentials
 where coalesce(refresh_token, '') <> '';

alter table public.qb_oauth_credentials alter column refresh_token drop not null;
update public.qb_oauth_credentials set refresh_token = null
 where public.qb_get_refresh_token(realm_id) is not null;

comment on column public.qb_oauth_credentials.refresh_token is
  'Deprecated Oct 2026: token lives in Supabase Vault (qb_get_refresh_token / qb_set_refresh_token). Kept only so the realm row and updated_at survive.';

insert into public.da_schema_migrations (version, description)
values ('036', 'QuickBooks refresh token moved to Vault') on conflict (version) do nothing;

commit;
