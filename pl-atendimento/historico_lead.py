"""Linha do tempo de um lead pro CRM: quando entrou, quando o catálogo foi criado,
quando mandamos acesso / cobrança / proposta, provas no grupo, plano fechado e notas.

Tudo sai do que já existe: mensagens do painel (privado + grupo do catálogo, as
duas sincronizadas em `mensagens`), grupos_catalogos, planos_fechados e, no
Supabase, leads / pl_catalog_stores / interacoes. Nada é gravado aqui."""
import re
import unicodedata
from datetime import datetime, timezone, timedelta

import grupos_catalogos

BRT = timezone(timedelta(hours=-3))

# (tipo, rótulo, regex) — primeira que bater vence. Só mensagens NOSSAS.
CLASSES = [
    ("acesso", "Acesso ao painel enviado", re.compile(r"catalogo/painel|🔑", re.I)),
    ("grupo", "Grupo do catálogo aberto", re.compile(r"canal direto entre voc", re.I)),
    ("cobranca_cadastro", "Cobrança de cadastro dos produtos",
     re.compile(r"sem produtos|dificuldade pra cadastrar|cadastr\w* (os |seus )?produtos", re.I)),
    ("pagamento", "Link de pagamento enviado", re.compile(r"link (de|pra|para) (o )?pagamento|mercadopago|mpago\.la|pix copia", re.I)),
    ("proposta", "Proposta de plano enviada",
     re.compile(r"plano indicado|podemos ativar|posso ativar|r\$\s?\d+[.,]?\d*\s*(/|por)\s*m[eê]s", re.I)),
    ("cobranca_prazo", "Cobrança de fim do teste",
     re.compile(r"(teste|per[ií]odo)( gr[aá]tis| de teste)?.{0,40}(acab|termin|venc|encerr|fim)", re.I)),
]
PROVA = re.compile(r"novo cliente provou", re.I)


def _dt(ms):
    ms = int(ms or 0)
    if ms and ms < 100000000000:        # veio em segundos
        ms *= 1000
    return datetime.fromtimestamp(ms / 1000, BRT)


def _iso(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(BRT)
    except (TypeError, ValueError):
        return None


def _digitos(v):
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) > 11 and d.startswith("55"):
        d = d[2:]
    return d.lstrip("0")


def _core(s):
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = re.sub(r"[^a-z0-9]", "", "".join(ch for ch in s if unicodedata.category(ch) != "Mn"))
    for pre in ("provoulevou", "oticas", "otica", "opticas", "optica"):
        if s.startswith(pre):
            s = s[len(pre):]
    return s


def _evento(dt, tipo, titulo, detalhe="", onde=""):
    return {"ts": dt.isoformat(), "quando": dt.strftime("%d/%m/%Y %H:%M"),
            "tipo": tipo, "titulo": titulo, "detalhe": (detalhe or "")[:220], "onde": onde}


def _parecido(a, b):
    a, b = _core(a), _core(b)
    return len(a) >= 4 and len(b) >= 4 and (a == b or (min(len(a), len(b)) >= 8 and (a in b or b in a)))


def _catalogo(crm, lead_crm, fone, grupo_nome, nomes):
    """Acha o catálogo do lead: e-mail, telefone, nome do grupo e, por fim, nome do lead."""
    try:
        cats = crm.request("pl_catalog_stores", {"select": "id,slug,display_name,owner_email,whatsapp,created_at"}) or []
    except Exception:
        return None
    return casa_catalogo(cats, lead_crm, fone, grupo_nome, nomes)


def casa_catalogo(cats, lead_crm, fone, grupo_nome, nomes):
    """Mesmo critério de _catalogo, sobre uma lista de catálogos já carregada."""
    email = ((lead_crm or {}).get("email") or "").strip().lower()
    if email:
        c = next((c for c in cats if (c.get("owner_email") or "").strip().lower() == email), None)
        if c:
            return c
    tail = _digitos(fone)[-8:]
    if len(tail) == 8:
        c = next((c for c in cats if _digitos(c.get("whatsapp"))[-8:] == tail), None)
        if c:
            return c
    for nome in [re.sub(r"(?i)^provou levou\s*&\s*", "", grupo_nome or "")] + nomes:
        nome = re.sub(r"\(.*?\)", "", nome or "")      # "Ótica X (Fulana)" -> "Ótica X"
        c = next((c for c in cats if _parecido(c.get("display_name"), nome)), None)
        if c:
            return c
    return None


def historico(c, crm, usuario, chatid=None, crm_id=None):
    chatid = chatid if isinstance(chatid, str) and chatid.endswith("@s.whatsapp.net") else None
    crm_id = crm_id if isinstance(crm_id, str) and re.fullmatch(r"[0-9a-f-]{36}", crm_id or "") else None
    if not chatid and not crm_id:
        raise ValueError("Lead inválido.")
    eventos = []

    lead_crm = None
    if crm_id:
        try:
            rows = crm.request("leads", {"id": "eq." + crm_id,
                                         "select": "id,nome_loja,telefone,whatsapp,email,created_at,status,responsavel"})
            lead_crm = rows[0] if rows else None
        except Exception:
            lead_crm = None
    if not lead_crm and chatid:
        tail = _digitos(chatid.split("@")[0])[-8:]
        try:
            rows = crm.request("leads", {"or": "(telefone.like.*%s,whatsapp.like.*%s)" % (tail, tail),
                                         "select": "id,nome_loja,telefone,whatsapp,email,created_at,status,responsavel",
                                         "status": "neq.descartado", "limit": "1"}) if len(tail) == 8 else []
            lead_crm = rows[0] if rows else None
        except Exception:
            lead_crm = None
    fone = chatid.split("@")[0] if chatid else _digitos((lead_crm or {}).get("telefone") or (lead_crm or {}).get("whatsapp"))
    if not chatid and fone:
        tail = fone[-8:]
        r = c.execute("SELECT chatid FROM leads WHERE chatid LIKE ? AND chatid NOT LIKE '%@g.us' LIMIT 1",
                      ("%" + tail + "@s.whatsapp.net",)).fetchone()
        chatid = r["chatid"] if r else None

    # grupo do catálogo (respeita o que cada usuário pode ver)
    grupo = None
    visiveis = grupos_catalogos.visible(c, usuario)
    if chatid:
        grupo = next((g for g in visiveis if g["lead_chatid"] == chatid), None)

    if lead_crm and _iso(lead_crm.get("created_at")):
        eventos.append(_evento(_iso(lead_crm["created_at"]), "lead", "Lead entrou no CRM"))

    nome_painel = c.execute("SELECT nome FROM leads WHERE chatid=?", (chatid,)).fetchone() if chatid else None
    nomes = [(lead_crm or {}).get("nome_loja") or "", nome_painel["nome"] if nome_painel else ""]
    cat = _catalogo(crm, lead_crm, fone, grupo["nome"] if grupo else "", nomes)
    if cat and not grupo:
        # grupo ligado a outro número da mesma loja: acha pelo telefone ou nome do catálogo
        tail = _digitos(cat.get("whatsapp"))[-8:]
        grupo = next((g for g in visiveis if len(tail) == 8 and _digitos(g["lead_chatid"].split("@")[0])[-8:] == tail), None) or             next((g for g in visiveis if _parecido(re.sub(r"(?i)^provou levou\s*&\s*", "", g["nome"]), cat.get("display_name"))), None)
    if cat and _iso(cat.get("created_at")):
        eventos.append(_evento(_iso(cat["created_at"]), "catalogo", "Catálogo criado",
                               "provoulevou.com.br/catalogo/?loja=" + cat["slug"]))

    def varre(cid, onde):
        primeira_nossa = primeira_cliente = None
        provas = []
        for m in c.execute("SELECT ts, from_me, texto FROM mensagens WHERE chatid=? AND excluida=0 ORDER BY ts", (cid,)):
            t = m["texto"] or ""
            if PROVA.search(t):
                provas.append(m["ts"])
                continue
            if m["from_me"]:
                if primeira_nossa is None:
                    primeira_nossa = m["ts"]
                for tipo, rot, rx in CLASSES:
                    if rx.search(t):
                        eventos.append(_evento(_dt(m["ts"]), tipo, rot, t.strip().replace("\n", " "), onde))
                        break
            elif primeira_cliente is None:
                primeira_cliente = m["ts"]
        return primeira_nossa, primeira_cliente, provas

    ult_cliente = None
    if chatid:
        pn, pc, _ = varre(chatid, "privado")
        if pn:
            eventos.append(_evento(_dt(pn), "contato", "Primeira mensagem nossa", "", "privado"))
        if pc:
            eventos.append(_evento(_dt(pc), "resposta", "Cliente respondeu pela 1ª vez", "", "privado"))
        r = c.execute("SELECT ts, texto FROM mensagens WHERE chatid=? AND from_me=0 AND excluida=0 ORDER BY ts DESC LIMIT 1",
                      (chatid,)).fetchone()
        if r:
            ult_cliente = {"ts": _dt(r["ts"]), "texto": (r["texto"] or "")[:200], "onde": "privado"}
    provas = []
    if grupo:
        _, _, provas = varre(grupo["chatid"], "grupo")
        r = c.execute("SELECT ts, texto FROM mensagens WHERE chatid=? AND from_me=0 AND excluida=0 ORDER BY ts DESC LIMIT 1",
                      (grupo["chatid"],)).fetchone()
        if r and (not ult_cliente or _dt(r["ts"]) > ult_cliente["ts"]):
            ult_cliente = {"ts": _dt(r["ts"]), "texto": (r["texto"] or "")[:200], "onde": "grupo"}
        if provas:
            eventos.append(_evento(_dt(provas[0]), "prova", "1ª prova no catálogo", "", "grupo"))
            if len(provas) > 1:
                eventos.append(_evento(_dt(provas[-1]), "prova", "Última prova no catálogo",
                                       "%d provas no total" % len(provas), "grupo"))

    if chatid:
        pf = c.execute("SELECT plano, valor_centavos, fechado_em FROM planos_fechados WHERE chatid=?", (chatid,)).fetchone()
        if pf and _iso(pf["fechado_em"]):
            eventos.append(_evento(_iso(pf["fechado_em"]), "plano", "Plano fechado",
                                   "%s · R$ %s/mês" % (pf["plano"], ("%.2f" % (pf["valor_centavos"] / 100)).replace(".", ","))))

    lead_id = crm_id or ((lead_crm or {}).get("id"))
    if lead_id:
        try:
            notas = crm.request("interacoes", {"lead_id": "eq." + lead_id, "select": "tipo,conteudo,created_at",
                                               "order": "created_at.asc"}) or []
        except Exception:
            notas = []
        for n in notas:
            if _iso(n.get("created_at")):
                eventos.append(_evento(_iso(n["created_at"]), "nota", "Nota no CRM" if n.get("tipo") == "nota" else "Interação: " + str(n.get("tipo")),
                                       n.get("conteudo") or ""))

    # antes do catálogo existir, preço na conversa é apresentação, não cobrança
    cat_ts = _iso(cat["created_at"]).isoformat() if cat and _iso(cat.get("created_at")) else None
    if cat_ts:
        for e in eventos:
            if e["tipo"] in ("proposta", "cobranca_prazo", "cobranca_cadastro", "pagamento") and e["ts"] < cat_ts:
                e["tipo"], e["titulo"] = "apresentacao", "Preço apresentado (antes do catálogo)"
    eventos.sort(key=lambda e: e["ts"])
    ultimo = {}
    for e in eventos:
        ultimo[e["tipo"]] = e["quando"]
    return {
        "resumo": {
            "catalogo_criado": ultimo.get("catalogo"),
            "catalogo_link": ("provoulevou.com.br/catalogo/?loja=" + cat["slug"]) if cat else None,
            "acesso_enviado": next((e["quando"] for e in eventos if e["tipo"] == "acesso"), None),
            "ultima_cobranca": max((e for e in eventos if e["tipo"] in ("cobranca_cadastro", "cobranca_prazo", "proposta", "pagamento")),
                                   key=lambda e: e["ts"], default={}).get("quando"),
            "provas": len(provas),
            "ultima_prova": _dt(provas[-1]).strftime("%d/%m/%Y %H:%M") if provas else None,
            "ultima_fala_cliente": {"quando": ult_cliente["ts"].strftime("%d/%m/%Y %H:%M"), "texto": ult_cliente["texto"],
                                    "onde": ult_cliente["onde"]} if ult_cliente else None,
        },
        "grupo": {"chatid": grupo["chatid"], "nome": grupo["nome"]} if grupo else None,
        "fone": fone,
        "catalogo_whatsapp": (cat or {}).get("whatsapp"),
        "eventos": list(reversed(eventos)),   # mais recente primeiro
    }
