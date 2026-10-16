"""Visão geral da Jornada (tela inicial da aba Jornada do lead): o funil inteiro e "o que fazer hoje".

Tudo em lote (nada por lead), pra caber em < 2 s com ~1.500 conversas:
  painel.db -> leads, mensagens (agregadas por conversa), grupos_catalogos, etapa_historico, etapa_sugestao,
               planos_fechados, crm_links
  Supabase  -> leads do CRM (anon, cache de 60 s) e, pela RPC crm_jornada_visao (PL_IA_KEY, cache de 60 s),
               catálogos com produtos, provas, envios automáticos (segunda chance / régua 30 dias) e cobrança pendente.
Visibilidade: Lucas vê tudo; Dione vê os leads dela + os sem responsável."""
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, date

import etapas
from historico_lead import BRT, _iso, _digitos
from jornada import _rpc, _stores, _rotulo_etapa, MOVIDO, NOTA_DATADA, ROTULO_ENVIO

ENCERRADO = {"CONVERTIDO", "PERDIDO"}
# a partir daqui entra em "Para fazer hoje": esperando resposta (até 7 dias), retomar Stand-by, cobrança/proposta,
# teste parado, catálogo sem produto, segunda chance sem resposta e follow-up (3 a 7 dias sem interação)
PARA_HOJE = 450
# leads só do CRM (sem conversa no painel) entram a partir destas etapas; "novo"/"respondeu" sem conversa é
# lista fria de Instagram e "perdida" sem conversa não tem o que fazer.
CRM_SO_A_PARTIR = {"interessado", "testando", "testando_ativo", "passou_prazo", "proposta_enviada",
                   "aguardando_pagamento", "fechou", "stand_by"}
CAMPOS_CRM = "id,nome_loja,telefone,whatsapp,status,responsavel,created_at,updated_at,teste_gratis_em,retomar_em,motivo_perda,notas"
SEM_FALA = ("ReactionMessage", "PinInChatMessage")
_CACHE = {"crm": (0.0, None), "cat": (0.0, None, False)}


def _crm_leads(crm):
    at, data = _CACHE["crm"]
    if data is not None and time.monotonic() - at < 60:
        return data

    def pagina(off):
        return crm.request("leads", {"select": CAMPOS_CRM, "order": "id", "limit": 1000, "offset": off}) or []
    data, off = [], 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            lotes = list(pool.map(pagina, range(off, off + 4000, 1000)))
            for l in lotes:
                data.extend(l)
            if len(lotes[-1]) < 1000:
                break
            off += 4000
    _CACHE["crm"] = (time.monotonic(), data)
    return data


def _catalogos(crm):
    at, data, ok = _CACHE["cat"]
    if data is not None and time.monotonic() - at < 60:
        return data, ok
    try:
        data, ok = _rpc(crm, "crm_jornada_visao", {}) or [], True
    except Exception:
        # sem a RPC: só o que a anon lê (sem produtos/provas/envios)
        data = [{"store_id": s["id"], "slug": s["slug"], "nome": s.get("display_name"), "lead_id": None,
                 "fone8": _digitos(s.get("whatsapp"))[-8:], "email": (s.get("owner_email") or "").strip().lower(),
                 "criado_em": s.get("created_at"), "entregue_em": s.get("entregue_em"), "teste_30d": bool(s.get("teste_30d"))}
                for s in _stores(crm)]
        ok = False
    _CACHE["cat"] = (time.monotonic(), data, ok)
    return data, ok


def _seg(ts):
    ts = int(ts or 0)
    return ts // 1000 if ts > 100000000000 else ts


def _quando(seg):
    return datetime.fromtimestamp(seg, BRT) if seg else None


def _ultimo_movimento(notas):
    """[(date, rótulo destino)] dos 'DD/MM/AAAA: movido para X' das notas do lead."""
    out = []
    for linha in (notas or "").splitlines():
        m = NOTA_DATADA.match(linha)
        if not m:
            continue
        mv = MOVIDO.search(m.group(4))
        if not mv:
            continue
        try:
            out.append((date(int(m.group(3)), int(m.group(2)), int(m.group(1))), _rotulo_etapa(mv.group(1))))
        except ValueError:
            pass
    return out


def _horas(seg):
    h = seg / 3600
    return "%d min" % max(1, round(seg / 60)) if h < 1 else ("%d h" % round(h) if h < 48 else "%d dias" % round(h / 24))


def visao(c, crm, usuario, agora=None):
    t0 = time.monotonic()
    agora = agora or datetime.now(BRT)
    hoje, agora_s = agora.date(), int(agora.timestamp())
    u = (usuario or "").strip().lower()
    if u not in ("lucas", "dione"):
        raise PermissionError("Login sem acesso à visão geral.")
    avisos = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        f_crm, f_cat = pool.submit(_crm_leads, crm), pool.submit(_catalogos, crm)

        # ── painel.db, tudo agregado ──
        locais = c.execute("SELECT chatid, fone, nome, status, responsavel, ultimo_de, ultimo_ts FROM leads "
                           "WHERE chatid LIKE '%@s.whatsapp.net' AND COALESCE(oculto,0)=0 AND NOT EXISTS ("
                           "SELECT 1 FROM mensagens m WHERE m.chatid=leads.chatid AND m.from_me=0 "
                           "AND m.texto LIKE 'Olá! Tive um problema ao usar o provador%')").fetchall()
        sem_fala = ",".join("'%s'" % x for x in SEM_FALA)
        agg = {r[0]: r for r in c.execute(
            "SELECT chatid, MAX(ts), MAX(CASE WHEN from_me=0 THEN ts END), MAX(CASE WHEN from_me=1 THEN ts END), "
            "SUM(from_me=1), SUM(from_me=0), MIN(ts) FROM mensagens WHERE excluida=0 AND COALESCE(tipo,'') NOT IN (" + sem_fala + ") "
            "AND COALESCE(texto,'') NOT LIKE '%novo cliente provou%' GROUP BY chatid")}
        ultima_txt = {r[0]: r for r in c.execute(
            "SELECT m.chatid, m.from_me, m.tipo, m.texto, m.segundos FROM mensagens m JOIN ("
            "SELECT chatid, MAX(ts) ts FROM mensagens WHERE excluida=0 AND COALESCE(tipo,'') NOT IN (" + sem_fala + ") "
            "AND COALESCE(texto,'') NOT LIKE '%novo cliente provou%' GROUP BY chatid) x ON x.chatid=m.chatid AND x.ts=m.ts")}
        provas_grupo = {r[0]: r[1] for r in c.execute(
            "SELECT chatid, COUNT(*) FROM mensagens WHERE excluida=0 AND texto LIKE '%novo cliente provou%' GROUP BY chatid")}
        grupos = {r[1]: r[0] for r in c.execute("SELECT chatid, lead_chatid FROM grupos_catalogos")}
        links = {r[0]: r[1] for r in c.execute("SELECT chatid, lead_id FROM crm_links")}
        hist = {}
        try:
            for r in c.execute("SELECT chatid, para, MAX(ts) FROM etapa_historico GROUP BY chatid, para"):
                hist[(r[0], r[1])] = r[2]
        except Exception:
            pass
        try:
            jev = {r[0]: r[1] for r in c.execute("SELECT chatid, etapa FROM etapa_sugestao WHERE decisao IS NULL AND etapa IS NOT NULL")}
        except Exception:
            jev = {}
        try:
            sug_status = {r[0]: r[1] for r in c.execute("SELECT chatid, status_antes FROM etapa_sugestao WHERE decisao IS NULL AND etapa IS NOT NULL")}
        except Exception:
            sug_status = {}
        planos = {r[0]: (r[1], r[2]) for r in c.execute("SELECT chatid, plano, valor_centavos FROM planos_fechados")}

        try:
            crm_leads = f_crm.result()
        except Exception:
            crm_leads = []
            avisos.append("CRM fora do ar: etapas e responsáveis vêm só do painel.")
        try:
            cats, rpc_ok = f_cat.result()
        except Exception:
            cats, rpc_ok = [], False
    if not rpc_ok:
        avisos.append("Função crm_jornada_visao ainda não aplicada no Supabase: sem produtos, provas e envios automáticos.")

    por_id = {l["id"]: l for l in crm_leads}
    por_fone = {}
    for l in crm_leads:
        for campo in ("telefone", "whatsapp"):
            t = _digitos(l.get(campo))[-8:]
            if len(t) == 8 and l.get("status") != "descartado":
                por_fone.setdefault(t, l)
    cat_lead = {x["lead_id"]: x for x in cats if x.get("lead_id")}
    cat_slug = {x["slug"]: x for x in cats}
    cat_fone = {x["fone8"]: x for x in cats if len(x.get("fone8") or "") == 8}
    cat_email = {x["email"]: x for x in cats if x.get("email")}

    def acha_cat(lc, fone8):
        if lc:
            if lc["id"] in cat_lead:
                return cat_lead[lc["id"]]
            for sl in reversed(re.findall(r"loja=([a-z0-9_-]+)", lc.get("notas") or "")):
                if sl in cat_slug:
                    return cat_slug[sl]
        return cat_fone.get(fone8) or cat_email.get(((lc or {}).get("email") or "").lower())

    itens, usados = [], set()

    def monta(chatid, local, lc):
        fone = (local["fone"] if local else None) or (lc or {}).get("telefone") or (lc or {}).get("whatsapp") or ""
        fone8 = _digitos(fone)[-8:]
        if lc and lc.get("status"):
            etapa = etapas.local_do_slug(lc["status"])
        else:
            etapa = (local["status"] if local else None) or "NOVO"
            etapa = etapa if etapa in etapas.STATUS else etapas.LOCAL_LEGADO.get(etapa, "NOVO")
        resp = ((local["responsavel"] if local else None) or (lc or {}).get("responsavel") or "").strip() or None
        if u == "dione" and resp not in (None, "Dione"):
            return None
        a = agg.get(chatid) if chatid else None
        g = grupos.get(chatid) if chatid else None
        ag = agg.get(g) if g else None
        # última interação: privado ou grupo (sem os avisos de prova)
        cand = []
        if a:
            cand.append((_seg(a[1]), "privado", chatid))
        if ag:
            cand.append((_seg(ag[1]), "grupo", g))
        ult = max(cand) if cand else None
        ultima = None
        if ult:
            t = ultima_txt.get(ult[2])
            ultima = {"ts": ult[0], "canal": ult[1], "quem": "nos" if t and t[1] else "lead",
                      "texto": " ".join(((t[3] or "").strip() if t and (t[3] or "").strip() else
                                         "[%s]" % (t[2] or "mídia").replace("Message", "").lower() if t else "").split())[:70]}
        aprox = False
        if not ultima and lc and _iso(lc.get("updated_at")):
            ultima = {"ts": int(_iso(lc["updated_at"]).timestamp()), "canal": "crm", "quem": "nos", "texto": "atualizado no CRM"}
            aprox = True
        dias_parado = (hoje - _quando(ultima["ts"]).date()).days if ultima else None
        esperando = bool(local and local["ultimo_de"] == "lead" and etapa not in ENCERRADO and a and a[2])
        espera_s = agora_s - _seg(a[2]) if esperando else None
        # desde quando está na etapa: histórico local > notas do CRM > (Novo) 1ª mensagem
        desde = None
        if chatid and (chatid, etapa) in hist:
            desde = _quando(_seg(hist[(chatid, etapa)])).date()
        if not desde and lc:
            movs = [d for d, para in _ultimo_movimento(lc.get("notas")) if para == etapa]
            desde = max(movs) if movs else None
        if not desde and etapa == "NOVO":
            desde = _quando(_seg(a[6])).date() if a else (_iso(lc.get("created_at")).date() if lc and _iso(lc.get("created_at")) else None)
        cat = acha_cat(lc, fone8)
        sinais, prio, motivo = [], 0, ""
        if esperando:
            sinais.append({"k": "esperando", "t": "🟢 esperando resposta há " + _horas(espera_s)})
            # quem falou agora vale mais que quem espera há semanas (esse provavelmente esfriou)
            if espera_s <= 7 * 86400:
                prio, motivo = 1000 + (168 - espera_s // 3600), "Cliente esperando resposta há " + _horas(espera_s)
            else:
                prio, motivo = 400, "Cliente esperou resposta há " + _horas(espera_s) + " (esfriando)"
        retomar = (lc or {}).get("retomar_em")
        if etapa == "STAND-BY" and retomar and str(retomar)[:10] <= hoje.isoformat():
            sinais.append({"k": "retomar", "t": "📅 retomar desde " + str(retomar)[8:10] + "/" + str(retomar)[5:7]})
            if prio < 800:
                prio, motivo = 800, "Data de retomar o contato chegou"
        if etapa in ("PROPOSTA ENVIADA", "AGUARDANDO PAGAMENTO"):
            sinais.append({"k": "financeiro", "t": "💰 " + etapa.lower()})
            if prio < 700 and (dias_parado or 0) >= 2:
                prio, motivo = 700 + min(dias_parado, 60), "%s sem resposta há %d dias" % (etapa.capitalize(), dias_parado)
        if cat and cat.get("cobranca_pendente"):
            cp = cat["cobranca_pendente"]
            sinais.append({"k": "financeiro", "t": "💰 PIX pendente R$ %s" % ("%.2f" % float(cp.get("valor") or 0)).replace(".", ",")})
            if prio < 750:
                prio, motivo = 750, "Cobrança gerada e ainda não paga"
        cat_info = None
        if cat:
            dia30 = None
            if cat.get("teste_30d") and _iso(cat.get("entregue_em")):
                dia30 = (hoje - _iso(cat["entregue_em"]).date()).days + 1
                sinais.append({"k": "teste30", "t": "🗓 teste 30d dia %d" % dia30})
            prods, provas = cat.get("produtos"), cat.get("provas")
            if provas is None and g:
                provas = provas_grupo.get(g)
            if prods is not None:
                sinais.append({"k": "produtos", "t": "📦 sem produto" if not prods else "📦 %d produto%s" % (prods, "s" if prods != 1 else "")})
            if provas:
                sinais.append({"k": "provas", "t": "👓 %d prova%s" % (provas, "s" if provas != 1 else "")})
            sc = _iso(cat.get("segunda_chance"))
            if sc:
                sinais.append({"k": "segunda_chance", "t": "🎁 segunda chance " + sc.strftime("%d/%m")})
            if etapa == "TESTE PARADO" and prio < 600:
                prio, motivo = 600 + min(dias_parado or 0, 60), "Teste parado" + (" — " + ("sem produto cadastrado" if prods == 0 else "sem provas recentes") if prods is not None else "")
            elif etapa in ("EM TESTE", "AGUARDANDO DADOS") and prods == 0 and prio < 500 and _iso(cat.get("criado_em")) \
                    and (hoje - _iso(cat["criado_em"]).date()).days >= 2:
                prio, motivo = 500, "Catálogo no ar sem produto há %d dias" % (hoje - _iso(cat["criado_em"]).date()).days
            if sc and etapa not in ENCERRADO and prio < 450 and ultima and ultima["ts"] < sc.timestamp():
                prio, motivo = 450, "Recebeu a segunda chance e ainda não respondeu"
            # respondeu depois da segunda chance = alguma fala do lojista (privado ou grupo) depois da mensagem
            ult_lead = max([_seg(x[2]) for x in (a, ag) if x and x[2]] or [0])
            prox = cat.get("proximo") or None
            cat_info = {"slug": cat.get("slug"), "produtos": prods, "provas": provas, "provas_7d": cat.get("provas_7d"),
                        "teste30_dia": dia30, "segunda_chance": sc.strftime("%d/%m") if sc else None,
                        "sc_respondeu": bool(sc and ult_lead > sc.timestamp()),
                        "sc_produtos": cat.get("produtos_pos_sc"), "sc_provas": cat.get("provas_pos_sc"),
                        "entregue_em": _iso(cat["entregue_em"]).strftime("%d/%m") if _iso(cat.get("entregue_em")) else None,
                        "proximo": {"dia": prox.get("dia"), "rotulo": ROTULO_ENVIO.get(prox.get("etapa"), "Dia %s" % prox.get("dia")),
                                    "data": str(prox.get("agendado_para") or "")[:10]} if prox else None}
        elif etapa == "TESTE PARADO" and prio < 600:
            prio, motivo = 600 + min(dias_parado or 0, 60), "Teste parado"
        if dias_parado is not None and dias_parado >= 3 and etapa not in ENCERRADO:
            sinais.append({"k": "parado", "t": "⏰ parado %d dias" % dias_parado})
            if etapa != "NOVO" and dias_parado <= 7 and prio < 460:
                # janela de follow-up: ainda dá pra retomar sem soar insistente nem deixar esfriar
                prio, motivo = 460 + dias_parado, "Fazer follow-up: sem interação há %d dias" % dias_parado
            elif etapa != "NOVO" and prio < 300:
                prio, motivo = 300 + min(dias_parado, 90), "Sem interação há %d dias (esfriando)" % dias_parado
            elif prio < 100:
                prio, motivo = 100 + min(dias_parado, 90), "Novo sem interação há %d dias" % dias_parado
        if chatid in jev and (sug_status.get(chatid) or "NOVO") == (local["status"] if local else "NOVO"):
            sinais.append({"k": "jev", "t": "✨ Jev sugere " + jev[chatid].lower()})
            if prio < 200:
                prio, motivo = 200, "Jev sugere mover para " + jev[chatid].title()
        if etapa in ENCERRADO:
            prio, motivo = 0, ""
            if chatid in planos:
                sinais.append({"k": "plano", "t": "✅ " + planos[chatid][0]})
        return {"chatid": chatid, "crm_id": (lc or {}).get("id"),
                "nome": (lc or {}).get("nome_loja") or (local["nome"] if local else "") or fone, "fone": fone,
                "etapa": etapa, "dias_na_etapa": (hoje - desde).days if desde else None, "responsavel": resp,
                "ultima": {"quando": _quando(ultima["ts"]).strftime("%d/%m/%Y %H:%M"), "quem": ultima["quem"], "canal": ultima["canal"],
                           "texto": ultima["texto"], "aprox": aprox} if ultima else None,
                "ultima_ts": ultima["ts"] if ultima else 0, "dias_parado": dias_parado,
                "esperando": esperando, "espera_horas": round(espera_s / 3600, 1) if esperando else None,
                "catalogo": cat_info, "retomar_em": retomar, "motivo_perda": (lc or {}).get("motivo_perda") if etapa == "PERDIDO" else None,
                "sinais": sinais, "prioridade": prio, "motivo": motivo}

    for l in locais:
        lc = por_id.get(links.get(l["chatid"])) if links.get(l["chatid"]) else None
        lc = lc or por_fone.get(_digitos(l["fone"])[-8:])
        if lc:
            usados.add(lc["id"])
        it = monta(l["chatid"], l, lc)
        if it:
            itens.append(it)
    for lc in crm_leads:
        if lc["id"] in usados or lc.get("status") not in CRM_SO_A_PARTIR:
            continue
        it = monta(None, None, lc)
        if it:
            itens.append(it)

    itens.sort(key=lambda x: (-x["prioridade"], -x["ultima_ts"]))
    # "parado" conta do Em conversa em diante: Novo que nunca respondeu é lista fria, não lead parado
    ativos = [x for x in itens if x["etapa"] not in ENCERRADO and x["etapa"] != "NOVO"]
    resumo = {
        "total": len(itens),
        "por_etapa": {e: sum(1 for x in itens if x["etapa"] == e) for e in etapas.STATUS},
        "esperando": sum(1 for x in itens if x["esperando"]),
        "parados_3": sum(1 for x in ativos if (x["dias_parado"] or 0) >= 3),
        "parados_7": sum(1 for x in ativos if (x["dias_parado"] or 0) >= 7),
        "parados_15": sum(1 for x in ativos if (x["dias_parado"] or 0) >= 15),
        "catalogos": sum(1 for x in itens if x["catalogo"]),
        "segunda_chance": sum(1 for x in itens if (x["catalogo"] or {}).get("segunda_chance")),
        "sc_responderam": sum(1 for x in itens if (x["catalogo"] or {}).get("sc_respondeu")),
        "sc_cadastraram": sum(1 for x in itens if ((x["catalogo"] or {}).get("sc_produtos") or 0) > 0),
        "sc_provaram": sum(1 for x in itens if ((x["catalogo"] or {}).get("sc_provas") or 0) > 0),
        "teste30": sum(1 for x in itens if (x["catalogo"] or {}).get("teste30_dia") is not None),
        "para_hoje": sum(1 for x in itens if x["prioridade"] >= PARA_HOJE),
    }
    return {"usuario": u, "resumo": resumo, "itens": itens, "etapas": list(etapas.STATUS),
            "fontes": {"rpc": rpc_ok, "avisos": avisos}, "gerado_em": agora.strftime("%d/%m/%Y %H:%M"),
            "ms": round((time.monotonic() - t0) * 1000)}
