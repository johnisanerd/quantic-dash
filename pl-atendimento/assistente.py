"""Assistente IA do CRM de prospecção: a Dione (e o Lucas) conversam sobre o negócio.

Acesso a dados: só pela função crm_ia_contexto(p_chave) do Supabase, que devolve um
retrato do funil, dos leads em andamento e do uso dos catálogos — sem telefone, e-mail,
chave de loja ou faturamento de lojista. A chave da IA (PL_IA_KEY) fica só no EasyPanel;
no banco existe apenas o hash dela (tabela crm_ia_chave, invisível pra anon).
"""
import json
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request

USUARIOS = {"lucas", "dione"}
MODELO = os.environ.get("PL_IA_MODELO", "gemini-2.5-flash")   # ou claude-haiku-5-5 (precisa ANTHROPIC_API_KEY)
MAX_TURNOS = 24
CACHE_SEG = 180
MAX_RESULTADO = 25000   # caracteres por resultado de ferramenta
ETAPAS_RETRATO = {"testando", "teste_catalogo_7_dias", "testando_ativo", "aguardando_cadastro", "passou_prazo",
                  "proposta_enviada", "negociando", "aguardando_pagamento"}

BASE = """# Provou Levou — o que vendemos

Provador virtual com IA para lojas de óculos, roupa e acessórios. O cliente da loja manda uma
foto e se vê usando o produto antes de comprar. Tagline: "O provador virtual que materializa o
desejo de compra." Site provoulevou.com.br · Instagram @provoulevouapp · WhatsApp comercial
(11) 93803-4714 · contato@provoulevou.com.br.

## Dois produtos
1. PROVADOR NO SITE — para quem tem loja online. Botão "Provar" na página do produto.
   Plataformas: Shopify, Nuvemshop, Tray, Bagy, VTEX, WooCommerce, Loja Integrada, Wix ou
   qualquer loja que aceite script (via Google Tag Manager). Instala em ~5 min (GTM, FTP ou app
   da plataforma), sem mexer no código da loja; a equipe costuma deixar no ar no mesmo dia.
   O lojista ganha painel com quem provou o quê e quem comprou depois (atribuição), e captura
   o WhatsApp de quem provou.
2. PROVOU CATÁLOGO — para quem NÃO tem loja online (vende por Instagram, WhatsApp ou loja
   física). Montamos um catálogo próprio com o provador dentro, num link só
   (provoulevou.com.br/catalogo/?loja=<nome>). O lojista cadastra os produtos num login
   próprio (foto, nome, preço) e divulga o link. Para criar: logo da loja, e-mail do login e
   WhatsApp da loja.
Em ambos criamos um grupo no WhatsApp onde o lojista recebe cada prova em tempo real (foto do
cliente usando o produto + modelo provado + WhatsApp do cliente), para chamar enquanto o
interesse está quente. 7 dias grátis para testar, sem cartão e sem custo de instalação.

## Planos do Provou Catálogo (mensais — é a tabela que o comercial envia)
Essencial R$ 39 (50 provas) · Crescimento R$ 79 (100) · Profissional R$ 159 (200) ·
Escala R$ 369 (500) · Volume 1.000 R$ 699 · Volume 1.500 R$ 959 · Volume 2.500 R$ 1.499.
No fim do teste recomendamos o pacote pelo volume real de provas (projete as provas dos
últimos 7 dias para 30 dias).

## Planos do Provador no site (mensais)
Essencial R$ 97 (50 fotos) · Crescimento R$ 147 (100) · Acelerador R$ 347 (300) ·
Performance R$ 547 (500, o mais vendido) · Escala R$ 997 (1.200) · acima disso, plano
Enterprise sob medida (SLA + gerente de conta) — falar com o Lucas.

## Números para argumentar
- +10.000 provas realizadas; R$ 230 mil+ em vendas atribuídas ao provador; ~22% de atribuição média.
- Conversão de quem usa o provador chega a 14,32% (Cacife Brand) — ~7,5x a média de moda online no Brasil (1,9%).
- Cacife Brand: instalou em março; abril vs abril do ano anterior, faturamento por dia +22%, e
  mais de R$ 100 mil em vendas de clientes que provaram antes de comprar.
- Óticas: 51% de quem prova compra em até 1h; até 30% das vendas atribuídas ao provador.
- Devoluções caem 23–78% em estudos globais (Warby Parker −27%).
- Regra prática: para cada R$ 10 mil/mês que a loja fatura, o provador costuma somar R$ 1,2–1,5 mil.
Clientes conhecidos: Cacife Brand, Mariana Cardoso, Amazoni, Maxilook, Califa, Paris London,
Ótica Style, Liuzzi, Mi Piace, Oclinhos de Leitura, Soucet, Marandola, Menina Flor e dezenas de
óticas no Provou Catálogo.

## Exemplos no ar para mostrar a um lead
O retrato dos dados traz `lojas_site_ativas`: lojas com o provador NO SITE rodando nos últimos 30 dias, com
segmento (roupa, óculos, acessórios/outros), provas no mês e um link de página de produto. Quando pedirem
"exemplos", "modelos para apresentar" ou "lojas de roupa/óculos com provador", mande 3 links desse campo,
do segmento pedido e com mais provas, sempre com https:// e www quando o link tiver (link sem https pode
aparecer como "não confiável" no navegador), e diga para tocar no botão "Provar" da página.
Hoje o Provou Catálogo está ativo só com óticas; o catálogo funciona para roupa, mas para MOSTRAR roupa
use as lojas de roupa com provador no site (ex.: Programmoda — plus size, Laço de Luxo — vestidos,
Coletivo Emaus — camisetas).

## Objeções (respostas que já usamos)
- "Sem interesse no momento": não forçar. Agradecer, deixar um dado forte (Cacife +22%,
  +R$ 100 mil atribuídos) e o convite dos 7 dias grátis sem cartão. Lead morno volta em 2–3 meses.
- "Achei caro / quanto custa?": ancorar no retorno antes do preço (1,9% → até 15% de conversão;
  R$ 1,2–1,5 mil a mais por R$ 10 mil faturados) e fechar com os 7 dias grátis.
- Reaquecer lead parado: curto e direto — "Bora instalar os 7 dias grátis de provador?" ou
  "Conseguiu dar uma olhada no que te enviei sobre o Provador Virtual?".
- Quem só tem loja física, Instagram ou WhatsApp → Provou Catálogo.

## Etapas do funil (out/2026) — rótulo no painel = código no CRM
NOVO = novo (chegou, ainda não respondeu de verdade) · EM CONVERSA = respondeu (respondeu; descobrindo onde vende) ·
INTERESSADO = interessado (pediu preço/como funciona) · AGUARDANDO DADOS = testando (aceitou o teste; falta logo,
e-mail ou WhatsApp) · EM TESTE = testando_ativo (catálogo/provador no ar) · TESTE PARADO = passou_prazo (no ar sem
produto/prova há 3 dias ou teste de 7 dias vencido) · PROPOSTA ENVIADA = proposta_enviada · AGUARDANDO PAGAMENTO =
aguardando_pagamento · CONVERTIDO = fechou · STAND-BY = stand_by (com data de retorno em retomar_em) · PERDIDO =
perdida (com motivo em motivo_perda). Etapas antigas (meta, dm_enviada, mensagem_1..3, contatar, negociando…) foram
migradas para essas. No Pipeline de atendimento (SQLite) o status usa o rótulo em maiúsculas.
"""

REGRAS = """Você é o assistente interno do time comercial da Provou Levou, dentro do CRM de prospecção.
Quem conversa com você é %(quem)s. Hoje é %(hoje)s (horário de Brasília).

Use a BASE DE CONHECIMENTO e o RETRATO DOS DADOS abaixo para responder sobre o negócio, o funil,
os leads em teste e o uso dos catálogos, sugerir próximos passos e escrever mensagens de WhatsApp.

Você tem duas ferramentas — USE-AS sempre que a pergunta for sobre leads, etapas, status, planos fechados,
conversas, quantidades ou datas (o retrato abaixo é só um resumo):
- buscar_leads_crm: CRM do Supabase (pipeline de prospecção: etapa, responsável, notas, teste grátis, origem).
- consultar_pipeline: SQL SELECT (SQLite) no Pipeline de atendimento do WhatsApp — status do chat,
  plano fechado e valor, comissão, mensagens trocadas, quem iniciou cada conversa.
- preparar_disparo: quando pedirem para disparar/mandar mensagem para leads. Primeiro ache os leads (ferramentas
  acima), depois prepare. Você NUNCA envia: a pessoa confere a lista e clica em Disparar no cartão. Diga quantos
  destinatários ficaram, quantos ficaram de fora (sem conversa no WhatsApp ou acima do limite de 100) e peça para
  revisar. Não inclua quem já fechou (CONVERTIDO/fechou) ou foi perdido, a menos que peçam explicitamente.
Pode chamar várias vezes e combinar. Se a consulta der erro, corrija e tente de novo.

Regras:
- Português do Brasil, direto, com recomendação clara. Nada de rodeio.
- Sobre a empresa, os produtos, como funciona, planos, números de argumentação e exemplos de lojas no ar: responda
  com segurança pela BASE DE CONHECIMENTO e por `lojas_site_ativas` — você conhece a Provou Levou, não mande
  perguntar ao Lucas o que está aqui.
- Números e status de leads/catálogos: SOMENTE do retrato dos dados ou das ferramentas. Se não estiver lá, diga que
  não tem esse dado aqui e sugira perguntar ao Lucas. Nunca invente preço, desconto, prazo,
  funcionalidade ou case.
- Quem já é cliente: antes de dizer que uma loja NÃO é cliente (ou de tratá-la como lead novo), confira
  `clientes_provador_site` (provador no site; compare pelo nome E pelo site/domínio) e `catalogos`. Essa lista é a
  fonte oficial e vale mais que a etapa do CRM, que pode estar desatualizada. situacao 'Ativo' = cliente pagante,
  'Teste Gratuito' = em teste, 'Inativo' = ex-cliente ou desligado. Se a loja está na lista mas o CRM mostra outra
  etapa, responda que ela é cliente e avise que o CRM está desatualizado.
- Desconto, plano fora da tabela, Enterprise ou questão técnica de instalação: oriente a falar com o Lucas.
- Mensagem para lojista: estilo WhatsApp, 2 a 5 linhas, no máximo um emoji, pronta para copiar.
  Nunca use colchetes/placeholder ([Nome]); se não souber o nome da pessoa, comece com "Oi, tudo bem?".
- Prioridade de cobrança: o teste dura 7 dias a partir de "teste_desde". Mais urgente = mais dias
  de teste corridos (5–7 dias ou já passou) com pouco uso (0 produtos ou provas_7d = 0). Catálogo
  criado hoje ou ontem ainda NÃO é urgente — no máximo um empurrão para cadastrar produtos.
  Quem está provando bem (provas_7d alto) perto do fim do teste é hora de propor o pacote.
- Se o lojista perguntou o preço, responda com os valores (a tabela do produto certo) e convide
  para os 7 dias grátis — não fuja do preço.
- Responda em markdown simples (listas curtas, negrito pontual). Tabelas só se pedirem.
"""

_cache = {"em": 0, "txt": ""}
_lock = threading.Lock()


def _post(url, body, headers, timeout=120):
    r = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                               headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        return json.loads(x.read().decode("utf-8"))


def contexto(crm_url, crm_key):
    with _lock:
        if time.time() - _cache["em"] < CACHE_SEG and _cache["txt"]:
            return _cache["txt"]
        chave = os.environ.get("PL_IA_KEY", "")
        if not (crm_url and crm_key and chave):
            raise RuntimeError("Assistente sem configuração (PL_IA_KEY / Supabase).")
        d = _post(crm_url.rstrip("/") + "/rest/v1/rpc/crm_ia_contexto", {"p_chave": chave},
                  {"apikey": crm_key, "Authorization": "Bearer " + crm_key})
        # retrato enxuto (o resto a IA busca pelas ferramentas): só leads em teste/proposta, notas curtas
        d["leads_em_andamento"] = [dict(l, notas=(l.get("notas") or "")[-200:]) for l in d.get("leads_em_andamento") or []
                                   if l.get("etapa") in ETAPAS_RETRATO]
        d.pop("convertidos_recentes", None)
        _cache.update(em=time.time(), txt=json.dumps(d, ensure_ascii=False, separators=(",", ":")))
        return _cache["txt"]


ESQUEMA_PIPELINE = """Tabelas (SQLite, só leitura):
- leads(chatid, fone, nome, status, responsavel, ultimo_ts, ultimo_de, oculto)
  status do chat: NOVO, EM CONVERSA, INTERESSADO, AGUARDANDO DADOS, EM TESTE, TESTE PARADO, PROPOSTA ENVIADA,
  AGUARDANDO PAGAMENTO, CONVERTIDO, STAND-BY, PERDIDO. responsavel: 'Lucas' | 'Dione' | NULL. ultimo_de: 'lead' (esperando a gente) | 'nos'.
  ultimo_ts = epoch em segundos (ou ms se > 1e11). oculto=1 = removido da fila.
- mensagens(chatid, ts, from_me, tipo, texto)   -- from_me=1 nós; ts epoch (s ou ms); áudio transcrito vem como '[áudio] …'
- planos_fechados(chatid, lead_id, plano, valor_centavos, fechado_em, atualizado_em)  -- fechado_em ISO -03:00
- comissoes_status(chatid, cliente_pagou_em, comissao_paga_em)   -- comissão = 20% da 1ª mensalidade
- conversas_iniciadas(chatid, ts, responsavel) / atendimentos_iniciados(chatid, responsavel, ts)
- conversas_atribuidas(chatid, responsavel, ts)
- crm_links(chatid, lead_id)   -- liga o chat ao lead do CRM (Supabase)
- grupos_catalogos(chatid, lead_chatid, nome, responsavel)   -- grupos de WhatsApp dos catálogos
Datas: date(CASE WHEN ts>100000000000 THEN ts/1000 ELSE ts END,'unixepoch','-3 hours')."""

FERRAMENTAS = [{"functionDeclarations": [
    {"name": "buscar_leads_crm",
     "description": "Busca leads no CRM (Supabase). Devolve total_encontrado, contagens por_etapa/por_fonte/por_responsavel do conjunto filtrado e até 'limite' leads (mais recentes primeiro) "
                    "com loja, etapa, responsável, instagram, site, plataforma, categoria, fonte, criado, atualizado, "
                    "teste_desde e notas. Etapas (funil out/2026): novo, respondeu (Em conversa), interessado, testando "
                    "(Aguardando dados), testando_ativo (Em teste), passou_prazo (Teste parado), proposta_enviada, "
                    "aguardando_pagamento, fechou (Convertido), stand_by, perdida.",
     "parameters": {"type": "OBJECT", "properties": {
         "busca": {"type": "STRING", "description": "texto no nome da loja, instagram, site ou notas"},
         "etapas": {"type": "ARRAY", "items": {"type": "STRING"}},
         "responsavel": {"type": "STRING", "description": "Lucas ou Dione"},
         "atualizado_desde": {"type": "STRING", "description": "AAAA-MM-DD"},
         "fonte": {"type": "STRING", "description": "origem do lead, ex.: Meta, WhatsApp, Instagram"},
         "criado_desde": {"type": "STRING", "description": "entrou no CRM a partir de AAAA-MM-DD"},
         "criado_ate": {"type": "STRING", "description": "entrou no CRM até AAAA-MM-DD (inclusive)"},
         "limite": {"type": "INTEGER", "description": "1 a 300 (padrão 100). Para CONTAR use limite 1 e leia total_encontrado/por_etapa/por_fonte"}}}},
    {"name": "preparar_disparo",
     "description": "Prepara (NÃO envia) um disparo de WhatsApp pela instância Quantic 4714. A pessoa revisa a lista e a "
                    "mensagem num cartão e só ela confirma o envio. Passe chatids (do consultar_pipeline, coluna chatid) "
                    "e/ou lead_ids (campo id do buscar_leads_crm). Máximo 100 destinatários. Use {nome} no texto para o "
                    "primeiro nome de cada lead. Separe em mais de uma mensagem com uma linha contendo só ---.",
     "parameters": {"type": "OBJECT", "properties": {
         "chatids": {"type": "ARRAY", "items": {"type": "STRING"}},
         "lead_ids": {"type": "ARRAY", "items": {"type": "STRING"}},
         "texto": {"type": "STRING"}}, "required": ["texto"]}},
    {"name": "consultar_pipeline",
     "description": "Executa um SELECT (SQLite) no Pipeline de atendimento do WhatsApp. " + ESQUEMA_PIPELINE,
     "parameters": {"type": "OBJECT", "properties": {"sql": {"type": "STRING"}}, "required": ["sql"]}},
]}]

_PIPE_TABELAS = ("conversas_iniciadas", "atendimentos_iniciados", "conversas_atribuidas", "crm_links", "grupos_catalogos")


def consultar_pipeline(sql, db_path, usuario):
    """SELECT só-leitura. Abre o painel.db em modo ro e expõe só views temporárias;
    para a Dione, planos/comissões aparecem só dos clientes dela (mesma regra da tela Comissões)."""
    sql = (sql or "").strip().rstrip(";")
    if not sql.lower().startswith(("select", "with")) or ";" in sql:
        return {"erro": "Só um SELECT por vez."}
    c = sqlite3.connect("file::memory:", uri=True)
    try:
        c.execute("ATTACH DATABASE ? AS src", ("file:%s?mode=ro" % db_path,))
        dono = "" if usuario == "lucas" else " WHERE chatid IN (SELECT chatid FROM src.leads WHERE responsavel='Dione')"
        c.execute("CREATE TEMP VIEW leads AS SELECT chatid,fone,nome,status,responsavel,ultimo_ts,ultimo_de,oculto FROM src.leads")
        c.execute("CREATE TEMP VIEW mensagens AS SELECT m.chatid, m.ts, m.from_me, m.tipo, "
                  "COALESCE(NULLIF(m.texto,''), CASE WHEN t.texto IS NOT NULL THEN '[áudio] ' || t.texto END) texto "
                  "FROM src.mensagens m LEFT JOIN src.transcricoes t ON t.url = 'msg:' || m.messageid WHERE m.excluida=0")
        c.execute("CREATE TEMP VIEW planos_fechados AS SELECT * FROM src.planos_fechados" + dono)
        c.execute("CREATE TEMP VIEW comissoes_status AS SELECT chatid,cliente_pagou_em,comissao_paga_em FROM src.comissoes_status" + dono)
        for t in _PIPE_TABELAS:
            c.execute("CREATE TEMP VIEW %s AS SELECT * FROM src.%s" % (t, t))

        def autoriza(acao, a1, a2, banco, view):
            if acao in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            if acao == sqlite3.SQLITE_READ and (banco == "temp" or (banco == "src" and view)):
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        c.set_authorizer(autoriza)
        fim = time.time() + 5
        c.set_progress_handler(lambda: 1 if time.time() > fim else 0, 10000)
        cur = c.execute(sql)
        cols = [d[0] for d in cur.description or []]
        linhas = cur.fetchmany(201)
        return {"colunas": cols, "linhas": [list(l) for l in linhas[:200]], "cortado": len(linhas) > 200}
    except sqlite3.Error as e:
        return {"erro": str(e)[:300]}
    finally:
        c.close()


def buscar_leads_crm(args, crm_url, crm_key):
    corpo = {"p_chave": os.environ.get("PL_IA_KEY", "")}
    for k in ("busca", "etapas", "responsavel", "atualizado_desde", "limite", "fonte", "criado_desde", "criado_ate"):
        if args.get(k) not in (None, "", []):
            corpo["p_" + k] = args[k]
    try:
        d = _post(crm_url.rstrip("/") + "/rest/v1/rpc/crm_ia_leads", corpo,
                  {"apikey": crm_key, "Authorization": "Bearer " + crm_key})
    except urllib.error.HTTPError as e:
        return {"erro": e.read().decode("utf-8", "replace")[:300]}
    # Teto de tamanho: resultado gigante estoura o contexto (e o preço do Claude acima de 100k tokens).
    leads = d.get("leads") or []
    while leads and len(json.dumps(leads, ensure_ascii=False)) > MAX_RESULTADO:
        leads = [dict(l, notas=(l.get("notas") or "")[-120:]) for l in leads[:max(1, len(leads) // 2)]]
        d["lista_cortada"] = "mostrando %d de %d; use as contagens ou filtre mais" % (len(leads), d.get("total_encontrado", 0))
    d["leads"] = leads
    return d


MAX_DISPARO = 100


def preparar_disparo(a, db_path):
    """Resolve os destinatários no painel.db (só leitura). Quem não tem conversa no WhatsApp
    da instância fica de fora — o disparo só sai para conversas existentes."""
    texto = str(a.get("texto") or "").strip()
    if not texto:
        return {"erro": "Falta o texto da mensagem."}
    chatids = [str(x).strip() for x in (a.get("chatids") or []) if str(x).strip()]
    lead_ids = [str(x).strip() for x in (a.get("lead_ids") or []) if str(x).strip()]
    if not (chatids or lead_ids):
        return {"erro": "Informe chatids ou lead_ids."}
    c = sqlite3.connect("file:%s?mode=ro" % db_path, uri=True)
    c.row_factory = sqlite3.Row
    try:
        sem_conversa = 0
        if lead_ids:
            marcas = ",".join("?" * len(lead_ids))
            achados = {r["lead_id"]: r["chatid"] for r in c.execute(
                "SELECT lead_id, chatid FROM crm_links WHERE lead_id IN (%s)" % marcas, lead_ids)}
            sem_conversa = len([l for l in lead_ids if l not in achados])
            chatids += [achados[l] for l in lead_ids if l in achados]
        chatids = [x for x in dict.fromkeys(chatids) if not x.endswith("@g.us")]
        linhas = {}
        for i in range(0, len(chatids), 500):
            parte = chatids[i:i + 500]
            for r in c.execute("SELECT chatid, nome, status, responsavel FROM leads WHERE chatid IN (%s)"
                               % ",".join("?" * len(parte)), parte):
                linhas[r["chatid"]] = dict(r)
    finally:
        c.close()
    itens = [linhas[x] for x in chatids if x in linhas]
    sem_conversa += len(chatids) - len(itens)
    cortados = max(0, len(itens) - MAX_DISPARO)
    return {"destinatarios": len(itens[:MAX_DISPARO]), "itens": itens[:MAX_DISPARO], "texto": texto,
            "sem_conversa_no_whatsapp": sem_conversa, "cortados_pelo_limite": cortados,
            "aviso": "Rascunho pronto. NADA foi enviado: a pessoa precisa revisar e clicar em Disparar no cartão."}


def _executa(nome, a, usuario, crm_url, crm_key, db_path, estado=None):
    if nome == "preparar_disparo" and db_path:
        r = preparar_disparo(a, db_path)
        if estado is not None and r.get("itens"):
            estado["disparo"] = r
        return dict(r, itens="%d destinatários (lista vai no cartão)" % len(r["itens"])) if r.get("itens") else r
    if nome == "buscar_leads_crm":
        return buscar_leads_crm(a, crm_url, crm_key)
    if nome == "consultar_pipeline" and db_path:
        return consultar_pipeline(a.get("sql"), db_path, usuario)
    return {"erro": "ferramenta indisponível"}


def _tipo_claude(p):
    """Converte o schema estilo Gemini (OBJECT/STRING) para JSON Schema."""
    out = {k: v for k, v in p.items() if k not in ("type", "properties", "items")}
    out["type"] = p["type"].lower()
    if "properties" in p:
        out["properties"] = {k: _tipo_claude(v) for k, v in p["properties"].items()}
    if "items" in p:
        out["items"] = _tipo_claude(p["items"])
    return out


def _responde_claude(sistema, turnos, usuario, crm_url, crm_key, db_path, estado):
    chave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chave:
        raise RuntimeError("Sem ANTHROPIC_API_KEY no servidor.")
    tools = [{"name": f["name"], "description": f["description"], "input_schema": _tipo_claude(f["parameters"])}
             for f in FERRAMENTAS[0]["functionDeclarations"]]
    msgs = [{"role": "assistant" if t["role"] == "model" else "user", "content": t["parts"][0]["text"]} for t in turnos]
    h = {"x-api-key": chave, "anthropic-version": "2023-06-01"}
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):   # chave de usuário (sk-ant-usr) exige o workspace
        h["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    for _ in range(8):
        corpo = {"model": MODELO, "max_tokens": 4096, "tools": tools, "messages": msgs,
                 "system": [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}]}
        for t in range(3):
            try:
                d = _post("https://api.anthropic.com/v1/messages", corpo, h, timeout=180)
                break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 529) and t < 2:
                    time.sleep(2 + t * 3)
                    continue
                raise RuntimeError("A IA não respondeu (HTTP %d). Tente de novo." % e.code)
        blocos = d.get("content", [])
        usos = [b for b in blocos if b.get("type") == "tool_use"]
        if d.get("stop_reason") != "tool_use" or not usos:
            return "".join(b.get("text", "") for b in blocos if b.get("type") == "text").strip()
        msgs = msgs + [{"role": "assistant", "content": blocos},
                       {"role": "user", "content": [{"type": "tool_result", "tool_use_id": b["id"],
                                                     "content": json.dumps(_executa(b["name"], b.get("input") or {}, usuario,
                                                                                    crm_url, crm_key, db_path, estado),
                                                                           ensure_ascii=False, default=str)}
                                                    for b in usos]}]
    return "Precisei de consultas demais para responder. Tente uma pergunta mais específica."


def responde(usuario, mensagens, gemini_key, crm_url, crm_key, hoje, db_path=None):
    usuario = (usuario or "").strip().lower()
    if usuario not in USUARIOS:
        raise PermissionError("Assistente disponível só para o comercial.")
    if not gemini_key and not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("Sem chave de IA no servidor.")
    if not isinstance(mensagens, list) or not mensagens:
        raise ValueError("Mande ao menos uma mensagem.")
    turnos = []
    for m in mensagens[-MAX_TURNOS:]:
        texto = str((m or {}).get("texto") or "").strip()[:6000]
        if texto:
            turnos.append({"role": "model" if m.get("de") == "ia" else "user", "parts": [{"text": texto}]})
    if not turnos or turnos[-1]["role"] != "user":
        raise ValueError("A última mensagem precisa ser sua.")
    sistema = (REGRAS % {"quem": "a Dione (comercial)" if usuario == "dione" else "o Lucas (dono)", "hoje": hoje}
               + "\n\n# BASE DE CONHECIMENTO\n" + BASE
               + "\n\n# RETRATO DOS DADOS (JSON, gerado agora do CRM)\n" + contexto(crm_url, crm_key))
    estado = {}
    if MODELO.startswith("claude"):
        try:
            return _final(_responde_claude(sistema, turnos, usuario, crm_url, crm_key, db_path, estado), estado)
        except RuntimeError:
            if not gemini_key:
                raise
            # Claude fora do ar / sem crédito: responde pelo Gemini em vez de deixar a Dione sem resposta
    corpo = {"systemInstruction": {"parts": [{"text": sistema}]}, "contents": turnos, "tools": FERRAMENTAS,
             "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096,
                                  "thinkingConfig": {"thinkingBudget": 1024}}}
    url = ("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s"
           % (MODELO if MODELO.startswith("gemini") else "gemini-2.5-flash", gemini_key))
    for _ in range(8):   # rodadas de ferramenta
        partes = _gemini(url, corpo)
        chamadas = [p["functionCall"] for p in partes if p.get("functionCall")]
        if not chamadas:
            return _final("".join(p.get("text", "") for p in partes if not p.get("thought")).strip(), estado)
        respostas = []
        for f in chamadas:
            r = _executa(f["name"], f.get("args") or {}, usuario, crm_url, crm_key, db_path, estado)
            respostas.append({"functionResponse": {"name": f["name"], "response": {"resultado": json.loads(json.dumps(r, default=str))}}})
        corpo["contents"] = corpo["contents"] + [{"role": "model", "parts": partes}, {"role": "user", "parts": respostas}]
    return _final("Precisei de consultas demais para responder. Tente uma pergunta mais específica.", estado)


def _final(texto, estado):
    return {"texto": texto, "disparo": estado.get("disparo")}


def _gemini(url, corpo):
    for t in range(3):
        try:
            d = _post(url, corpo, {}, timeout=180)
            return d["candidates"][0]["content"]["parts"]
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 503) and t < 2:
                time.sleep(2 + t * 3)
                continue
            raise RuntimeError("A IA não respondeu (HTTP %d). Tente de novo." % e.code)
        except (KeyError, IndexError):
            raise RuntimeError("A IA não conseguiu responder essa. Reformule a pergunta.")
    raise RuntimeError("A IA está ocupada. Tente de novo em instantes.")


# ───────────── histórico (o Lucas lê as conversas da equipe) ─────────────

def _log_con(db_path):
    c = sqlite3.connect(db_path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE IF NOT EXISTS assistente_log (id INTEGER PRIMARY KEY AUTOINCREMENT, usuario TEXT NOT NULL, "
              "conversa_id TEXT NOT NULL, pergunta TEXT NOT NULL, resposta TEXT NOT NULL, disparo_n INTEGER DEFAULT 0, "
              "ts INTEGER NOT NULL)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_assistente_log ON assistente_log(conversa_id, ts)")
    return c


def registra(db_path, usuario, conversa_id, pergunta, resposta, disparo):
    c = _log_con(db_path)
    try:
        c.execute("INSERT INTO assistente_log(usuario,conversa_id,pergunta,resposta,disparo_n,ts) VALUES(?,?,?,?,?,?)",
                  ((usuario or "").strip().lower(), str(conversa_id or "sem-id")[:64], str(pergunta)[:6000],
                   str(resposta)[:20000], len((disparo or {}).get("itens") or []), int(time.time())))
        c.commit()
    finally:
        c.close()


def lista_conversas(db_path, limite=200):
    c = _log_con(db_path)
    try:
        return [dict(r) for r in c.execute(
            "SELECT conversa_id, usuario, MIN(ts) inicio, MAX(ts) ultima, COUNT(*) perguntas, SUM(disparo_n>0) disparos, "
            "(SELECT pergunta FROM assistente_log x WHERE x.conversa_id=l.conversa_id ORDER BY ts LIMIT 1) primeira "
            "FROM assistente_log l GROUP BY conversa_id, usuario ORDER BY ultima DESC LIMIT ?", (limite,))]
    finally:
        c.close()


def le_conversa(db_path, conversa_id):
    c = _log_con(db_path)
    try:
        return [dict(r) for r in c.execute(
            "SELECT usuario, pergunta, resposta, disparo_n, ts FROM assistente_log WHERE conversa_id=? ORDER BY ts, id",
            (conversa_id,))]
    finally:
        c.close()
