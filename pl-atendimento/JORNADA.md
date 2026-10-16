# Jornada do lead (CRM de prospecção)

Aba **Jornada do lead** no CRM (`/crm/jornada`). A Dione busca um lead por nome ou telefone e vê cada passo
dele, dia a dia: o que nós fizemos e o que ele fez com a gente. Segue o modelo da "Jornada do comprador"
da dashboard do lojista. Ainda **não publicado**: só commit local.

## O que foi feito

- **Backend:** módulo novo `jornada.py`, exposto em dois endpoints:
  - `GET /api/lead/jornada?chatid=…&crm_id=…` devolve o lead, o resumo, a régua de 30 dias e os eventos.
    Aceita também o chatid do grupo do catálogo.
  - `GET /api/jornada/catalogos30` devolve a visão geral dos catálogos em `teste_30d`.
- **Histórico de etapas:** tabela local nova `etapa_historico` no `painel.db`, com os campos `de`, `para`, `ts`,
  `origem` e `por`. Ela é preenchida em todo lugar onde a etapa muda:
  - `manual`: botão ou arrasto no Atendimento/Pipeline, ou plano fechado. Grava quem fez (Lucas ou Dione).
  - `jev`: o Jev moveu sozinho.
  - `jev_sugestao`: alguém aplicou a sugestão do Jev.
  - `crm`: mudou fora do painel (rotina do funil, agente de catálogos ou o próprio CRM). Vem de
    `pull_statuses` e `reflect_local`.
- **Proxy:** `server.js` (regex `PROSPECCAO_API`) agora deixa passar `lead/jornada` e `jornada/catalogos30`.
- **Front:**
  - Página nova `crm-app/src/pages/Jornada.tsx`, com item "Jornada do lead" no menu e rota `/jornada`.
  - **Busca:** junta `/api/fila?busca=` (painel, inclui grupos) com `leads` do Supabase, por nome ou telefone.
  - **Cabeçalho de resumo:**
    - etapa atual e há quantos dias está nela;
    - quantos dias está no funil e o responsável;
    - mensagens nossas e dele, e o nosso tempo de resposta (mediana e média);
    - número de provas e a última interação;
    - status da conta.
  - **Régua de 30 dias:** aparece quando o catálogo tem `teste_30d`. Mostra a barra com a montagem (dias 1–21),
    o teste grátis (dias 22–28) e o dia de hoje. Lista as mensagens dos dias 7, 14, 21, 22 e 28, com data
    (`agendado_para` ou prevista), status e o texto enviado.
  - **Próximos marcos:** envios agendados, retomar Stand-by, fim do teste de 7 dias e tarefas com prazo.
  - **Linha do tempo:** vertical e agrupada por dia, com ícone e cor por categoria e filtros por categoria.
    As mensagens ficam recolhidas por dia ("12 mensagens — expandir"). Tem links para a conversa
    (`/atendimento?chatid=`), o grupo e o lead no CRM.
  - Sem lead escolhido, a página mostra a lista de catálogos na régua de 30 dias: dia atual, próxima mensagem,
    envios e falhas, produtos e provas.
- **Atalhos para a Jornada:**
  - botão "🧭 Jornada do lead" no card do Pipeline;
  - botão "Jornada" no `LeadDetalhe`.
  - O `LeadDetalhe` existia mas estava sem rota. Ganhou `/leads/:id`, que é para onde aponta o link
    "Lead no CRM".
- **Testes:** `test_jornada.py` (8 testes, `painel.db` temporário e CRM simulado). `test_planos_fechados` foi
  ajustado à nova assinatura de `change(..., origem, por)`.

## De onde vem cada evento

| Categoria | Evento | Fonte |
|---|---|---|
| Mensagens | todas as mensagens nossas e do lead, no privado e no grupo (áudio, imagem etc. viram rótulo; reação é ignorada) | `painel.db.mensagens` |
| Mensagens | DM / follow-up / resposta do Instagram | `interacoes` (dm_enviada, follow_up, resposta) |
| Etapas | mudança manual, do Jev ou vinda do CRM | `etapa_historico` (local, novo) |
| Etapas | "movido para Teste parado (motivo)", "retomar contato" | linhas datadas de `leads.notas` (rotina do funil) |
| Etapas | Jev sugeriu, aplicada ou ignorada, Jev moveu | `etapa_sugestao` (só a última avaliação por conversa) |
| Catálogo | catálogo criado (e por quem), entregue | `pl_catalog_stores` + `pl_catalog_onboarding` |
| Catálogo | acesso enviado, grupo aberto, cobrança de cadastro | regex nas nossas mensagens (mesmas do `historico_lead`) |
| Catálogo | produtos cadastrados por dia, provas por dia | `pl_catalog_products`, `geracoes_provou_levou.catalog_store_id` |
| Catálogo | envios automáticos da régua de 30 dias (quem = sistema; texto e status) | `pl_catalog_teste_envios` |
| Financeiro | proposta, link de pagamento, cobrança de fim de teste | regex nas nossas mensagens |
| Financeiro | PIX/boleto gerado, pagamento aprovado | `provou_levou_pix_extras` (`raw_payload.store_id` ou `loja`) |
| Financeiro | pagamento recebido, status e plano da conta | `pagamentos_clientes`, `provou_levou_stores` (domínio `/catalogo/<slug>`) |
| Financeiro | plano fechado | `painel.db.planos_fechados` |
| Tarefas/notas | observações do CRM; anotações datadas do lead; tarefas do próprio login que citam o nome da loja | `interacoes`, `leads.notas`, `painel.db.tarefas` |
| Responsável | atribuído a X; X fez o 1º envio | `conversas_atribuidas`, `atendimentos_iniciados` |
| Lead | entrou no CRM (origem), primeiro contato, cadastro unificado | `leads`, `mensagens`, `leads.notas` |

**Ligação lead → loja:**
1. `pl_catalog_onboarding.lead_id`, pela RPC;
2. o slug que o agente anota em `leads.notas` (`?loja=<slug>`);
3. e-mail, telefone ou nome (o mesmo critério do `historico_lead`).

## Visibilidade

A visibilidade é a mesma de hoje. O usuário vem do header `X-Prospeccao-User`, que o proxy grava a partir da sessão.

- **Conversa privada:** todo login vê, igual ao Atendimento.
- **Grupo do catálogo:** só entra se `grupos_catalogos.visible` permitir. A Dione vê só os grupos dela.
- **Tarefas:** só as do próprio login.
- **Cobranças e pagamentos** (vindos da RPC): o Lucas vê sempre. A Dione vê só nos leads em que ela é a
  responsável; nos outros aparece um aviso.

## RPC no Supabase (SQL em `sql/crm_jornada.sql`, NÃO aplicado)

Com a chave anon, o servidor não lê estas tabelas:
- `pl_catalog_onboarding` e `pl_catalog_teste_envios` (RLS sem policy);
- `geracoes_provou_levou`, `provou_levou_stores` e `pagamentos_clientes`.

Por isso há duas funções `security definer` de leitura, protegidas pela mesma chave do Assistente IA
(`PL_IA_KEY`, hash em `crm_ia_chave`):
- `crm_jornada_loja(p_chave, p_lead_id, p_slug)`: onboarding, produtos e provas por dia, conta, pagamentos,
  cobranças e envios da régua. Sem telefone, e-mail, chave de loja ou QR code.
- `crm_jornada_catalogos_30d(p_chave)`: visão geral.

As consultas internas foram conferidas como SELECT puro no banco real.

**Sem a RPC, a página continua funcionando.** Ela mostra catálogo e produtos (que a anon lê) e conta as provas
pelos avisos "Novo cliente provou" do grupo. Também aparece um aviso amarelo. A régua aparece com datas
previstas, mas sem status de envio.

## Desempenho

O lead e os catálogos (estes em cache de 60 s) são lidos em paralelo; depois, as interações e a RPC, também
em paralelo. O SQLite é lido na thread da requisição.

| Cenário | Tempo |
|---|---|
| Lead real (69 mensagens), CRM de produção, sem a RPC | ~200–280 ms |
| Teste com 4.000 mensagens | < 1,5 s (teste automatizado) |

## Limitações

- **Mudanças de etapa antigas:** o histórico de etapas só começa no deploy (`etapa_historico` é novo). Antes
  disso, só existem os movimentos automáticos anotados em `leads.notas` (com data, sem hora) e a última
  decisão do Jev. "Há quanto tempo está na etapa" fica "sem registro" quando não há movimento conhecido.
- **Jev:** `etapa_sugestao` guarda só a última avaliação por conversa. Os movimentos do Jev passam a ser
  históricos pelo `etapa_historico`.
- **Mudanças feitas direto no CRM** (arrastar card de lead sem conversa): entram como origem `crm` quando o
  painel percebe (a cada ~60 s), sem o nome de quem fez.
- **Eventos só com data** (notas, produtos e provas por dia, pagamentos) aparecem como "dia todo".
- **Mensagens antigas:** só entram as mensagens que estão no `painel.db` (a captura começou com janela de 14 dias).
- **Tempo de resposta:** só na conversa privada, de uma mensagem do lead (ou sequência delas) até a nossa
  próxima. Mostra a mediana porque noites e fins de semana puxam a média.
- **Régua de 30 dias:** hoje nenhum catálogo tem `teste_30d` nem `entregue_em`, e `pl_catalog_teste_envios`
  está vazia. A régua e a visão geral só vão ter conteúdo quando a rotina começar a rodar.
- **Tarefas:** não têm vínculo com o lead. A ligação é pelo nome da loja no título ou nas anotações.

## Deploy (quando for publicar)

1. Aplicar `pl-atendimento/sql/crm_jornada.sql` no SQL Editor do Supabase. É opcional, mas sem ele não há
   provas por dia exatas, pagamentos nem envios da régua.
2. Confirmar que o serviço tem `PL_IA_KEY` (já usada pelo Assistente e pelo espelho).
3. Commit e push no `main` do repositório `quantic-dash`. Antes, baixar o `main` atual e aplicar o diff por
   cima: não sobrescrever.
4. Fazer o redeploy do serviço `quantic-crm` no EasyPanel. O Dockerfile já roda `npm run build` do `crm-app`;
   o `dist` não foi commitado.
5. Conferir:
   - `/crm/jornada` abre com a lista de catálogos;
   - buscar um lead mostra a jornada;
   - mover uma etapa no Atendimento faz aparecer "X → Y · Dione" na linha do tempo.
6. Testes: `cd pl-atendimento && python3 -m unittest test_jornada test_crm_bridge test_planos_fechados`.
   `test_grupos_catalogos`, `test_live_events` e `test_responsavel` já falhavam antes.

## Visão geral (tela inicial, 16/10/2026)

**Por que a página aparecia "sem dados".** Os endpoints e as RPCs estavam funcionando:
- os nomes de env batem (`PL_CRM_URL`, `PL_CRM_KEY`, `PL_IA_KEY`);
- `crm_jornada_loja` e `crm_jornada_catalogos_30d` respondem com a chave do serviço;
- a jornada de 240 leads reais, montada numa cópia do painel.db feita a partir do espelho, saiu sem erro (p50 0,2 s).

O problema era a tela inicial. Ela só listava catálogos com `teste_30d`, que eram zero. O resultado era um card
vazio até a pessoa buscar um lead.

**Agora a tela inicial é a visão geral** (`GET /api/jornada/visao`, `visao_geral.py`, `JornadaVisao.tsx`):
- **Cards de destaque:**
  - esperando resposta (cliente falou por último, igual à bolinha do Atendimento);
  - para fazer hoje;
  - parados 3+, 7+ e 15+ dias sem interação;
  - segunda chance.
- **Funil:** leads por etapa (as 11 etapas). Cada card é clicável e vira filtro.
- **Lista "o que fazer hoje":** ordenada por prioridade, com o motivo de cada lead. Cada linha mostra etapa, dias
  na etapa, última interação (quem, quando e trecho), responsável e sinais:
  - 🟢 esperando resposta
  - ⏰ parado X dias
  - 📦 produtos
  - 👓 provas
  - 🎁 segunda chance
  - 💰 proposta ou PIX pendente
  - 🗓 teste 30d dia N
  - 📅 retomar
  - ✨ sugestão do Jev
  - ✅ plano
- **Filtros:** etapa, responsável, só esperando, só parados, só catálogos e segunda chance. Ordenação por
  prioridade, tempo parado, tempo na etapa ou interação recente. O clique abre a jornada do lead.
- **Prioridade**, da mais alta para a mais baixa:
  1. cliente esperando há até 7 dias (o mais recente primeiro);
  2. Stand-by com retomar vencido;
  3. cobrança gerada e não paga;
  4. proposta ou aguardando pagamento parado há 2+ dias;
  5. teste parado;
  6. catálogo no ar sem produto;
  7. follow-up (3 a 7 dias sem interação);
  8. segunda chance sem resposta;
  9. esperando há mais de 7 dias, ou parado há mais de 7 dias (esfriando);
  10. Novo parado.

  "Para fazer hoje" conta os itens com prioridade ≥ 450: os grupos 1 a 8 e, no grupo 1, só quem espera
  até 7 dias.
- **Quem entra na lista:**
  - todas as conversas do painel (sem grupos, ocultas e suporte de cliente final);
  - os leads só do CRM a partir de Interessado (catálogo sem conversa, por exemplo).
- **Contagem de "parados":** conta do Em conversa em diante, sem Convertido e Perdido. Novo que nunca respondeu é
  lista fria.
- **Visibilidade:** o Lucas vê todos; a Dione vê os dela e os sem responsável. Outro login recebe 403.
- **Desempenho:** tudo é calculado em lote: SQLite agregado por conversa, `leads` do CRM em 3 páginas em
  paralelo e a RPC `crm_jornada_visao`, essas duas com cache de 60 s. Na base real (1.439 itens) levou 0,5 s
  frio e 0,1 s com cache. A resposta, de ~800 KB, vai em gzip (~10x menor).
- **SQL a aplicar:** `sql/crm_jornada_visao.sql`. Traz, por catálogo: lead dono, produtos, provas, envios
  automáticos (segunda chance / régua), conta e PIX pendente. Já foi conferido como SELECT no banco real: 0,36 s.
  Sem a função, a visão geral funciona igual, só sem os sinais de catálogo, e mostra um aviso.
- **Limitação:** "há quanto tempo na etapa" depende do `etapa_historico` (novo) ou das notas "movido para" do CRM.
  Para leads antigos que não estão em Novo aparece "sem registro" até a próxima mudança de etapa.
