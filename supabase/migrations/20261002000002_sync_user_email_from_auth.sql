-- #307: el email del usuario tiene una sola fuente de verdad, `auth.users.email` (Supabase
-- Auth: con él se inicia sesión y a él llegan los correos). `public.users.email` pasa a ser
-- una copia que mantiene la base: cuando Auth cambia el email, este trigger lo copia a
-- `public.users` (y `updated_at`). La API lee la copia en `get_user_for_auth` y la cachea
-- `auth_user_cache_ttl_seconds` (60 s por defecto): `/users/me` ve el email nuevo como mucho
-- un TTL después del cambio.
--
-- Solo se copia un email no nulo: `public.users.email` es NOT NULL y un usuario de Auth sin
-- email (p. ej. solo teléfono) no debe romper el UPDATE de Auth.
--
-- SECURITY DEFINER con search_path vacío: quien actualiza `auth.users` es el rol de Auth
-- (`supabase_auth_admin`), que no tiene permisos sobre `public.users`.

begin;

create or replace function public.sync_user_email_from_auth()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  update public.users
     set email = new.email,
         updated_at = now()
   where id = new.id
     and email is distinct from new.email;
  return null;
end;
$$;

revoke all on function public.sync_user_email_from_auth() from public, anon, authenticated;

drop trigger if exists trg_auth_users_sync_email on auth.users;

create trigger trg_auth_users_sync_email
  after update of email on auth.users
  for each row
  when (new.email is not null and old.email is distinct from new.email)
  execute function public.sync_user_email_from_auth();

-- Backfill: corrige los emails que ya se desincronizaron (p. ej. el super_admin, sesión 83).
update public.users u
   set email = a.email,
       updated_at = now()
  from auth.users a
 where a.id = u.id
   and a.email is not null
   and u.email is distinct from a.email;

commit;
