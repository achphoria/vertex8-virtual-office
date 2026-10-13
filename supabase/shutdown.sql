-- Vertex8 virtual office shutdown (2026-10-13). Reversible: no data dropped.
update public.kv_chat_agents set enabled = false;
do $$
declare r record;
begin
  for r in select c.relname from pg_class c join pg_namespace n on n.oid=c.relnamespace
           where n.nspname='public' and c.relkind in ('r','v','p') and c.relname like 'kv\_%' loop
    execute format('revoke all on public.%I from anon, authenticated', r.relname);
  end loop;
  for r in select p.oid::regprocedure::text sig from pg_proc p join pg_namespace n on n.oid=p.pronamespace
           where n.nspname='public' and p.proname like 'kv\_%' loop
    execute format('revoke execute on function %s from public, anon, authenticated', r.sig);
  end loop;
end $$;

-- ===== REVERSE (restore grants as they were before shutdown) =====
-- update public.kv_chat_agents set enabled = (agent <> 'grok');
-- grant select on public.kv_activity_log, public.kv_chat_agents, public.kv_office_state, public.kv_presence to anon, authenticated;
-- grant select on public.kv_chat_messages to authenticated;
-- grant execute on function public.kv_chat_error(text,uuid,text), public.kv_chat_reply(text,uuid,text), public.kv_set_state(text,jsonb) to anon;
-- grant execute on function public.kv_chat_pending, public.kv_staff_admin to anon;   -- (use full signatures, see \df)
-- grant execute on function public.kv_chat_me(), public.kv_presence_leave(), public.kv_presence_set(text,text,text) to authenticated;
-- Then: redeploy edge functions from /workspace/virtual-office/archive/, and re-enable Pages (gh api -X POST repos/achphoria/vertex8-virtual-office/pages -f source[branch]=main -f source[path]=/).
