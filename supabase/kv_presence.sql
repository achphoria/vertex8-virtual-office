-- Kantor Virtual Vertex8 v5 — kehadiran (presence) avatar staf di halaman publik.
-- Hanya objek BARU (kv_ / kv_private). Tabel publik TIDAK menyimpan user_id/email:
-- hanya pid acak, nama tampilan staf, dan keadaan ringan ("hadir" / "ngobrol" dengan agent X).
-- Isi chat tidak pernah masuk ke sini.

create table kv_private.kv_presence_owner(
  user_id uuid primary key references auth.users(id) on delete cascade,
  pid text not null unique default substr(md5(gen_random_uuid()::text), 1, 12)
);
alter table kv_private.kv_presence_owner enable row level security;
revoke all on kv_private.kv_presence_owner from public, anon, authenticated, service_role;
create policy kv_presence_owner_deny_all on kv_private.kv_presence_owner for all to anon, authenticated using (false) with check (false);

create table public.kv_presence(
  pid text primary key references kv_private.kv_presence_owner(pid) on delete cascade,
  display_name text not null check (length(display_name) between 1 and 60),
  state text not null default 'hadir' check (state in ('hadir', 'ngobrol')),
  agent text check (agent is null or agent ~ '^[a-z0-9_-]{1,32}$'),
  waiting boolean not null default false,
  talk_at timestamptz,
  reply_at timestamptz,
  updated_at timestamptz not null default now()
);
alter table public.kv_presence enable row level security;
revoke all on public.kv_presence from anon, authenticated;
grant select on public.kv_presence to anon, authenticated;
-- publik hanya melihat baris yang masih segar (avatar staf yang sedang online)
create policy kv_presence_read on public.kv_presence for select to anon, authenticated
  using (updated_at > now() - interval '10 minutes');

-- tulis hanya lewat fungsi: staf aktif (allowlist kv_staff) untuk barisnya sendiri; nama diambil dari kv_staff
create function kv_private.kv_presence_set_impl(p_state text, p_agent text, p_event text) returns jsonb
language plpgsql security definer set search_path = '' as $$
declare v_uid uuid := auth.uid(); v_name text; v_pid text; v_state text; v_agent text; v_ev text;
begin
  if v_uid is null then raise exception 'belum masuk' using errcode = '42501'; end if;
  select s.display_name into v_name from kv_private.kv_staff_cur() s;
  if v_name is null then raise exception 'bukan staf aktif' using errcode = '42501'; end if;
  v_state := case when p_state = 'ngobrol' then 'ngobrol' else 'hadir' end;
  v_agent := case when v_state = 'ngobrol' and p_agent ~ '^[a-z0-9_-]{1,32}$' then p_agent end;
  if v_agent is null then v_state := 'hadir'; end if;
  v_ev := case when p_event in ('talk', 'wait', 'reply', 'idle') then p_event end;
  insert into kv_private.kv_presence_owner(user_id) values (v_uid) on conflict (user_id) do nothing;
  select o.pid into v_pid from kv_private.kv_presence_owner o where o.user_id = v_uid;
  delete from public.kv_presence where updated_at < now() - interval '1 day';
  insert into public.kv_presence as p (pid, display_name, state, agent, waiting, talk_at, reply_at, updated_at)
  values (v_pid, v_name, v_state, v_agent, coalesce(v_ev = 'wait', false) and v_state = 'ngobrol',
          case when v_ev in ('talk', 'wait') then now() end, case when v_ev = 'reply' then now() end, now())
  on conflict (pid) do update set
    display_name = excluded.display_name, state = excluded.state, agent = excluded.agent,
    waiting = case when excluded.state <> 'ngobrol' or v_ev in ('reply', 'idle') then false
                   when v_ev = 'wait' then true else p.waiting end,
    talk_at = case when v_ev in ('talk', 'wait') then now() else p.talk_at end,
    reply_at = case when v_ev = 'reply' then now() else p.reply_at end,
    updated_at = now();
  return jsonb_build_object('pid', v_pid);
end $$;

create function kv_private.kv_presence_leave_impl() returns void
language sql security definer set search_path = '' as $$
  delete from public.kv_presence p using kv_private.kv_presence_owner o where o.pid = p.pid and o.user_id = auth.uid();
$$;

create function public.kv_presence_set(p_state text, p_agent text default null, p_event text default null)
returns jsonb language sql set search_path = '' as $$ select kv_private.kv_presence_set_impl(p_state, p_agent, p_event) $$;
create function public.kv_presence_leave()
returns void language sql set search_path = '' as $$ select kv_private.kv_presence_leave_impl() $$;

revoke all on function kv_private.kv_presence_set_impl(text, text, text), kv_private.kv_presence_leave_impl(),
  public.kv_presence_set(text, text, text), public.kv_presence_leave() from public, anon, authenticated, service_role;
grant execute on function kv_private.kv_presence_set_impl(text, text, text), kv_private.kv_presence_leave_impl(),
  public.kv_presence_set(text, text, text), public.kv_presence_leave() to authenticated;

alter publication supabase_realtime add table public.kv_presence;
