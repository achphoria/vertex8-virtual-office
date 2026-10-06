-- Kantor Virtual Vertex8 v6 — riwayat kerja per agent (append-only).
-- Diisi OTOMATIS oleh trigger pada kv_office_state (jalur kv_set_state yang dijaga token penulis):
-- setiap entri log baru (status/tugas) dan setiap langkah (--step) baru dicatat. Tidak ada insert dari web.
-- Publik hanya bisa membaca 30 hari terakhir. Isinya = teks status yang memang sudah publik (sudah disaring
-- update-status.py: tanpa Rp / jumlah member / nomor telepon).

create table public.kv_activity_log(
  id bigint generated always as identity primary key,
  agent text check (agent is null or agent ~ '^[a-z0-9][a-z0-9_-]{0,31}$'),
  agent_name text not null check (length(agent_name) between 1 and 60),
  state text not null check (length(state) between 1 and 30),
  task text not null check (length(task) between 1 and 400),
  step text check (step is null or length(step) <= 200),
  created_at timestamptz not null default now()
);
create unique index kv_activity_log_dedup_idx on public.kv_activity_log(agent_name, state, md5(task), coalesce(step, ''), created_at);
create index kv_activity_log_agent_idx on public.kv_activity_log(agent, created_at desc);
create index kv_activity_log_time_idx on public.kv_activity_log(created_at desc);
alter table public.kv_activity_log enable row level security;
revoke all on public.kv_activity_log from anon, authenticated;
grant select on public.kv_activity_log to anon, authenticated;
create policy kv_activity_log_read_30d on public.kv_activity_log for select to anon, authenticated
  using (created_at > now() - interval '30 days');

-- trigger: catat entri log baru + langkah baru. Tidak pernah menggagalkan penulisan status.
create function kv_private.kv_activity_capture() returns trigger
language plpgsql security definer set search_path = '' as $$
declare e jsonb; a jsonb; w jsonb; ow jsonb; v_old jsonb; v_agents jsonb; v_t timestamptz; v_id text;
begin
  begin
    v_agents := case when jsonb_typeof(new.data->'agents') = 'array' then new.data->'agents' else '[]'::jsonb end;
    v_old := case when tg_op = 'UPDATE' and jsonb_typeof(old.data->'log') = 'array' then old.data->'log' else '[]'::jsonb end;
    if jsonb_typeof(new.data->'log') = 'array' then
      for e in select x from jsonb_array_elements(new.data->'log') x loop
        continue when jsonb_typeof(e) <> 'object' or coalesce(e->>'text', '') = '' or coalesce(e->>'agent', '') = '';
        continue when v_old @> jsonb_build_array(e);
        begin v_t := (e->>'t')::timestamptz; exception when others then v_t := null; end;
        v_t := coalesce(v_t, now());
        v_id := null;
        select x->>'id' into v_id from jsonb_array_elements(v_agents) x
          where x->>'name' = e->>'agent' or x->>'id' = e->>'agent' limit 1;
        insert into public.kv_activity_log(agent, agent_name, state, task, created_at)
        values (case when v_id ~ '^[a-z0-9][a-z0-9_-]{0,31}$' then v_id end, left(e->>'agent', 60),
                left(coalesce(nullif(e->>'status', ''), 'Info'), 30), left(e->>'text', 400), v_t)
        on conflict do nothing;
      end loop;
    end if;
    -- langkah kecil (--step) pada tugas "Sedang kerja"
    for a in select x from jsonb_array_elements(v_agents) x loop
      continue when jsonb_typeof(a) <> 'object' or jsonb_typeof(a->'tasks') is distinct from 'array' or coalesce(a->>'name', '') = '';
      w := null; ow := null;
      select t into w from jsonb_array_elements(a->'tasks') t
        where jsonb_typeof(t) = 'object' and lower(coalesce(t->>'status', '')) like 'sedang%' limit 1;
      continue when w is null or coalesce(w->>'step', '') = '';
      if tg_op = 'UPDATE' and jsonb_typeof(old.data->'agents') = 'array' then
        select t into ow from jsonb_array_elements(old.data->'agents') oa, jsonb_array_elements(
                 case when jsonb_typeof(oa->'tasks') = 'array' then oa->'tasks' else '[]'::jsonb end) t
          where (oa->>'id' = a->>'id' or oa->>'name' = a->>'name')
            and jsonb_typeof(t) = 'object' and lower(coalesce(t->>'status', '')) like 'sedang%' limit 1;
      end if;
      continue when ow is not null and coalesce(ow->>'step', '') = w->>'step'
                    and coalesce(ow->>'step_at', '') = coalesce(w->>'step_at', '');
      begin v_t := (w->>'step_at')::timestamptz; exception when others then v_t := null; end;
      insert into public.kv_activity_log(agent, agent_name, state, task, step, created_at)
      values (case when a->>'id' ~ '^[a-z0-9][a-z0-9_-]{0,31}$' then a->>'id' end, left(a->>'name', 60), 'Langkah',
              left(coalesce(nullif(w->>'text', ''), '-'), 400), left(w->>'step', 200), coalesce(v_t, now()))
      on conflict do nothing;
    end loop;
    if random() < 0.02 then
      delete from public.kv_activity_log where created_at < now() - interval '90 days';
    end if;
  exception when others then
    raise warning 'kv_activity_capture: %', sqlerrm;
  end;
  return null;
end $$;
revoke all on function kv_private.kv_activity_capture() from public, anon, authenticated, service_role;
create trigger kv_activity_capture after insert or update of data on public.kv_office_state
  for each row execute function kv_private.kv_activity_capture();

-- isi awal dari log yang sekarang ada di kv_office_state
insert into public.kv_activity_log(agent, agent_name, state, task, created_at)
select (select x->>'id' from jsonb_array_elements(s.data->'agents') x
         where x->>'name' = e->>'agent' or x->>'id' = e->>'agent' limit 1),
       left(e->>'agent', 60), left(coalesce(nullif(e->>'status', ''), 'Info'), 30), left(e->>'text', 400), (e->>'t')::timestamptz
from public.kv_office_state s, jsonb_array_elements(s.data->'log') e
where s.id = 1 and coalesce(e->>'text', '') <> '' and coalesce(e->>'agent', '') <> '' and coalesce(e->>'t', '') <> ''
on conflict do nothing;
