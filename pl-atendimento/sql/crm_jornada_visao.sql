-- Visão geral da Jornada (tela inicial da aba Jornada do lead) — RPC de LEITURA, em lote.
-- Rodar (de novo) no SQL Editor do Supabase — 16/10 tarde: + produtos_pos_sc / provas_pos_sc (reação à segunda chance). Mesma proteção das outras: chave PL_IA_KEY (crm_ia_chave).
--
-- Uma linha por catálogo, com o que o servidor não consegue ler com a anon: lead dono (onboarding),
-- produtos, provas, envios automáticos (régua 30 dias e segunda chance), conta e cobrança pendente.
-- Sem telefone completo (só os 8 últimos dígitos, pra casar com o lead), sem e-mail, sem chave de loja.
-- Sem esta função a visão geral funciona igual, só sem os sinais de catálogo (📦 👓 🎁 🗓 💰 PIX).

create or replace function public.crm_jornada_visao(p_chave text)
returns jsonb
language plpgsql
stable security definer
set search_path to 'public'
as $function$
begin
  if p_chave is null or not exists (select 1 from crm_ia_chave where hash = encode(sha256(convert_to(p_chave,'UTF8')),'hex')) then
    raise exception 'acesso negado' using errcode = '42501';
  end if;
  return coalesce((
    with prod as (
      select store_id, count(*) filter (where is_active)::int n from pl_catalog_products group by store_id
    ),
    prov as (
      select catalog_store_id sid, count(*)::int n,
             count(*) filter (where created_at >= now() - interval '7 days')::int n7, max(created_at) ult
      from geracoes_provou_levou where catalog_store_id is not null group by catalog_store_id
    ),
    env as (
      select coalesce(t.store_id, s2.id) sid,
             max(t.enviado_em) filter (where t.etapa like 'segunda_chance%' and t.status = 'enviado') segunda_chance,
             count(*) filter (where t.status = 'enviado')::int enviados,
             count(*) filter (where t.status = 'erro')::int erros
      from pl_catalog_teste_envios t left join pl_catalog_stores s2 on s2.slug = t.slug
      group by 1
    )
    select jsonb_agg(jsonb_build_object(
      'store_id', s.id, 'slug', s.slug, 'nome', s.display_name, 'lead_id', o.lead_id,
      'fone8', right(regexp_replace(coalesce(s.whatsapp, ''), '\D', '', 'g'), 8),
      'criado_em', s.created_at, 'entregue_em', s.entregue_em, 'teste_30d', coalesce(s.teste_30d, false), 'ativo', s.is_active,
      'produtos', coalesce(pr.n, 0), 'provas', coalesce(pv.n, 0), 'provas_7d', coalesce(pv.n7, 0), 'ultima_prova', pv.ult,
      'segunda_chance', e.segunda_chance, 'enviados', coalesce(e.enviados, 0), 'erros', coalesce(e.erros, 0),
      -- reação à segunda chance: produtos cadastrados e provas DEPOIS da mensagem
      'produtos_pos_sc', case when e.segunda_chance is null then null else
          (select count(*)::int from pl_catalog_products p where p.store_id = s.id and p.created_at > e.segunda_chance) end,
      'provas_pos_sc', case when e.segunda_chance is null then null else
          (select count(*)::int from geracoes_provou_levou g where g.catalog_store_id = s.id and g.created_at > e.segunda_chance) end,
      'proximo', (select jsonb_build_object('dia', t.dia, 'etapa', t.etapa, 'agendado_para', t.agendado_para)
                  from pl_catalog_teste_envios t where (t.store_id = s.id or t.slug = s.slug) and t.status = 'agendado'
                  order by t.agendado_para, t.dia limit 1),
      'conta_status', st.status, 'plano', coalesce(st.plano_personalizado, st.plan),
      'cobranca_pendente', (select jsonb_build_object('valor', x.valor, 'criado_em', x.created_at, 'tipo', x.raw_payload->>'tipo')
                            from provou_levou_pix_extras x
                            where x.status = 'pending' and x.created_at > now() - interval '15 days'
                              and ((st.id is not null and x.raw_payload->>'store_id' = st.id::text) or x.loja = s.slug)
                            order by x.created_at desc limit 1)
    ))
    from pl_catalog_stores s
    left join prod pr on pr.store_id = s.id
    left join prov pv on pv.sid = s.id
    left join env e on e.sid = s.id
    left join lateral (select lead_id from pl_catalog_onboarding o where o.slug = s.slug
                       order by o.criado_em desc nulls last limit 1) o on true
    left join lateral (select id, status, plan, plano_personalizado from provou_levou_stores x
                       where x.domain ilike '%/catalogo/' || s.slug order by x.created_at desc limit 1) st on true
  ), '[]'::jsonb);
end;
$function$;

revoke all on function public.crm_jornada_visao(text) from public;
grant execute on function public.crm_jornada_visao(text) to anon, authenticated;
notify pgrst, 'reload schema';
