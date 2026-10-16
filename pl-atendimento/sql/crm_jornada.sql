-- Jornada do lead (CRM de prospecção) — RPCs de LEITURA para o servidor do painel.
-- NÃO aplicado. Rodar no SQL Editor do Supabase (self-hosted) quando for publicar.
--
-- Por quê: o servidor do CRM só tem a chave anon. pl_catalog_onboarding, pl_catalog_teste_envios
-- (RLS sem policy), geracoes_provou_levou, provou_levou_stores e pagamentos_clientes (RLS por
-- lojista) não são legíveis com ela. Estas funções devolvem só o necessário pra linha do tempo,
-- protegidas pela MESMA chave do Assistente IA (PL_IA_KEY, hash em crm_ia_chave), igual a
-- crm_ia_contexto / crm_funil_automatico. Nada de telefone, e-mail, chave de loja ou QR code.
-- Sem a função no ar, o painel continua funcionando com o que a anon já lê (degrada sozinho).

create or replace function public.crm_jornada_loja(p_chave text, p_lead_id uuid default null, p_slug text default null)
returns jsonb
language plpgsql
stable security definer
set search_path to 'public'
as $function$
declare
  v_slug text;
  v_store uuid;
  v_pls uuid;
  r jsonb;
begin
  if p_chave is null or not exists (select 1 from crm_ia_chave where hash = encode(sha256(convert_to(p_chave,'UTF8')),'hex')) then
    raise exception 'acesso negado' using errcode = '42501';
  end if;

  -- lead -> loja: pl_catalog_onboarding (lead_id, slug, store_id); senão o slug que o painel achou
  if p_lead_id is not null then
    select o.slug into v_slug from pl_catalog_onboarding o where o.lead_id = p_lead_id order by o.criado_em desc nulls last limit 1;
  end if;
  v_slug := coalesce(v_slug, nullif(trim(p_slug), ''));
  if v_slug is null then
    return '{}'::jsonb;
  end if;
  select s.id into v_store from pl_catalog_stores s where s.slug = v_slug;
  if v_store is null then
    return '{}'::jsonb;
  end if;
  select x.id into v_pls from provou_levou_stores x where x.domain ilike '%/catalogo/' || v_slug order by x.created_at desc limit 1;

  select jsonb_build_object(
    'store', (select jsonb_build_object('id', s.id, 'slug', s.slug, 'nome', s.display_name, 'criado_em', s.created_at,
                     'entregue_em', s.entregue_em, 'teste_30d', coalesce(s.teste_30d, false), 'ativo', s.is_active, 'plano', s.plan)
              from pl_catalog_stores s where s.id = v_store),
    'onboarding', (select jsonb_build_object('lead_id', o.lead_id, 'criado_em', o.criado_em, 'criado_por', o.criado_por,
                          'responsavel', o.responsavel, 'grupo_nome', o.grupo_nome, 'tem_grupo', o.grupo_jid is not null,
                          'observacao', left(o.observacao, 300))
                   from pl_catalog_onboarding o where o.slug = v_slug order by o.criado_em desc nulls last limit 1),
    'produtos_por_dia', coalesce((select jsonb_agg(jsonb_build_object('dia', d, 'n', n) order by d)
        from (select (created_at at time zone 'America/Sao_Paulo')::date d, count(*)::int n
              from pl_catalog_products where store_id = v_store group by 1) x), '[]'::jsonb),
    'provas_por_dia', coalesce((select jsonb_agg(jsonb_build_object('dia', d, 'n', n) order by d)
        from (select (created_at at time zone 'America/Sao_Paulo')::date d, count(*)::int n
              from geracoes_provou_levou where catalog_store_id = v_store group by 1) x), '[]'::jsonb),
    'conta', (select jsonb_build_object('status', x.status, 'plano', coalesce(x.plano_personalizado, x.plan),
                     'ultimo_pagamento', x.last_payment, 'forma_pagamento', x.forma_pagamento)
              from provou_levou_stores x where x.id = v_pls),
    'pagamentos', coalesce((select jsonb_agg(jsonb_build_object('data', p.data_pagamento, 'tipo', p.tipo, 'valor', p.valor,
                          'descricao', left(p.descricao, 120), 'criado_em', p.created_at) order by p.data_pagamento, p.created_at)
        from pagamentos_clientes p where v_pls is not null and p.store_id = v_pls), '[]'::jsonb),
    'cobrancas', coalesce((select jsonb_agg(jsonb_build_object('criado_em', e.created_at, 'aprovado_em', e.approved_at,
                          'status', e.status, 'valor', e.valor, 'tipo', e.raw_payload->>'tipo',
                          'plano', e.raw_payload->>'plano', 'fotos', e.raw_payload->>'fotos') order by e.created_at)
        from (select * from provou_levou_pix_extras e
              where (v_pls is not null and e.raw_payload->>'store_id' = v_pls::text) or e.loja = v_slug
              order by e.created_at desc limit 60) e), '[]'::jsonb),
    'envios', coalesce((select jsonb_agg(jsonb_build_object('dia', t.dia, 'etapa', t.etapa, 'agendado_para', t.agendado_para,
                          'enviado_em', t.enviado_em, 'status', t.status, 'texto', left(t.texto, 1500),
                          'erro', left(t.erro, 300), 'criado_em', t.criado_em) order by t.dia, t.id)
        from pl_catalog_teste_envios t where t.store_id = v_store or t.slug = v_slug), '[]'::jsonb)
  ) into r;
  return r;
end;
$function$;

-- Visão geral: catálogos na régua de 30 dias, dia atual e próxima mensagem agendada.
create or replace function public.crm_jornada_catalogos_30d(p_chave text)
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
    select jsonb_agg(jsonb_build_object(
      'store_id', s.id, 'slug', s.slug, 'nome', s.display_name, 'criado_em', s.created_at, 'entregue_em', s.entregue_em,
      'dia_atual', case when s.entregue_em is null then null
                        else (current_date - (s.entregue_em at time zone 'America/Sao_Paulo')::date) + 1 end,
      'lead_id', o.lead_id, 'responsavel', o.responsavel,
      'produtos', (select count(*)::int from pl_catalog_products p where p.store_id = s.id),
      'provas', (select count(*)::int from geracoes_provou_levou g where g.catalog_store_id = s.id),
      'enviados', (select count(*)::int from pl_catalog_teste_envios t where (t.store_id = s.id or t.slug = s.slug) and t.status = 'enviado'),
      'erros', (select count(*)::int from pl_catalog_teste_envios t where (t.store_id = s.id or t.slug = s.slug) and t.status = 'erro'),
      'proximo', (select jsonb_build_object('dia', t.dia, 'etapa', t.etapa, 'agendado_para', t.agendado_para)
                  from pl_catalog_teste_envios t where (t.store_id = s.id or t.slug = s.slug) and t.status = 'agendado'
                  order by t.agendado_para, t.dia limit 1)
    ) order by s.entregue_em desc nulls first, s.created_at desc)
    from pl_catalog_stores s
    left join lateral (select lead_id, responsavel from pl_catalog_onboarding o where o.slug = s.slug
                       order by o.criado_em desc nulls last limit 1) o on true
    where coalesce(s.teste_30d, false)), '[]'::jsonb);
end;
$function$;

revoke all on function public.crm_jornada_loja(text, uuid, text) from public;
revoke all on function public.crm_jornada_catalogos_30d(text) from public;
grant execute on function public.crm_jornada_loja(text, uuid, text) to anon, authenticated;
grant execute on function public.crm_jornada_catalogos_30d(text) to anon, authenticated;
notify pgrst, 'reload schema';
