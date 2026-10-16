-- Espelho das sugestões de RESPOSTA do Jev (aba Jornada → Responder) — pra medir o Jev fora do container.
-- NÃO aplicado. Opcional: sem isto o log fica só no painel.db (tabela resposta_sugestao) e o espelho ignora.
-- Mesma proteção do pl_atend_espelha: chave PL_IA_KEY (crm_ia_chave). Tabela só legível com service_role.

create table if not exists public.pl_atend_respostas (
  id bigint primary key,              -- id local (painel.db resposta_sugestao.id)
  chatid text not null,
  ultima_msg text,
  usuario text,
  sugestao text not null,
  porque text,
  modelo text,
  alerta text,
  criado_ts bigint not null,
  resultado text,                      -- null (aberta) | enviada (como estava) | editada | descartada
  texto_enviado text,
  decidido_ts bigint,
  espelhado_em timestamptz default now()
);
alter table public.pl_atend_respostas enable row level security;
revoke all on public.pl_atend_respostas from anon, authenticated;

create or replace function public.pl_atend_espelha_respostas(p_chave text, p_itens jsonb default '[]'::jsonb)
returns int
language plpgsql
security definer
set search_path to 'public'
as $function$
declare n int;
begin
  if p_chave is null or not exists (select 1 from crm_ia_chave where hash = encode(sha256(convert_to(p_chave,'UTF8')),'hex')) then
    raise exception 'acesso negado' using errcode = '42501';
  end if;
  insert into pl_atend_respostas(id, chatid, ultima_msg, usuario, sugestao, porque, modelo, alerta, criado_ts, resultado, texto_enviado, decidido_ts)
  select (x->>'id')::bigint, x->>'chatid', x->>'ultima_msg', x->>'usuario', x->>'sugestao', x->>'porque', x->>'modelo', x->>'alerta',
         (x->>'criado_ts')::bigint, x->>'resultado', x->>'texto_enviado', nullif(x->>'decidido_ts','')::bigint
  from jsonb_array_elements(coalesce(p_itens, '[]')) x where x->>'id' is not null
  on conflict (id) do update set resultado = excluded.resultado, texto_enviado = excluded.texto_enviado,
    decidido_ts = excluded.decidido_ts, espelhado_em = now();
  get diagnostics n = row_count;
  return n;
end;
$function$;

revoke all on function public.pl_atend_espelha_respostas(text, jsonb) from public;
grant execute on function public.pl_atend_espelha_respostas(text, jsonb) to anon, authenticated;
notify pgrst, 'reload schema';
