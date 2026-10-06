-- Kantor Virtual Vertex8 v6 — chat dengan semua agent (kecuali grok/Builder yang belum punya webhook).
-- Hanya mengubah objek kv_ / kv_private. Tidak menyentuh tabel lain.

-- 1) aktifkan chat untuk 7 agent (content sudah aktif). grok tetap "segera".
update public.kv_chat_agents set enabled = true
 where agent in ('analyst','marketing','member','performance','finance','hr','engineering');

-- 2) allowlist staf: '*' di allowed_agents = semua agent yang aktif (admin otomatis semua)
alter table public.kv_staff alter column allowed_agents set default '{*}';

create or replace function kv_private.kv_staff_can_chat(p_agent text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from kv_private.kv_staff_cur() s
                where s.is_admin or p_agent = any(s.allowed_agents) or '*' = any(s.allowed_agents))
     and exists(select 1 from public.kv_chat_agents a where a.agent = p_agent and a.enabled)
$$;

create or replace function kv_private.kv_chat_me_impl() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare s public.kv_staff; v_all boolean;
begin
  if auth.uid() is null then return jsonb_build_object('authorized', false); end if;
  select * into s from kv_private.kv_staff_cur();
  if not found then return jsonb_build_object('authorized', false); end if;
  if s.user_id is null then
    update public.kv_staff set user_id = auth.uid(), updated_at = now() where email = s.email and user_id is null;
  end if;
  v_all := s.is_admin or '*' = any(s.allowed_agents);
  return jsonb_build_object('authorized', true, 'email', s.email, 'display_name', s.display_name, 'is_admin', s.is_admin,
    'all_agents', v_all,
    'allowed_agents', coalesce((select jsonb_agg(a.agent order by a.sort) from public.kv_chat_agents a
                                 where a.enabled and (v_all or a.agent = any(s.allowed_agents))), '[]'::jsonb));
end $$;

create or replace function kv_private.kv_staff_admin_impl(p_token text, p_action text, p_email text, p_display_name text,
                                                          p_allowed text[], p_is_admin boolean)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_email text := lower(btrim(coalesce(p_email, ''))); v_uid uuid; v_bad text; v_n int; v_allowed text[] := p_allowed;
begin
  perform kv_private.kv_chat_check_admin(p_token);
  if p_action = 'list' then
    return coalesce((select jsonb_agg(jsonb_build_object('email', s.email, 'display_name', s.display_name,
              'allowed_agents', s.allowed_agents, 'is_admin', s.is_admin, 'active', s.active,
              'linked', s.user_id is not null,
              'auth_user', exists(select 1 from auth.users u where lower(u.email) = s.email),
              'auth_confirmed', exists(select 1 from auth.users u where lower(u.email) = s.email and u.email_confirmed_at is not null))
              order by s.email) from public.kv_staff s), '[]'::jsonb);
  elsif p_action = 'rotate_token' then
    if p_display_name !~ '^[0-9a-f]{64}$' then raise exception 'hash token baru tidak valid' using errcode = '22023'; end if;
    update kv_private.kv_chat_secrets set value = p_display_name, updated_at = now() where name = 'admin_token';
    return jsonb_build_object('ok', true);
  end if;
  if v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then raise exception 'email tidak valid' using errcode = '22023'; end if;
  if p_action = 'upsert' then
    if v_allowed is not null and ('*' = any(v_allowed) or 'all' = any(v_allowed)) then v_allowed := '{*}'; end if;
    select string_agg(x, ', ') into v_bad from unnest(coalesce(v_allowed, '{}')) x
      where x <> '*' and not exists(select 1 from public.kv_chat_agents a where a.agent = x);
    if v_bad is not null then raise exception 'agent tidak dikenal: %', v_bad using errcode = '22023'; end if;
    select u.id into v_uid from auth.users u where lower(u.email) = v_email and u.email_confirmed_at is not null
      order by u.created_at limit 1;
    insert into public.kv_staff(email, display_name, allowed_agents, is_admin, active, user_id)
    values (v_email, coalesce(nullif(btrim(p_display_name), ''), split_part(v_email, '@', 1)),
            coalesce(v_allowed, '{*}'), coalesce(p_is_admin, false), true, v_uid)
    on conflict (email) do update set
      display_name = coalesce(nullif(btrim(p_display_name), ''), public.kv_staff.display_name),
      allowed_agents = coalesce(v_allowed, public.kv_staff.allowed_agents),
      is_admin = coalesce(p_is_admin, public.kv_staff.is_admin),
      active = true,
      user_id = coalesce(v_uid, public.kv_staff.user_id),
      updated_at = now();
  elsif p_action in ('disable', 'enable') then
    update public.kv_staff set active = (p_action = 'enable'), updated_at = now() where email = v_email;
    get diagnostics v_n = row_count;
    if v_n = 0 then raise exception 'email belum ada di allowlist' using errcode = 'P0002'; end if;
  elsif p_action = 'remove' then
    delete from public.kv_staff where email = v_email;
    get diagnostics v_n = row_count;
    if v_n = 0 then raise exception 'email belum ada di allowlist' using errcode = 'P0002'; end if;
    return jsonb_build_object('removed', v_email);
  else
    raise exception 'aksi tidak dikenal: %', p_action using errcode = '22023';
  end if;
  return (select jsonb_build_object('email', s.email, 'display_name', s.display_name, 'allowed_agents', s.allowed_agents,
           'is_admin', s.is_admin, 'active', s.active, 'linked', s.user_id is not null,
           'auth_user', exists(select 1 from auth.users u where lower(u.email) = s.email),
           'auth_confirmed', exists(select 1 from auth.users u where lower(u.email) = s.email and u.email_confirmed_at is not null))
          from public.kv_staff s where s.email = v_email);
end $$;

-- 3) Edge Function: bila secret webhook agent belum ada, pesan TETAP pending (tidak hilang) + catatan ramah
--    untuk staf. Catatan terhapus otomatis saat pesan dibalas (kv_chat_reply_impl mengosongkan error_note).
create or replace function kv_private.kv_chat_notify_done_impl(p_message_id uuid, p_status text) returns void
language sql security definer set search_path = '' as $$
  update public.kv_chat_messages
     set wake_status = left(regexp_replace(lower(coalesce(p_status, 'gagal')), '[^a-z0-9_]', '_', 'g'), 40),
         error_note = case when p_status = 'belum_dikonfigurasi'
                           then 'Agent ini belum tersambung — pesanmu tersimpan dan akan dibalas setelah agent tersambung.'
                           else error_note end
   where id = p_message_id and wake_status = 'memanggil';
$$;
