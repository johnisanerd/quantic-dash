"""Responder pelo painel da Jornada: últimas mensagens + "Jev sugere a resposta" + registro do que a Dione fez.

- conversa(): últimas mensagens da conversa privada (áudio/imagem como rótulo, transcrição quando já existe).
- sugere(): monta o contexto da jornada (etapa, tempo na etapa, catálogo, régua, segunda chance, proposta/PIX)
  + base de conhecimento do Assistente (planos, objeções) + tom da Dione, e pede a próxima mensagem ao modelo
  (Claude Haiku pela ANTHROPIC_API_KEY / PL_IA_MODELO, com Gemini de reserva). Devolve resposta + "por quê".
  Cache por (conversa, última mensagem): abrir de novo não gasta outra chamada. Nunca envia nada.
- resposta_sugestao (painel.db): cada sugestão gerada e o destino dela — enviada como estava, editada ou
  descartada — pra medir o Jev depois (espelhada no Supabase pelo espelho.py, se a RPC existir).
O envio em si é do painel.py (mesmo envia_texto do Atendimento), sempre por clique humano."""
import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.request

import assistente
from historico_lead import _dt

IGNORA = ("ReactionMessage", "PinInChatMessage")
TEXTO = {None, "", "Conversation", "ExtendedTextMessage", "TextMessage", "TemplateMessage", "ButtonsMessage",
         "ButtonsResponseMessage", "ListMessage", "ListResponseMessage", "NativeFlowMessage", "InteractiveMessage",
         "TemplateButtonReplyMessage", "Queued", "error", "UnknownMessageType"}
MIDIA = {"AudioMessage": "áudio", "ImageMessage": "imagem", "VideoMessage": "vídeo", "DocumentMessage": "documento",
         "StickerMessage": "figurinha", "ContactMessage": "contato", "AlbumMessage": "álbum", "PtvMessage": "vídeo"}
TIMEOUT = 8.0
MODELO_CLAUDE = "claude-haiku-5-5"

TOM = """Você é o Jev, o copiloto do comercial da Provou Levou. Escreva a PRÓXIMA mensagem que a %(quem)s vai mandar
para este lojista no WhatsApp, continuando a conversa abaixo.

Tom da Dione: informal e simpática, frases curtas, jeito de WhatsApp (nada de e-mail), 1 a 4 linhas, no máximo
um emoji e só quando cabe. Trata por "você". Sem assinatura, sem "Olá, tudo bem?" se a conversa já está rolando.

Regras:
- Responda primeiro o que o cliente perguntou por último. Se ele não perguntou nada, puxe o próximo passo da etapa.
- Preços, planos, números e prazos: SOMENTE os da BASE DE CONHECIMENTO. Nunca invente valor, desconto, prazo
  ou funcionalidade. Se faltar informação para responder, a mensagem deve ser uma pergunta curta ao cliente
  (ou dizer que vai confirmar com o Lucas).
- Desconto, plano fora da tabela, Enterprise ou questão técnica de instalação: diga que vai confirmar com o Lucas.
- Use o contexto do lead (etapa, catálogo, produtos, provas, régua de 30 dias, segunda chance, cobrança) para
  personalizar: ex.: catálogo sem produto -> ajudar a cadastrar; provando bem perto do fim do teste -> propor o
  pacote pelo volume; PIX pendente -> lembrar com leveza.
- Nunca use colchetes ou placeholders. Se não souber o nome da pessoa, não invente.

Responda SÓ um JSON, sem nada antes ou depois:
{"resposta": "<texto da mensagem, pronto para enviar>", "porque": "<uma linha curta explicando pra Dione o motivo, ex.: cliente perguntou o preço do plano de 200 provas>"}"""


def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS resposta_sugestao (id INTEGER PRIMARY KEY AUTOINCREMENT, chatid TEXT NOT NULL, "
              "ultima_msg TEXT, usuario TEXT, sugestao TEXT NOT NULL, porque TEXT, modelo TEXT, alerta TEXT, "
              "criado_ts INTEGER NOT NULL, resultado TEXT, texto_enviado TEXT, decidido_ts INTEGER)")
    c.execute("CREATE INDEX IF NOT EXISTS ix_resposta_sugestao ON resposta_sugestao(chatid, ultima_msg)")


def _rotulo(tipo, seg):
    n = MIDIA.get(tipo, (tipo or "mídia").replace("Message", "").lower())
    return "[%s%s]" % (n, " de %ss" % seg if seg else "")


def mensagens(c, chatid, n=8):
    rows = c.execute("SELECT messageid, ts, from_me, tipo, texto, segundos FROM mensagens WHERE chatid=? AND excluida=0 "
                     "AND COALESCE(tipo,'') NOT IN ('ReactionMessage','PinInChatMessage') ORDER BY ts DESC LIMIT ?",
                     (chatid, n)).fetchall()
    ids = ["msg:" + r["messageid"] for r in rows if r["tipo"] == "AudioMessage"]
    trans = {}
    if ids:
        trans = {r[0][4:]: r[1] for r in c.execute("SELECT url, texto FROM transcricoes WHERE url IN (%s)" % ",".join("?" * len(ids)), ids)}
    out = []
    for r in reversed(rows):
        t = (r["texto"] or "").strip()
        midia = r["tipo"] not in TEXTO
        out.append({"id": r["messageid"], "de": "nos" if r["from_me"] else "lead", "hora": _dt(r["ts"]).strftime("%d/%m %H:%M"),
                    "texto": (_rotulo(r["tipo"], r["segundos"]) + (" " + t if t and r["tipo"] != "AudioMessage" else "")) if midia else t,
                    "midia": midia, "transcricao": trans.get(r["messageid"]) or ""})
    return out


def conversa(c, usuario, chatid):
    """Quadro "Responder": só conversa privada que está no painel (o mesmo que o Atendimento deixa abrir)."""
    if not isinstance(chatid, str) or not chatid.endswith("@s.whatsapp.net"):
        raise ValueError("Só dá pra responder pelo painel em conversa privada.")
    if (usuario or "").strip().lower() not in ("lucas", "dione"):
        raise PermissionError("Login sem acesso ao envio.")
    lead = c.execute("SELECT nome, fone, status, responsavel, ultimo_de FROM leads WHERE chatid=?", (chatid,)).fetchone()
    if not lead:
        raise ValueError("Conversa não encontrada no Atendimento.")
    return {"chatid": chatid, "nome": lead["nome"], "fone": lead["fone"], "etapa": lead["status"],
            "responsavel": lead["responsavel"], "esperando": lead["ultimo_de"] == "lead", "mensagens": mensagens(c, chatid)}


def _contexto(j, msgs):
    """Texto de contexto pro modelo a partir da jornada (sem telefone)."""
    if not j:
        return "(sem dados da jornada)"
    r, L, rg = j.get("resumo") or {}, j.get("lead") or {}, j.get("regua")
    linhas = ["Loja: %s" % (L.get("nome") or "—"),
              "Etapa atual: %s%s" % (r.get("etapa"), " há %s dias" % r["dias_na_etapa"] if r.get("dias_na_etapa") is not None else ""),
              "No funil há %s dias · responsável: %s" % (r.get("dias_desde_entrada"), r.get("responsavel") or "ninguém"),
              "Mensagens: %s nossas, %s do lead" % (r.get("msgs_nossas"), r.get("msgs_dele"))]
    if L.get("catalogo"):
        linhas.append("Catálogo: %s · provas no total: %s" % (L["catalogo"]["link"], r.get("provas")))
    prods = [e for e in j.get("eventos") or [] if e.get("tipo") == "produtos"]
    if L.get("catalogo"):
        linhas.append("Produtos cadastrados: %s" % (sum(e.get("n") or 0 for e in prods) if prods else "nenhum"))
    if rg:
        linhas.append("Régua de 30 dias: entregue em %s, hoje é o dia %s (%s); teste grátis de %s a %s" % (
            rg.get("entregue_em"), rg.get("dia_atual"), rg.get("fase"), rg.get("teste_de"), rg.get("teste_ate")))
    sc = [e for e in j.get("eventos") or [] if e.get("tipo") == "envio_auto" and "Segunda chance" in (e.get("titulo") or "")]
    if sc:
        linhas.append("Recebeu a mensagem automática de SEGUNDA CHANCE em %s: %s" % (sc[-1]["quando"], (sc[-1].get("texto") or "")[:300]))
    fin = [e for e in j.get("eventos") or [] if e.get("cat") == "financeiro"][-4:]
    for e in fin:
        linhas.append("Financeiro (%s): %s %s" % (e["quando"], e["titulo"], e.get("detalhe") or ""))
    if (r.get("conta") or {}).get("status"):
        linhas.append("Conta: %s · plano %s" % (r["conta"].get("status"), r["conta"].get("plano") or "—"))
    for p in (r.get("proximos") or [])[:3]:
        linhas.append("Próximo marco %s: %s" % (p["data"], p["titulo"]))
    if r.get("motivo_perda"):
        linhas.append("Motivo da perda: %s" % r["motivo_perda"])
    return "\n".join(linhas)


def _historico(c, chatid, n=16):
    out = []
    for m in mensagens(c, chatid, n):
        t = m["transcricao"] and (m["texto"] + " (transcrição: " + m["transcricao"][:400] + ")") or m["texto"]
        out.append("%s %s: %s" % (m["hora"], "NÓS" if m["de"] == "nos" else "LOJISTA", (t or "")[:500]))
    return out


def _json(texto):
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        raise ValueError("resposta fora do formato")
    d = json.loads(m.group(0))
    resp = str(d.get("resposta") or "").strip().strip('"')
    if not resp:
        raise ValueError("resposta vazia")
    return resp[:1500], str(d.get("porque") or "").strip()[:200]


def _claude(sistema, usuario_msg, timeout, temperatura):
    chave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chave:
        raise RuntimeError("sem ANTHROPIC_API_KEY")
    modelo = os.environ.get("PL_IA_MODELO", "")
    modelo = modelo if modelo.startswith("claude") else MODELO_CLAUDE
    h = {"x-api-key": chave, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        h["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    body = {"model": modelo, "max_tokens": 700, "temperature": temperatura,
            "system": [{"type": "text", "text": sistema, "cache_control": {"type": "ephemeral"}}],
            "messages": [{"role": "user", "content": usuario_msg}]}
    r = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"), method="POST", headers=h)
    with urllib.request.urlopen(r, timeout=timeout) as x:
        d = json.loads(x.read().decode("utf-8"))
    return "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text"), modelo


def _gemini(sistema, usuario_msg, timeout, temperatura):
    chave = os.environ.get("GEMINI_KEY", "")
    if not chave:
        raise RuntimeError("sem GEMINI_KEY")
    body = {"systemInstruction": {"parts": [{"text": sistema}]}, "contents": [{"role": "user", "parts": [{"text": usuario_msg}]}],
            "generationConfig": {"temperature": temperatura, "maxOutputTokens": 700, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}}}
    r = urllib.request.Request("https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + chave,
                               data=json.dumps(body).encode("utf-8"), method="POST", headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as x:
        d = json.loads(x.read().decode("utf-8"))
    return d["candidates"][0]["content"]["parts"][0]["text"], "gemini-2.5-flash"


def chama_modelo(sistema, usuario_msg, temperatura=0.4, prazo=TIMEOUT):
    """Claude primeiro; se falhar e ainda houver tempo, Gemini. Devolve (resposta, porque, modelo)."""
    inicio, erros = time.monotonic(), []
    ordem = (_gemini, _claude) if os.environ.get("PL_IA_MODELO", "").startswith("gemini") else (_claude, _gemini)
    for f in ordem:
        resta = prazo - (time.monotonic() - inicio)
        if resta < 2:
            break
        try:
            texto, modelo = f(sistema, usuario_msg, resta, temperatura)
            resp, porque = _json(texto)
            return resp, porque, modelo
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, RuntimeError, KeyError, IndexError) as e:
            erros.append("%s: %s" % (f.__name__, str(e)[:80]))
    raise RuntimeError("; ".join(erros) or "sem tempo")


_VALOR = re.compile(r"R\$\s?(\d{1,3}(?:\.\d{3})*(?:,\d{2})?|\d+(?:,\d{2})?)")


def confere_valores(texto):
    """Valor em R$ que não está na base de conhecimento vira alerta (a Dione confere antes de mandar)."""
    base = assistente.BASE
    fora = [v for v in _VALOR.findall(texto or "") if ("R$ " + v.split(",")[0]) not in base]
    return ("Confira: %s não está na tabela de preços." % ", ".join("R$ " + v for v in fora)) if fora else ""


def sugere(c, usuario, chatid, jornada_fn, nova=False, quem="a Dione"):
    """jornada_fn() -> dict da jornada (ou None). Devolve {id, resposta, porque, modelo, alerta, cache} ou {erro}."""
    conv = conversa(c, usuario, chatid)
    ult = conv["mensagens"][-1]["id"] if conv["mensagens"] else ""
    anterior = c.execute("SELECT * FROM resposta_sugestao WHERE chatid=? AND ultima_msg=? ORDER BY id DESC LIMIT 1",
                         (chatid, ult)).fetchone()
    if anterior and not nova and anterior["resultado"] in (None, "descartada"):
        return {"id": anterior["id"], "resposta": anterior["sugestao"], "porque": anterior["porque"], "modelo": anterior["modelo"],
                "alerta": anterior["alerta"] or "", "cache": True}
    try:
        j = jornada_fn()
    except Exception:
        j = None
    pedido = ("# CONTEXTO DO LEAD (jornada)\n%s\n\n# ÚLTIMAS MENSAGENS (mais antigas primeiro)\n%s\n\n" % (
        _contexto(j, conv["mensagens"]), "\n".join(_historico(c, chatid)) or "(conversa ainda sem mensagens)"))
    if nova and anterior:
        pedido += "A sugestão anterior foi recusada; escreva uma alternativa diferente desta: %s\n\n" % anterior["sugestao"][:400]
    pedido += "Escreva a próxima mensagem de %s." % quem
    sistema = (TOM % {"quem": quem}) + "\n\n# BASE DE CONHECIMENTO\n" + assistente.BASE
    try:
        resp, porque, modelo = chama_modelo(sistema, pedido, 0.8 if nova else 0.4)
    except RuntimeError as e:
        print("  aviso: Jev não sugeriu resposta (%s)" % str(e)[:160])
        return {"erro": "O Jev não conseguiu sugerir agora. Escreva a mensagem ou tente de novo em instantes."}
    alerta = confere_valores(resp)
    if anterior and nova and anterior["resultado"] is None:
        decide(c, anterior["id"], "descartada")
    cur = c.execute("INSERT INTO resposta_sugestao(chatid, ultima_msg, usuario, sugestao, porque, modelo, alerta, criado_ts) "
                    "VALUES(?,?,?,?,?,?,?,?)", (chatid, ult, (usuario or "").lower(), resp, porque, modelo, alerta, int(time.time())))
    c.commit()
    return {"id": cur.lastrowid, "resposta": resp, "porque": porque, "modelo": modelo, "alerta": alerta, "cache": False}


def _norm(t):
    return " ".join(str(t or "").split())


def decide(c, sugestao_id, resultado, texto_enviado=None):
    """resultado: enviada (como estava) | editada | descartada. Calcula enviada x editada pelo texto."""
    try:
        sid = int(sugestao_id)
    except (TypeError, ValueError):
        return None
    r = c.execute("SELECT sugestao, resultado FROM resposta_sugestao WHERE id=?", (sid,)).fetchone()
    if not r or r["resultado"] in ("enviada", "editada"):
        return None
    if resultado in ("enviada", "editada"):
        resultado = "enviada" if _norm(texto_enviado) == _norm(r["sugestao"]) else "editada"
    elif resultado != "descartada":
        return None
    c.execute("UPDATE resposta_sugestao SET resultado=?, texto_enviado=?, decidido_ts=? WHERE id=?",
              (resultado, texto_enviado, int(time.time()), sid))
    c.commit()
    return resultado
