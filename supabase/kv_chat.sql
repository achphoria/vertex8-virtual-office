-- Kantor Virtual Vertex8 — fitur "Ngobrol dengan Agent" (prototipe)
-- Hanya membuat objek BARU berawalan kv_ / skema kv_private. Tidak mengubah tabel lain.
-- Token (penulis/admin) TIDAK pernah disimpan di sini; DB hanya menyimpan hash sha256-nya.

create extension if not exists pg_net with schema extensions;  -- dipakai trigger untuk memanggil Edge Function kv-chat-notify (fungsi di skema net)

grant usage on schema kv_private to authenticated, service_role;

-- ---------- rahasia khusus chat (hash token admin) ----------
create table if not exists kv_private.kv_chat_secrets(
  name text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);
alter table kv_private.kv_chat_secrets enable row level security;
revoke all on kv_private.kv_chat_secrets from public, anon, authenticated, service_role;
create policy kv_chat_secrets_deny_all on kv_private.kv_chat_secrets for all to anon, authenticated using (false) with check (false);

-- ---------- daftar agent yang bisa diajak ngobrol ----------
create table public.kv_chat_agents(
  agent text primary key check (agent ~ '^[a-z0-9][a-z0-9_-]{0,31}$'),
  display_name text not null,
  role_label text,
  enabled boolean not null default false,
  sort int not null default 0
);
alter table public.kv_chat_agents enable row level security;
revoke all on public.kv_chat_agents from anon, authenticated;
grant select on public.kv_chat_agents to anon, authenticated;
create policy kv_chat_agents_read on public.kv_chat_agents for select to anon, authenticated using (true);
insert into public.kv_chat_agents(agent, display_name, role_label, enabled, sort) values
  ('grok','Mr. Wakidi','Builder',false,1),
  ('analyst','Mr. Wiyadi','Ops & Data',false,2),
  ('marketing','Mr. Wahyudi','Marketing',false,3),
  ('member','Mr. Widodo','Member Success',false,4),
  ('performance','Mr. Winarto','Performance',false,5),
  ('finance','Mr. Wibowo','Finance',false,6),
  ('content','Mr. Wawan','Content & Creative',true,7),
  ('hr','Mr. Wisnu','HR & People',false,8),
  ('engineering','Mr. Warsito','Engineering & Facility',false,9);

-- ---------- allowlist staf ----------
create table public.kv_staff(
  email text primary key check (email = lower(email) and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  display_name text not null check (length(display_name) between 1 and 60),
  allowed_agents text[] not null default '{content}',
  is_admin boolean not null default false,
  active boolean not null default true,
  user_id uuid unique references auth.users(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
alter table public.kv_staff enable row level security;
revoke all on public.kv_staff from anon, authenticated;
grant select (email, display_name, allowed_agents, is_admin, active) on public.kv_staff to authenticated;
create policy kv_staff_read_own on public.kv_staff for select to authenticated using (user_id = (select auth.uid()));

-- ---------- pesan chat ----------
create table public.kv_chat_messages(
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null default auth.uid() references auth.users(id) on delete cascade,
  agent text not null references public.kv_chat_agents(agent),
  role text not null check (role in ('staff','agent')),
  content text not null check (length(content) between 1 and 4000),
  status text not null default 'pending' check (status in ('pending','answered','error')),
  sender_name text,
  reply_to uuid references public.kv_chat_messages(id) on delete set null,
  picked_at timestamptz,
  notified_at timestamptz,
  wake_status text check (wake_status ~ '^[a-z0-9_]{1,40}$'),
  error_note text,
  created_at timestamptz not null default now(),
  answered_at timestamptz
);
create index kv_chat_messages_thread_idx on public.kv_chat_messages(user_id, agent, created_at desc);
create index kv_chat_messages_pending_idx on public.kv_chat_messages(agent, created_at) where status = 'pending' and role = 'staff';
create index kv_chat_messages_reply_idx on public.kv_chat_messages(reply_to);
alter table public.kv_chat_messages enable row level security;
revoke all on public.kv_chat_messages from anon, authenticated;
grant select on public.kv_chat_messages to authenticated;
grant insert (user_id, agent, role, content) on public.kv_chat_messages to authenticated;

-- ---------- helper (SECURITY DEFINER, tidak terekspos lewat REST) ----------
-- Staf aktif yang sedang login: email harus sudah terkonfirmasi, dan baris allowlist terikat ke user ini
-- (atau belum terikat tapi emailnya sama).
create function kv_private.kv_staff_cur() returns setof public.kv_staff
language sql stable security definer set search_path = '' as $$
  select s.* from public.kv_staff s
  join auth.users u on u.id = auth.uid()
  where s.active and u.email_confirmed_at is not null
    and (s.user_id = u.id or (s.user_id is null and s.email = lower(u.email)))
  limit 1
$$;
create function kv_private.kv_staff_active() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from kv_private.kv_staff_cur())
$$;
create function kv_private.kv_staff_is_admin() returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from kv_private.kv_staff_cur() s where s.is_admin)
$$;
create function kv_private.kv_staff_can_chat(p_agent text) returns boolean
language sql stable security definer set search_path = '' as $$
  select exists(select 1 from kv_private.kv_staff_cur() s where s.is_admin or p_agent = any(s.allowed_agents))
     and exists(select 1 from public.kv_chat_agents a where a.agent = p_agent and a.enabled)
$$;

create policy kv_chat_read on public.kv_chat_messages for select to authenticated
  using ((user_id = (select auth.uid()) and (select kv_private.kv_staff_active()))
         or (select kv_private.kv_staff_is_admin()));
create policy kv_chat_insert on public.kv_chat_messages for insert to authenticated
  with check (user_id = (select auth.uid()) and role = 'staff' and kv_private.kv_staff_can_chat(agent));

-- ---------- trigger: normalisasi + batas laju, lalu bangunkan agent ----------
create function kv_private.kv_chat_before_insert() returns trigger
language plpgsql security definer set search_path = '' as $$
declare v_name text; v_n int;
begin
  if new.role = 'staff' then
    new.content := btrim(coalesce(new.content, ''));
    if length(new.content) = 0 then raise exception 'Pesan kosong' using errcode = '22023'; end if;
    if length(new.content) > 2000 then raise exception 'Pesan terlalu panjang (maks 2000 karakter)' using errcode = '22023'; end if;
    new.status := 'pending'; new.reply_to := null; new.picked_at := null; new.notified_at := null;
    new.wake_status := null; new.error_note := null; new.answered_at := null; new.created_at := now();
    select s.display_name into v_name from kv_private.kv_staff_cur() s;
    new.sender_name := coalesce(v_name, 'Staf');
    select count(*) into v_n from public.kv_chat_messages m
      where m.user_id = new.user_id and m.role = 'staff' and m.created_at > now() - interval '1 minute';
    if v_n >= 10 then raise exception 'Terlalu banyak pesan, tunggu sebentar' using errcode = '22023'; end if;
    select count(*) into v_n from public.kv_chat_messages m
      where m.user_id = new.user_id and m.role = 'staff' and m.status = 'pending';
    if v_n >= 20 then raise exception 'Masih banyak pesan yang menunggu balasan' using errcode = '22023'; end if;
  end if;
  return new;
end $$;
create trigger kv_chat_before_insert before insert on public.kv_chat_messages
  for each row execute function kv_private.kv_chat_before_insert();

create function kv_private.kv_chat_after_insert() returns trigger
language plpgsql security definer set search_path = '' as $$
begin
  if new.role = 'staff' then
    begin
      perform net.http_post(
        url := 'https://ccbyqgisgclqlqatxwbk.supabase.co/functions/v1/kv-chat-notify',
        body := jsonb_build_object('message_id', new.id),
        headers := jsonb_build_object('Content-Type', 'application/json'),
        timeout_milliseconds := 8000);
    exception when others then
      update public.kv_chat_messages set wake_status = 'gagal_kirim' where id = new.id;
    end;
  end if;
  return null;
end $$;
create trigger kv_chat_after_insert after insert on public.kv_chat_messages
  for each row execute function kv_private.kv_chat_after_insert();

-- ---------- cek token ----------
create function kv_private.kv_chat_check_writer(p_token text) returns void
language plpgsql stable security definer set search_path = '' as $$
declare v_hash text;
begin
  select s.value into v_hash from public.kv_secrets s where s.name = 'writer_token';
  if v_hash is null or p_token is null or length(p_token) < 20
     or encode(sha256(convert_to(p_token, 'UTF8')), 'hex') <> v_hash then
    raise exception 'token tidak valid' using errcode = '28000';
  end if;
end $$;
create function kv_private.kv_chat_check_admin(p_token text) returns void
language plpgsql stable security definer set search_path = '' as $$
declare v_hash text;
begin
  select s.value into v_hash from kv_private.kv_chat_secrets s where s.name = 'admin_token';
  if v_hash is null or p_token is null or length(p_token) < 20
     or encode(sha256(convert_to(p_token, 'UTF8')), 'hex') <> v_hash then
    raise exception 'token admin tidak valid' using errcode = '28000';
  end if;
end $$;

-- ---------- RPC agent (token penulis) ----------
create or replace function kv_private.kv_chat_pending_impl(p_token text, p_agent text, p_limit int, p_history int)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v jsonb; v_name text; v_ids uuid[];
begin
  perform kv_private.kv_chat_check_writer(p_token);
  select a.display_name into v_name from public.kv_chat_agents a where a.agent = p_agent;
  if v_name is null then raise exception 'agent tidak dikenal: %', p_agent using errcode = '22023'; end if;
  select coalesce(array_agg(q.id order by q.created_at), '{}') into v_ids from (
    select m.id, m.created_at from public.kv_chat_messages m
    where m.agent = p_agent and m.role = 'staff' and m.status = 'pending'
      and exists(select 1 from public.kv_staff s join auth.users u on u.id = m.user_id   -- hanya staf yang masih aktif
                 where s.active and (s.user_id = u.id or (s.user_id is null and s.email = lower(u.email))))
    order by m.created_at limit least(greatest(coalesce(p_limit, 20), 1), 50)) q;
  update public.kv_chat_messages m set picked_at = now() where m.id = any(v_ids) and m.picked_at is null;
  select coalesce(jsonb_agg(jsonb_build_object(
      'id', m.id,
      'thread', left(m.user_id::text, 8),
      'sender', m.sender_name,
      'created_at', m.created_at,
      'content', m.content,
      'history', coalesce((select jsonb_agg(jsonb_build_object('role', h.role, 'from', h.sender_name,
                    'created_at', h.created_at, 'content', h.content) order by h.created_at)
                  from (select * from public.kv_chat_messages h0
                        where h0.user_id = m.user_id and h0.agent = m.agent and h0.created_at < m.created_at
                        order by h0.created_at desc limit least(greatest(coalesce(p_history, 8), 0), 30)) h), '[]'::jsonb)
    ) order by m.created_at), '[]'::jsonb)
  into v
  from public.kv_chat_messages m where m.id = any(v_ids);
  return jsonb_build_object('agent', p_agent, 'agent_name', v_name, 'count', jsonb_array_length(v), 'pending', v);
end $$;

create function kv_private.kv_chat_reply_impl(p_token text, p_message_id uuid, p_content text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare m public.kv_chat_messages; v_id uuid; v_n int; v_left int; v_txt text := btrim(coalesce(p_content, ''));
begin
  perform kv_private.kv_chat_check_writer(p_token);
  if length(v_txt) = 0 or length(v_txt) > 4000 then
    raise exception 'balasan harus 1..4000 karakter' using errcode = '22023';
  end if;
  select * into m from public.kv_chat_messages where id = p_message_id and role = 'staff' for update;
  if not found then raise exception 'pesan tidak ditemukan' using errcode = 'P0002'; end if;
  insert into public.kv_chat_messages(user_id, agent, role, content, status, sender_name, reply_to, answered_at)
  values (m.user_id, m.agent, 'agent', v_txt, 'answered',
          (select a.display_name from public.kv_chat_agents a where a.agent = m.agent), m.id, now())
  returning id into v_id;
  update public.kv_chat_messages x set status = 'answered', answered_at = now(), error_note = null
   where x.user_id = m.user_id and x.agent = m.agent and x.role = 'staff'
     and (x.id = m.id or (x.status = 'pending' and x.created_at <= m.created_at));
  get diagnostics v_n = row_count;
  select count(*) into v_left from public.kv_chat_messages x where x.agent = m.agent and x.role = 'staff' and x.status = 'pending';
  return jsonb_build_object('reply_id', v_id, 'answered', v_n, 'agent', m.agent, 'pending_left', v_left);
end $$;

create function kv_private.kv_chat_error_impl(p_token text, p_message_id uuid, p_note text)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_agent text; v_left int;
begin
  perform kv_private.kv_chat_check_writer(p_token);
  update public.kv_chat_messages set status = 'error', error_note = left(btrim(coalesce(p_note, '')), 200)
   where id = p_message_id and role = 'staff' returning agent into v_agent;
  if v_agent is null then raise exception 'pesan tidak ditemukan' using errcode = 'P0002'; end if;
  select count(*) into v_left from public.kv_chat_messages x where x.agent = v_agent and x.role = 'staff' and x.status = 'pending';
  return jsonb_build_object('id', p_message_id, 'status', 'error', 'agent', v_agent, 'pending_left', v_left);
end $$;

-- ---------- RPC admin (token admin) ----------
create function kv_private.kv_staff_admin_impl(p_token text, p_action text, p_email text, p_display_name text,
                                               p_allowed text[], p_is_admin boolean)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare v_email text := lower(btrim(coalesce(p_email, ''))); v_uid uuid; v_bad text; v_n int;
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
    select string_agg(x, ', ') into v_bad from unnest(coalesce(p_allowed, '{}')) x
      where not exists(select 1 from public.kv_chat_agents a where a.agent = x);
    if v_bad is not null then raise exception 'agent tidak dikenal: %', v_bad using errcode = '22023'; end if;
    select u.id into v_uid from auth.users u where lower(u.email) = v_email and u.email_confirmed_at is not null
      order by u.created_at limit 1;
    insert into public.kv_staff(email, display_name, allowed_agents, is_admin, active, user_id)
    values (v_email, coalesce(nullif(btrim(p_display_name), ''), split_part(v_email, '@', 1)),
            coalesce(p_allowed, '{content}'), coalesce(p_is_admin, false), true, v_uid)
    on conflict (email) do update set
      display_name = coalesce(nullif(btrim(p_display_name), ''), public.kv_staff.display_name),
      allowed_agents = coalesce(p_allowed, public.kv_staff.allowed_agents),
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

-- ---------- RPC halaman (staf login) ----------
create function kv_private.kv_chat_me_impl() returns jsonb
language plpgsql security definer set search_path = '' as $$
declare s public.kv_staff;
begin
  if auth.uid() is null then return jsonb_build_object('authorized', false); end if;
  select * into s from kv_private.kv_staff_cur();
  if not found then return jsonb_build_object('authorized', false); end if;
  if s.user_id is null then
    update public.kv_staff set user_id = auth.uid(), updated_at = now() where email = s.email and user_id is null;
  end if;
  return jsonb_build_object('authorized', true, 'email', s.email, 'display_name', s.display_name, 'is_admin', s.is_admin,
    'allowed_agents', coalesce((select jsonb_agg(a.agent order by a.sort) from public.kv_chat_agents a
                                 where a.enabled and (s.is_admin or a.agent = any(s.allowed_agents))), '[]'::jsonb));
end $$;

-- ---------- RPC Edge Function (service_role saja) ----------
create function kv_private.kv_chat_notify_claim_impl(p_message_id uuid) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare m public.kv_chat_messages; v_recent boolean; v_pending int;
begin
  select * into m from public.kv_chat_messages where id = p_message_id for update;
  if not found or m.role <> 'staff' or m.status <> 'pending' or m.notified_at is not null then
    return jsonb_build_object('wake', false, 'reason', 'tidak_perlu');
  end if;
  select exists(select 1 from public.kv_chat_messages x where x.agent = m.agent and x.role = 'staff'
                and x.status = 'pending' and x.id <> m.id and x.wake_status = 'dikirim'
                and x.notified_at > now() - interval '60 seconds') into v_recent;
  update public.kv_chat_messages set notified_at = now(),
         wake_status = case when v_recent then 'debounce' else 'memanggil' end where id = m.id;
  select count(*) into v_pending from public.kv_chat_messages x where x.agent = m.agent and x.role = 'staff' and x.status = 'pending';
  return jsonb_build_object('wake', not v_recent, 'reason', case when v_recent then 'debounce' else 'ok' end,
    'agent', m.agent, 'agent_name', (select a.display_name from public.kv_chat_agents a where a.agent = m.agent), 'pending', v_pending);
end $$;
create function kv_private.kv_chat_notify_done_impl(p_message_id uuid, p_status text) returns void
language sql security definer set search_path = '' as $$
  update public.kv_chat_messages set wake_status = left(regexp_replace(lower(coalesce(p_status, 'gagal')), '[^a-z0-9_]', '_', 'g'), 40)
   where id = p_message_id and wake_status = 'memanggil';
$$;

-- ---------- pembungkus publik (pola sama dengan kv_set_state) ----------
create function public.kv_chat_pending(p_token text, p_agent text, p_limit int default 20, p_history int default 8)
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_chat_pending_impl(p_token, p_agent, p_limit, p_history) $$;
create function public.kv_chat_reply(p_token text, p_message_id uuid, p_content text)
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_chat_reply_impl(p_token, p_message_id, p_content) $$;
create function public.kv_chat_error(p_token text, p_message_id uuid, p_note text default null)
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_chat_error_impl(p_token, p_message_id, p_note) $$;
create function public.kv_staff_admin(p_token text, p_action text, p_email text default null, p_display_name text default null,
                                      p_allowed text[] default null, p_is_admin boolean default null)
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_staff_admin_impl(p_token, p_action, p_email, p_display_name, p_allowed, p_is_admin) $$;
create function public.kv_chat_me()
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_chat_me_impl() $$;
create function public.kv_chat_notify_claim(p_message_id uuid)
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_chat_notify_claim_impl(p_message_id) $$;
create function public.kv_chat_notify_done(p_message_id uuid, p_status text)
returns void language sql set search_path = '' as $$ select kv_private.kv_chat_notify_done_impl(p_message_id, p_status) $$;

-- ---------- hak eksekusi (default Supabase memberi ke semua; cabut lalu beri seperlunya) ----------
do $$
declare f record;
begin
  for f in select p.oid::regprocedure as sig from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where (n.nspname = 'kv_private' and p.proname like 'kv\_chat%' or n.nspname = 'kv_private' and p.proname like 'kv\_staff%')
              or (n.nspname = 'public' and (p.proname like 'kv\_chat%' or p.proname = 'kv_staff_admin'))
  loop
    execute format('revoke all on function %s from public, anon, authenticated, service_role', f.sig);
  end loop;
end $$;
grant execute on function public.kv_chat_pending(text, text, int, int), kv_private.kv_chat_pending_impl(text, text, int, int),
  public.kv_chat_reply(text, uuid, text), kv_private.kv_chat_reply_impl(text, uuid, text),
  public.kv_chat_error(text, uuid, text), kv_private.kv_chat_error_impl(text, uuid, text),
  public.kv_staff_admin(text, text, text, text, text[], boolean), kv_private.kv_staff_admin_impl(text, text, text, text, text[], boolean)
  to anon;
grant execute on function public.kv_chat_me(), kv_private.kv_chat_me_impl(),
  kv_private.kv_staff_active(), kv_private.kv_staff_is_admin(), kv_private.kv_staff_can_chat(text)
  to authenticated;
grant execute on function public.kv_chat_notify_claim(uuid), kv_private.kv_chat_notify_claim_impl(uuid),
  public.kv_chat_notify_done(uuid, text), kv_private.kv_chat_notify_done_impl(uuid, text)
  to service_role;

-- ---------- Realtime (balasan tampil langsung; tetap tunduk RLS) ----------
alter publication supabase_realtime add table public.kv_chat_messages;
