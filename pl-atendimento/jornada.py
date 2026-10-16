"""Jornada do lead (aba Jornada do CRM): cada passo do lead, o que nós fizemos e o que ele fez.

Junta numa linha do tempo só (mais detalhe em JORNADA.md):
  painel.db  -> mensagens (privado + grupo do catálogo), etapa_historico (mudanças de etapa a partir de
                agora), etapa_sugestao (Jev), conversas_atribuidas / atendimentos_iniciados (responsável),
                planos_fechados, tarefas (do próprio login que citam a loja)
  Supabase   -> leads (+ linhas datadas de leads.notas: movimentos automáticos do funil), interacoes,
                pl_catalog_stores e, pela RPC crm_jornada_loja (chave PL_IA_KEY), onboarding, produtos e
                provas por dia, cobranças PIX/boleto, pagamentos e os envios da régua de 30 dias.
Sem a RPC no ar, cai pro que a chave anon lê (catálogo, produtos) e conta as provas pelo grupo.
Só leitura no Supabase. A única escrita é local: etapa_historico (registra_etapa)."""
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, date

import etapas
import grupos_catalogos
from historico_lead import BRT, CLASSES, PROVA, _dt, _iso, _digitos, _core, casa_catalogo

# ───────────────────────── histórico de etapas (local) ─────────────────────────

def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS etapa_historico (id INTEGER PRIMARY KEY AUTOINCREMENT, chatid TEXT NOT NULL, "
              "de TEXT, para TEXT NOT NULL, ts INTEGER NOT NULL, origem TEXT NOT NULL, por TEXT)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_etapa_historico ON etapa_historico(chatid, ts)")


def registra_etapa(c, chatid, de, para, origem, por=None, ts=None):
    """origem: manual (botão no painel/CRM) | jev (moveu sozinho) | jev_sugestao (alguém aplicou) |
    crm (mudou fora do painel: rotina do funil, agente de catálogos, Quantic Dash). Não faz commit."""
    if not chatid or not para or (de or "") == para:
        return
    linha = (chatid, de, para, int(ts or time.time()), origem, por)
    try:
        c.execute("INSERT INTO etapa_historico(chatid,de,para,ts,origem,por) VALUES(?,?,?,?,?,?)", linha)
    except sqlite3.OperationalError:
        init(c)
        c.execute("INSERT INTO etapa_historico(chatid,de,para,ts,origem,por) VALUES(?,?,?,?,?,?)", linha)


# ───────────────────────── régua de 30 dias do catálogo ─────────────────────────
# entrega = dia 1; montagem até o dia 21; teste grátis do 22 ao 28
REGUA = [(7, "montagem_7", "Montagem · dia 7"), (14, "montagem_14", "Montagem · dia 14"),
         (21, "vespera", "Véspera do teste · dia 21"), (22, "inicio_teste", "Início do teste grátis · dia 22"),
         (28, "ultimo_dia", "Último dia do teste · dia 28")]
ROTULO_ENVIO = {e: r for _, e, r in REGUA}

CATEGORIAS = ("mensagens", "etapas", "catalogo", "financeiro", "notas", "responsavel", "lead")
QUEM_ROTULO = {"nos": "Nós", "lead": "Lead", "sistema": "Sistema (automático)", "jev": "Jev"}
ORIGEM_ROTULO = {"manual": "mudança manual", "jev": "Jev moveu sozinho", "jev_sugestao": "sugestão do Jev aplicada",
                 "crm": "mudou fora do painel (rotina do funil, agente de catálogos ou CRM)"}
TIPO_COBRANCA = {"plano": "plano", "avulsas": "provas avulsas", "boleto": "boleto", "excedente": "excedente"}

TEXTO = {None, "", "Conversation", "ExtendedTextMessage", "TextMessage", "TemplateMessage", "ButtonsMessage",
         "ButtonsResponseMessage", "ListMessage", "ListResponseMessage", "NativeFlowMessage", "InteractiveMessage",
         "TemplateButtonReplyMessage", "Queued", "error", "UnknownMessageType"}
IGNORA = {"ReactionMessage", "PinInChatMessage"}   # reação/fixar: não é fala de ninguém

_CACHE = {"stores": (0.0, None)}


def _stores(crm):
    at, data = _CACHE["stores"]
    if data is not None and time.monotonic() - at < 60:
        return data
    data = crm.request("pl_catalog_stores", {"select": "id,slug,display_name,owner_email,whatsapp,created_at,entregue_em,teste_30d"}) or []
    _CACHE["stores"] = (time.monotonic(), data)
    return data


def _rpc(crm, nome, corpo):
    chave = os.environ.get("PL_IA_KEY", "")
    if not chave:
        raise RuntimeError("sem PL_IA_KEY")
    return crm.request("rpc/" + nome, method="POST", body=dict(corpo, p_chave=chave))


def _data(s):
    """'2026-10-15' ou timestamptz -> date (BRT)."""
    if not s:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    s = str(s)
    if len(s) == 10:
        try:
            return date.fromisoformat(s)
        except ValueError:
            return None
    d = _iso(s)
    return d.date() if d else None


def _meio_dia(d):
    return datetime(d.year, d.month, d.day, 12, 0, tzinfo=BRT)


def _moeda(v):
    try:
        return ("R$ %.2f" % float(v)).replace(".", ",")
    except (TypeError, ValueError):
        return ""


def _fmt_dur(seg):
    if seg is None:
        return None
    m = seg / 60
    if m < 60:
        return "%d min" % max(1, round(m))
    h = m / 60
    if h < 48:
        return ("%.1f h" % h).replace(".", ",")
    return "%d dias" % round(h / 24)


def _mediana(xs):
    xs = sorted(xs)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _seg(ms):
    ms = int(ms or 0)
    return ms // 1000 if ms > 100000000000 else ms


def _rotulo_midia(tipo, seg):
    n = {"AudioMessage": "áudio", "ImageMessage": "imagem", "VideoMessage": "vídeo", "DocumentMessage": "documento",
         "StickerMessage": "figurinha", "LocationMessage": "localização", "ContactMessage": "contato",
         "ContactsArrayMessage": "contatos", "AlbumMessage": "álbum", "PtvMessage": "vídeo",
         "GroupInviteMessage": "convite de grupo"}.get(
        tipo, (tipo or "mídia").replace("Message", "").lower())
    return "[%s%s]" % (n, " de %ss" % seg if seg else "")


def _rotulo_etapa(texto):
    """'Teste parado' (texto livre das notas) -> 'TESTE PARADO' (rótulo do funil), se reconhecer."""
    t = _core(texto)
    for rot, slug in etapas.FUNIL:
        if t in (_core(rot), _core(etapas.ROTULO_CRM.get(slug, ""))):
            return rot
    return None


NOTA_DATADA = re.compile(r"^\s*(\d{2})/(\d{2})/(\d{4}):\s*(.+?)\s*$")
NOTA_CRM = re.compile(r"^\s*\[CRM (\d{2})/(\d{2})\]\s*(.+?)\s*$")
MOVIDO = re.compile(r"(?i)movido para ([^(.]+?)\s*(?:\((.+)\))?\.?$")


class _Jornada:
    def __init__(self, agora):
        self.agora = agora
        self.eventos = []

    def ev(self, dt, cat, tipo, titulo, detalhe="", quem="sistema", canal="sistema", por=None, sem_hora=False, **extra):
        if not dt:
            return None
        e = {"ts": dt.isoformat(), "dia": dt.strftime("%Y-%m-%d"),
             "quando": dt.strftime("%d/%m/%Y") if sem_hora else dt.strftime("%d/%m/%Y %H:%M"),
             "hora": "" if sem_hora else dt.strftime("%H:%M"),
             "cat": cat, "tipo": tipo, "titulo": titulo, "detalhe": (detalhe or "").strip()[:400],
             "quem": quem, "quem_rotulo": por or QUEM_ROTULO.get(quem, quem), "canal": canal}
        e.update(extra)
        self.eventos.append(e)
        return e


def _acha_lead(c, crm, chatid, crm_id):
    campos = "id,nome_loja,telefone,whatsapp,email,created_at,updated_at,status,responsavel,notas,fonte_oportunidade," \
             "teste_gratis_em,retomar_em,motivo_perda,tentativas"
    lead_crm = None
    if crm_id:
        rows = crm.request("leads", {"id": "eq." + crm_id, "select": campos})
        lead_crm = rows[0] if rows else None
    if not lead_crm and chatid:
        linked = c.execute("SELECT lead_id FROM crm_links WHERE chatid=?", (chatid,)).fetchone() \
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='crm_links'").fetchone() else None
        if linked:
            rows = crm.request("leads", {"id": "eq." + linked[0], "select": campos})
            lead_crm = rows[0] if rows else None
    if not lead_crm and chatid:
        tail = _digitos(chatid.split("@")[0])[-8:]
        if len(tail) == 8:
            rows = crm.request("leads", {"or": "(telefone.like.*%s,whatsapp.like.*%s)" % (tail, tail), "select": campos,
                                         "status": "neq.descartado", "order": "updated_at.desc", "limit": "1"})
            lead_crm = rows[0] if rows else None
    return lead_crm


def jornada(c, crm, usuario, chatid=None, crm_id=None, agora=None):
    t0 = time.monotonic()
    agora = agora or datetime.now(BRT)
    hoje = agora.date()
    usuario = (usuario or "").strip().lower()
    chatid = chatid if isinstance(chatid, str) and re.fullmatch(r"[\w.-]+@(s\.whatsapp\.net|g\.us)", chatid or "") else None
    crm_id = crm_id if isinstance(crm_id, str) and re.fullmatch(r"[0-9a-f-]{36}", crm_id or "") else None
    if not chatid and not crm_id:
        raise ValueError("Lead inválido.")
    visiveis = grupos_catalogos.visible(c, usuario)
    if chatid and chatid.endswith("@g.us"):
        g = next((g for g in visiveis if g["chatid"] == chatid), None)
        if not g:
            raise ValueError("Grupo não disponível para este acesso.")
        chatid = g["lead_chatid"] if g["lead_chatid"].endswith("@s.whatsapp.net") else None
        if not chatid and not crm_id:
            raise ValueError("Grupo sem conversa da loja vinculada.")

    avisos = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_stores = pool.submit(_stores, crm)
        try:
            lead_crm = _acha_lead(c, crm, chatid, crm_id)
        except Exception:
            lead_crm = None
            avisos.append("CRM fora do ar: dados do lead no Supabase não vieram.")
        try:
            cats = f_stores.result()
        except Exception:
            cats = []

        fone = chatid.split("@")[0] if chatid else _digitos((lead_crm or {}).get("telefone") or (lead_crm or {}).get("whatsapp"))
        if not chatid and fone:
            tail = fone[-8:]
            r = c.execute("SELECT chatid FROM leads WHERE chatid LIKE ? AND chatid NOT LIKE '%@g.us' LIMIT 1",
                          ("%" + tail + "@s.whatsapp.net",)).fetchone() if len(tail) == 8 else None
            chatid = r[0] if r else None
        local = c.execute("SELECT * FROM leads WHERE chatid=?", (chatid,)).fetchone() if chatid else None
        if not local and not lead_crm:
            raise ValueError("Lead não encontrado.")
        grupo = next((g for g in visiveis if chatid and g["lead_chatid"] == chatid), None)
        nomes = [(lead_crm or {}).get("nome_loja") or "", local["nome"] if local else ""]
        # 1º o slug que o agente de catálogos anota no lead ("...catalogo/?loja=<slug>"), depois e-mail/telefone/nome
        slugs = re.findall(r"loja=([a-z0-9_-]+)", (lead_crm or {}).get("notas") or "")
        cat = next((x for sl in reversed(slugs) for x in cats if x.get("slug") == sl), None) or \
            (casa_catalogo(cats, lead_crm, fone, grupo["nome"] if grupo else "", nomes) if cats else None)
        if cat and not grupo:
            tail = _digitos(cat.get("whatsapp"))[-8:]
            grupo = next((g for g in visiveis if len(tail) == 8 and _digitos(g["lead_chatid"].split("@")[0])[-8:] == tail), None)

        lead_id = (lead_crm or {}).get("id")
        f_notas = pool.submit(crm.request, "interacoes", {"lead_id": "eq." + lead_id, "select": "tipo,conteudo,created_at",
                                                          "order": "created_at.asc", "limit": "500"}) if lead_id else None
        f_loja = pool.submit(_rpc, crm, "crm_jornada_loja", {"p_lead_id": lead_id, "p_slug": (cat or {}).get("slug")}) \
            if (lead_id or cat) else None
        try:
            notas = f_notas.result() if f_notas else []
        except Exception:
            notas = []
            avisos.append("Não consegui ler as interações do CRM.")
        loja, rpc_ok = {}, False
        if f_loja:
            try:
                loja = f_loja.result() or {}
                rpc_ok = True
            except Exception:
                loja = {}
        produtos_dia = None
        if f_loja and not rpc_ok and not cat:
            avisos.append("Função crm_jornada_loja ainda não aplicada no Supabase: catálogo achado só por e-mail/telefone/nome.")
        if not rpc_ok and cat:
            try:
                prods = crm.request("pl_catalog_products", {"store_id": "eq." + cat["id"], "select": "created_at", "limit": "3000"}) or []
                cont = {}
                for p in prods:
                    d = _data(p.get("created_at"))
                    if d:
                        cont[d.isoformat()] = cont.get(d.isoformat(), 0) + 1
                produtos_dia = [{"dia": k, "n": v} for k, v in sorted(cont.items())]
            except Exception:
                produtos_dia = None
            avisos.append("Provas, pagamentos e envios automáticos dependem da função crm_jornada_loja no Supabase "
                          "(ainda não aplicada); provas contadas pelas mensagens do grupo.")

    J = _Jornada(agora)
    responsavel = (local["responsavel"] if local and local["responsavel"] else None) or (lead_crm or {}).get("responsavel")
    pode_fin = usuario == "lucas" or (usuario == "dione" and responsavel == "Dione")
    store = (loja.get("store") if loja else None) or ({"id": cat["id"], "slug": cat["slug"], "nome": cat.get("display_name"),
                                                        "criado_em": cat.get("created_at"), "entregue_em": cat.get("entregue_em"),
                                                        "teste_30d": bool(cat.get("teste_30d"))} if cat else None)

    # ── lead ──
    if lead_crm and _iso(lead_crm.get("created_at")):
        J.ev(_iso(lead_crm["created_at"]), "lead", "lead", "Lead entrou no CRM",
             "Origem: " + lead_crm["fonte_oportunidade"] if lead_crm.get("fonte_oportunidade") else "", canal="crm")

    # ── mensagens ──
    stats = {"nossas": 0, "dele": 0, "nossas_grupo": 0, "dele_grupo": 0}
    resp_nossa, resp_dele = [], []
    ultima = None
    provas_grupo = {}

    def varre(cid, canal):
        nonlocal ultima
        pend_lead = pend_nos = None
        for m in c.execute("SELECT ts, from_me, tipo, texto, segundos FROM mensagens WHERE chatid=? AND excluida=0 ORDER BY ts", (cid,)):
            t = (m["texto"] or "").strip()
            dt = _dt(m["ts"])
            if PROVA.search(t):
                provas_grupo[dt.strftime("%Y-%m-%d")] = provas_grupo.get(dt.strftime("%Y-%m-%d"), 0) + 1
                continue
            if m["tipo"] in IGNORA:
                continue
            midia = m["tipo"] not in TEXTO
            texto = (_rotulo_midia(m["tipo"], m["segundos"]) + (" " + t if t and m["tipo"] != "AudioMessage" else "")) if midia else t
            quem = "nos" if m["from_me"] else "lead"
            J.ev(dt, "mensagens", "msg_" + quem, "Mensagem nossa" if m["from_me"] else "Mensagem do lead",
                 texto or "[mensagem vazia]", quem, canal, midia=midia)
            s = _seg(m["ts"])
            if m["from_me"]:
                stats["nossas" if canal == "privado" else "nossas_grupo"] += 1
                if canal == "privado":
                    if pend_lead is not None:
                        resp_nossa.append(s - pend_lead)
                        pend_lead = None
                    if pend_nos is None:
                        pend_nos = s
                for tipo, rot, rx in CLASSES:
                    if rx.search(t):
                        catg = "financeiro" if tipo in ("proposta", "pagamento", "cobranca_prazo") else "catalogo"
                        J.ev(dt, catg, tipo, rot, t.replace("\n", " "), "nos", canal, marco=True)
                        break
            else:
                stats["dele" if canal == "privado" else "dele_grupo"] += 1
                if canal == "privado":
                    if pend_nos is not None:
                        resp_dele.append(s - pend_nos)
                        pend_nos = None
                    if pend_lead is None:
                        pend_lead = s
            if ultima is None or dt >= ultima["dt"]:
                ultima = {"dt": dt, "quem": quem, "canal": canal, "texto": (texto or "")[:200]}

    if chatid:
        varre(chatid, "privado")
        p = c.execute("SELECT ts FROM mensagens WHERE chatid=? AND from_me=0 AND excluida=0 ORDER BY ts LIMIT 1", (chatid,)).fetchone()
        if p:
            J.ev(_dt(p[0]), "lead", "primeiro_contato", "Lead falou com a gente pela 1ª vez", "", "lead", "privado")
    if grupo:
        varre(grupo["chatid"], "grupo")

    # ── interações do CRM (notas e DMs do Instagram) ──
    for n in notas:
        dt = _iso(n.get("created_at"))
        tipo = n.get("tipo")
        if tipo == "nota":
            J.ev(dt, "notas", "nota", "Observação no CRM", n.get("conteudo") or "", "nos", "crm")
        elif tipo in ("dm_enviada", "follow_up"):
            J.ev(dt, "mensagens", "msg_nos", "DM enviada" if tipo == "dm_enviada" else "Follow-up enviado",
                 n.get("conteudo") or "", "nos", "instagram")
        elif tipo == "resposta":
            J.ev(dt, "mensagens", "msg_lead", "Resposta do lead (Instagram)", n.get("conteudo") or "", "lead", "instagram")
        elif dt:
            J.ev(dt, "notas", "interacao", "Interação: " + str(tipo), n.get("conteudo") or "", "nos", "crm")

    # ── etapas ──
    movs = []   # (dt, rótulo destino) para achar desde quando está na etapa atual
    dias_nota_mov = set()
    for linha in ((lead_crm or {}).get("notas") or "").splitlines():
        m = NOTA_DATADA.match(linha)
        if m:
            try:
                d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                continue
            texto = m.group(4)
        else:
            m = NOTA_CRM.match(linha)
            if not m:
                continue
            try:
                d = date(hoje.year, int(m.group(2)), int(m.group(1)))
                if d > hoje:
                    d = date(hoje.year - 1, d.month, d.day)
            except ValueError:
                continue
            texto = m.group(3)
        dt = _meio_dia(d)
        mv = MOVIDO.search(texto)
        if mv:
            destino = _rotulo_etapa(mv.group(1))
            J.ev(dt, "etapas", "etapa_auto", "Movido para " + mv.group(1).strip(), mv.group(2) or "",
                 "sistema", "crm", por="Rotina do funil", sem_hora=True, para=destino)
            if destino:
                movs.append((dt, destino))
                dias_nota_mov.add((dt.strftime("%Y-%m-%d"), destino))
        elif re.search(r"(?i)cat[aá]logo criado", texto):
            J.ev(dt, "catalogo", "catalogo_nota", "Catálogo criado (registro no lead)", texto, "sistema" if "agente" in texto else "nos",
                 "crm", por="Agente de catálogos" if "agente" in texto else None, sem_hora=True)
        elif re.search(r"(?i)convertido|pagou", texto):
            if pode_fin:
                J.ev(dt, "financeiro", "pagamento_nota", "Conversão registrada", texto, "sistema", "crm", sem_hora=True)
        elif re.search(r"(?i)stand-by chegou|retomar contato", texto):
            J.ev(dt, "etapas", "retomar", "Data de retomar o contato chegou", texto, "sistema", "crm", por="Rotina do funil", sem_hora=True)
        elif re.search(r"(?i)unificado com|j[aá] tem loja no ar", texto):
            J.ev(dt, "lead", "unificado", "Cadastro ajustado", texto, "sistema", "crm", sem_hora=True)
        else:
            J.ev(dt, "notas", "nota_lead", "Anotação no lead", texto, "nos", "crm", sem_hora=True)

    hist_jev = set()
    if chatid:
        try:
            rows = c.execute("SELECT de, para, ts, origem, por FROM etapa_historico WHERE chatid=? ORDER BY ts", (chatid,)).fetchall()
        except sqlite3.OperationalError:
            rows = []
        for r in rows:
            dt = _dt(r["ts"])
            if r["origem"] == "crm" and (dt.strftime("%Y-%m-%d"), r["para"]) in dias_nota_mov:
                movs.append((dt, r["para"]))
                continue   # a nota do lead já conta esse movimento, com o motivo
            quem = {"manual": "nos", "jev": "jev", "jev_sugestao": "nos", "crm": "sistema"}.get(r["origem"], "sistema")
            J.ev(dt, "etapas", "etapa_" + r["origem"], "%s → %s" % ((r["de"] or "—").title(), r["para"].title()),
                 ORIGEM_ROTULO.get(r["origem"], r["origem"]), quem, "crm" if r["origem"] == "crm" else "sistema",
                 por=r["por"] if r["origem"] in ("manual", "jev_sugestao") and r["por"] else None, de=r["de"], para=r["para"])
            movs.append((dt, r["para"]))
            if r["origem"] == "jev":
                hist_jev.add(r["para"])
        try:
            s = c.execute("SELECT * FROM etapa_sugestao WHERE chatid=? AND etapa IS NOT NULL", (chatid,)).fetchone()
        except sqlite3.OperationalError:
            s = None
        if s:
            conf = "%d%% de certeza" % round((s["conf"] or 0) * 100)
            if s["decisao"] == "auto":
                if s["etapa"] not in hist_jev:
                    J.ev(_dt(s["decidido_ts"] or s["criado_ts"]), "etapas", "jev_auto", "Jev moveu para " + s["etapa"].title(),
                         "%s · antes: %s" % (conf, (s["status_antes"] or "NOVO").title()), "jev", "sistema", para=s["etapa"])
                    movs.append((_dt(s["decidido_ts"] or s["criado_ts"]), s["etapa"]))
            else:
                J.ev(_dt(s["criado_ts"]), "etapas", "jev_sugestao", "Jev sugeriu " + s["etapa"].title(), conf, "jev", "sistema")
                if s["decisao"] in ("aplicada", "ignorada"):
                    J.ev(_dt(s["decidido_ts"]), "etapas", "jev_" + s["decisao"],
                         "Sugestão do Jev %s" % ("aplicada" if s["decisao"] == "aplicada" else "ignorada"),
                         s["etapa"].title(), "nos", "sistema", por=(s["decidido_por"] or "").title() or None)

    # ── responsável ──
    if chatid:
        for r in c.execute("SELECT responsavel, ts FROM conversas_atribuidas WHERE chatid=? ORDER BY ts", (chatid,)):
            J.ev(_dt(r["ts"]), "responsavel", "atribuido", "Atribuído a " + r["responsavel"], "", "nos", "sistema")
        for r in c.execute("SELECT responsavel, ts FROM atendimentos_iniciados WHERE chatid=? ORDER BY ts", (chatid,)):
            J.ev(_dt(r["ts"]), "responsavel", "primeiro_envio", r["responsavel"] + " fez o 1º envio", "", "nos", "privado", por=r["responsavel"])

    # ── catálogo ──
    onb = loja.get("onboarding") if loja else None
    regua = None
    if store:
        criado = _iso(store.get("criado_em"))
        J.ev(criado, "catalogo", "catalogo", "Catálogo criado", "provoulevou.com.br/catalogo/?loja=" + store["slug"], "sistema", "sistema",
             por=("Agente de catálogos" if (onb or {}).get("criado_por") == "agente" else (onb or {}).get("criado_por") or None))
        if onb and onb.get("tem_grupo") and not grupo:
            avisos.append("O catálogo tem grupo de WhatsApp, mas ele não está vinculado a este acesso.")
        entregue = _iso(store.get("entregue_em"))
        J.ev(entregue, "catalogo", "entregue", "Catálogo entregue ao lojista", "dia 1 da régua de 30 dias" if store.get("teste_30d") else "",
             "sistema", "sistema")
        for p in (loja.get("produtos_por_dia") if rpc_ok else produtos_dia) or []:
            d = _data(p.get("dia"))
            if d:
                J.ev(_meio_dia(d), "catalogo", "produtos", "%d produto%s cadastrado%s" % (p["n"], "s" if p["n"] != 1 else "", "s" if p["n"] != 1 else ""),
                     "", "lead", "sistema", sem_hora=True, n=p["n"])
        envios = (loja.get("envios") or []) if rpc_ok else []
        for e in envios:
            rot = ROTULO_ENVIO.get(e.get("etapa"), "Dia %s" % e.get("dia"))
            st = e.get("status")
            if st == "enviado":
                J.ev(_iso(e.get("enviado_em")) or _meio_dia(_data(e.get("agendado_para")) or hoje), "catalogo", "envio_auto",
                     "Mensagem automática enviada · " + rot, e.get("texto") or "", "sistema", "grupo",
                     texto=e.get("texto") or "", status=st)
            elif st in ("erro", "pulado"):
                d = _data(e.get("agendado_para"))
                J.ev(_iso(e.get("enviado_em")) or (_meio_dia(d) if d else _iso(e.get("criado_em"))), "catalogo", "envio_" + st,
                     ("Mensagem automática falhou · " if st == "erro" else "Mensagem automática pulada · ") + rot,
                     e.get("erro") or "", "sistema", "grupo", texto=e.get("texto") or "", status=st)
        if store.get("teste_30d"):
            regua = _regua(store, envios, hoje)

    provas = (loja.get("provas_por_dia") or []) if rpc_ok else [{"dia": k, "n": v} for k, v in sorted(provas_grupo.items())]
    total_provas = 0
    for p in provas:
        d = _data(p.get("dia"))
        if d:
            total_provas += p["n"]
            J.ev(_meio_dia(d), "catalogo", "provas", "%d prova%s no catálogo" % (p["n"], "s" if p["n"] != 1 else ""),
                 "" if rpc_ok else "contadas pelos avisos no grupo", "lead", "sistema", por="Clientes da loja", sem_hora=True, n=p["n"])
    if lead_crm and lead_crm.get("teste_gratis_em"):
        d = _data(lead_crm["teste_gratis_em"])
        if d:
            J.ev(_meio_dia(d), "catalogo", "teste_gratis", "Início do teste grátis (data no CRM)", "", "nos", "crm", sem_hora=True)

    # ── financeiro ──
    conta = loja.get("conta") if loja else None
    if pode_fin and rpc_ok:
        for co in loja.get("cobrancas") or []:
            tipo = TIPO_COBRANCA.get(co.get("tipo") or "", co.get("tipo") or "PIX")
            det = " · ".join(x for x in [co.get("plano") or "", ("%s provas" % co["fotos"]) if co.get("fotos") else "",
                                         _moeda(co.get("valor")), "status: " + str(co.get("status"))] if x)
            J.ev(_iso(co.get("criado_em")), "financeiro", "cobranca", "Cobrança gerada (%s)" % tipo, det, "sistema", "sistema")
            if co.get("aprovado_em") or co.get("status") == "approved":
                J.ev(_iso(co.get("aprovado_em")) or _iso(co.get("criado_em")), "financeiro", "pago", "Pagamento aprovado (%s)" % tipo,
                     _moeda(co.get("valor")), "lead", "sistema")
        for pg in loja.get("pagamentos") or []:
            d = _data(pg.get("data"))
            J.ev(_meio_dia(d) if d else _iso(pg.get("criado_em")), "financeiro", "pagamento", "Pagamento recebido",
                 " · ".join(x for x in [_moeda(pg.get("valor")), pg.get("tipo") or "", pg.get("descricao") or ""] if x),
                 "lead", "sistema", sem_hora=bool(d))
    if chatid:
        pf = c.execute("SELECT plano, valor_centavos, fechado_em FROM planos_fechados WHERE chatid=?", (chatid,)).fetchone()
        if pf and (pode_fin or usuario == "dione"):
            J.ev(_iso(pf["fechado_em"]), "financeiro", "plano", "Plano fechado",
                 "%s · %s/mês" % (pf["plano"], _moeda(pf["valor_centavos"] / 100)), "nos", "crm")

    # ── tarefas do próprio login que citam a loja ──
    dono = {"lucas": "Lucas", "dione": "Dione"}.get(usuario)
    chave_nome = max((_core(n) for n in nomes if n), key=len, default="")
    proximos = []
    if dono and len(chave_nome) >= 5:
        try:
            trs = c.execute("SELECT titulo, notas, prazo, criada_em, feita_em, estado FROM tarefas WHERE dono=?", (dono,)).fetchall()
        except sqlite3.OperationalError:
            trs = []
        for t in trs:
            if chave_nome not in _core((t["titulo"] or "") + " " + (t["notas"] or "")):
                continue
            J.ev(_iso(t["criada_em"]), "notas", "tarefa", "Tarefa criada: " + t["titulo"], ("prazo " + t["prazo"]) if t["prazo"] else "", "nos", "crm", por=dono)
            if t["feita_em"]:
                J.ev(_iso(t["feita_em"]), "notas", "tarefa_feita", "Tarefa concluída: " + t["titulo"], "", "nos", "crm", por=dono)
            elif t["prazo"] and _data(t["prazo"]) and _data(t["prazo"]) >= hoje:
                proximos.append({"data": t["prazo"], "titulo": "Tarefa: " + t["titulo"], "detalhe": "", "tipo": "tarefa"})

    # ── resumo ──
    J.eventos.sort(key=lambda e: e["ts"])
    status_rot = etapas.local_do_slug(lead_crm["status"]) if lead_crm and lead_crm.get("status") else \
        ((local["status"] if local else None) or "NOVO")
    desde = max((dt for dt, para in movs if para == status_rot), default=None)
    inicio = min([x for x in [_iso((lead_crm or {}).get("created_at")),
                              _iso(J.eventos[0]["ts"]) if J.eventos else None] if x], default=None)
    if lead_crm and lead_crm.get("retomar_em") and _data(lead_crm["retomar_em"]) and _data(lead_crm["retomar_em"]) >= hoje:
        proximos.append({"data": lead_crm["retomar_em"], "titulo": "Retomar o contato (Stand-by)", "detalhe": "", "tipo": "etapa"})
    if regua:
        for m in regua["mensagens"]:
            if m["status"] in ("agendado", "previsto") and m["data"] and m["data"] >= hoje.isoformat():
                proximos.append({"data": m["data"], "titulo": "Mensagem automática · " + m["rotulo"],
                                 "detalhe": "agendada" if m["status"] == "agendado" else "prevista pela régua", "tipo": "envio"})
    elif store and status_rot in ("EM TESTE", "AGUARDANDO DADOS") and _iso(store.get("criado_em")):
        fim = (_iso(store["criado_em"]).date() + timedelta(days=7))
        if fim >= hoje:
            proximos.append({"data": fim.isoformat(), "titulo": "Fim do teste de 7 dias", "detalhe": "a rotina do funil move para Teste parado", "tipo": "etapa"})
    proximos.sort(key=lambda p: p["data"])

    nome = (lead_crm or {}).get("nome_loja") or (local["nome"] if local else "") or fone
    resumo = {
        "dias_desde_entrada": (hoje - inicio.date()).days if inicio else None,
        "entrou_em": inicio.strftime("%d/%m/%Y") if inicio else None,
        "etapa": status_rot,
        "etapa_desde": desde.strftime("%d/%m/%Y") if desde else None,
        "dias_na_etapa": (hoje - desde.date()).days if desde else None,
        "responsavel": responsavel,
        "msgs_nossas": stats["nossas"], "msgs_dele": stats["dele"],
        "msgs_nossas_grupo": stats["nossas_grupo"], "msgs_dele_grupo": stats["dele_grupo"],
        "resposta_nossa_media": _fmt_dur(sum(resp_nossa) / len(resp_nossa)) if resp_nossa else None,
        "resposta_nossa_mediana": _fmt_dur(_mediana(resp_nossa)),
        "resposta_dele_mediana": _fmt_dur(_mediana(resp_dele)),
        "respostas_medidas": len(resp_nossa),
        "ultima_interacao": {"quando": ultima["dt"].strftime("%d/%m/%Y %H:%M"), "quem": ultima["quem"], "canal": ultima["canal"],
                             "texto": ultima["texto"], "ha_dias": (hoje - ultima["dt"].date()).days} if ultima else None,
        "provas": total_provas,
        "tentativas": (lead_crm or {}).get("tentativas"),
        "motivo_perda": (lead_crm or {}).get("motivo_perda") if status_rot == "PERDIDO" else None,
        "conta": conta if pode_fin else None,
        "financeiro_oculto": not pode_fin,
        "proximos": proximos[:8],
    }
    return {
        "lead": {"nome": nome, "fone": fone, "chatid": chatid, "crm_id": lead_id, "grupo": {"chatid": grupo["chatid"], "nome": grupo["nome"]} if grupo else None,
                 "catalogo": {"slug": store["slug"], "link": "provoulevou.com.br/catalogo/?loja=" + store["slug"],
                              "teste_30d": bool(store.get("teste_30d"))} if store else None},
        "resumo": resumo,
        "regua": regua,
        "eventos": J.eventos,
        "categorias": list(CATEGORIAS),
        "fontes": {"rpc": rpc_ok, "avisos": avisos},
        "ms": round((time.monotonic() - t0) * 1000),
    }


def _regua(store, envios, hoje):
    entrega = _data(store.get("entregue_em"))
    por_etapa = {e.get("etapa"): e for e in envios}
    msgs = []
    for dia, etapa, rot in REGUA:
        e = por_etapa.get(etapa) or next((x for x in envios if x.get("dia") == dia), None)
        data = (e or {}).get("agendado_para") or ((entrega + timedelta(days=dia - 1)).isoformat() if entrega else None)
        msgs.append({"dia": dia, "etapa": etapa, "rotulo": rot, "data": str(data)[:10] if data else None,
                     "status": (e or {}).get("status") or ("aguardando entrega" if not entrega else
                                                           "sem registro" if data and str(data)[:10] < hoje.isoformat() else "previsto"),
                     "enviado_em": (_iso(e["enviado_em"]).strftime("%d/%m/%Y %H:%M") if e and _iso(e.get("enviado_em")) else None),
                     "texto": (e or {}).get("texto") or "", "erro": (e or {}).get("erro") or ""})
    dia_atual = (hoje - entrega).days + 1 if entrega else None
    fase = None
    if dia_atual is not None:
        fase = "montagem" if dia_atual <= 21 else "teste" if dia_atual <= 28 else "encerrado"
    return {"entregue_em": entrega.strftime("%d/%m/%Y") if entrega else None, "dia_atual": dia_atual, "fase": fase,
            "teste_de": (entrega + timedelta(days=21)).strftime("%d/%m") if entrega else None,
            "teste_ate": (entrega + timedelta(days=27)).strftime("%d/%m") if entrega else None,
            "mensagens": msgs}


def catalogos_30d(crm, usuario, agora=None):
    """Visão geral: catálogos na régua de 30 dias, dia atual de cada um e a próxima mensagem."""
    hoje = (agora or datetime.now(BRT)).date()
    try:
        itens, rpc_ok = _rpc(crm, "crm_jornada_catalogos_30d", {}) or [], True
    except Exception:
        rpc_ok = False
        itens = [{"store_id": s["id"], "slug": s["slug"], "nome": s.get("display_name"), "criado_em": s.get("created_at"),
                  "entregue_em": s.get("entregue_em"), "lead_id": None, "responsavel": None, "proximo": None}
                 for s in _stores(crm) if s.get("teste_30d")]
    out = []
    for it in itens:
        entrega = _data(it.get("entregue_em"))
        dia = (hoje - entrega).days + 1 if entrega else None
        prox = it.get("proximo")
        if prox:
            prox = {"dia": prox.get("dia"), "rotulo": ROTULO_ENVIO.get(prox.get("etapa"), "Dia %s" % prox.get("dia")),
                    "data": str(prox.get("agendado_para") or "")[:10], "status": "agendado"}
        elif entrega:
            d, _, rot = next(((d, e, r) for d, e, r in REGUA if d >= (dia or 0)), (None, None, None))
            prox = {"dia": d, "rotulo": rot, "data": (entrega + timedelta(days=d - 1)).isoformat(), "status": "previsto"} if d else None
        out.append({"slug": it.get("slug"), "nome": it.get("nome"), "lead_id": it.get("lead_id"), "responsavel": it.get("responsavel"),
                    "entregue_em": entrega.strftime("%d/%m/%Y") if entrega else None, "dia_atual": dia,
                    "fase": None if dia is None else ("montagem" if dia <= 21 else "teste" if dia <= 28 else "encerrado"),
                    "produtos": it.get("produtos"), "provas": it.get("provas"), "enviados": it.get("enviados"),
                    "erros": it.get("erros"), "proximo": prox})
    return {"itens": out, "rpc": rpc_ok}
