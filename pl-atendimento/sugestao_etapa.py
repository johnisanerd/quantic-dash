"""Jev (TypeSafe) + Claude Haiku organizando o funil de prospecção pelas conversas do WhatsApp.

Para cada conversa com mensagem nova (e, na 1ª passada, todas as do funil inicial):
1. Filtro fixo: conversa em que o "lojista" só mandou suporte de cliente final, spam, resposta
   automática do WhatsApp Business ou a mensagem pronta do anúncio NÃO é avaliada.
2. Monta o texto limpo (nossas mensagens resumidas, áudio do lojista transcrito, cartão de
   contato/e-mail marcados, etapa atual) e pergunta a etapa ao Jev E ao Haiku.
3. Os dois concordam com certeza >= 0,8 -> MOVE SOZINHO (Em conversa, Interessado, Aguardando
   dados, Stand-by; só avançando). Perdido nunca move sozinho. Discordam mas um está seguro
   (Jev >= 0,9 ou Haiku >= 0,8) -> SUGESTÃO na conversa. Haiku fora do ar -> vale só o Jev >= 0,9.
Gabarito de 127 conversas reais (09/10/2026): automático 75/75 certos, sugestão 8/10.
Tudo fica em etapa_sugestao (decisao auto/aplicada/ignorada) e é espelhado no Supabase.
"""
import json
import os
import re
import sqlite3
import time
import urllib.request

CONFIANCA = 0.8          # Haiku: mostra sugestão / concordância
CONFIANCA_AUTO = 0.9     # Jev sozinho: sugestão (ou automático se o Haiku estiver fora)
MODELO_HAIKU = "claude-haiku-5-5"
# 21/10/2026 (Dione): o Jev não move mais ninguém sozinho — só sugere; quem decide a etapa é ela, no meio da conversa.
AUTO_OK = set()
# Falas do "lojista" que não dizem nada sobre o interesse dele (o Jev não deve decidir em cima delas)
ANUNCIO = re.compile(r"(?i)^\s*(oi|ol[aá])!?\s*(gostaria de saber mais sobre o|tenho interesse no|quero saber mais sobre o) (provador virtual|provou cat[aá]logo)")
AUTOMATICA = re.compile(r"(?i)agradecemos sua mensagem|n[aã]o estamos dispon[ií]veis|seja muito bem-vind|em breve iremos te atender|hor[aá]rio de atendimento|nosso hor[aá]rio|mensagem autom[aá]tica")
SPAM = re.compile(r"(?i)\bbets?\b|apostas|tiktok\.com|gire a roda|pix premiado|medida provis[oó]ria")
SUPORTE = re.compile(r"(?i)tive um problema ao usar o provador")
# Mensagens NOSSAS que mostram que o lojista já recebeu o catálogo/provador: daí em diante quem move é a
# rotina do funil pelos dados da loja (Em teste / Teste parado), não o Jev pela conversa.
ENTREGUE = re.compile(r"(?i)catalogo/painel|ficou pronto|est[aá] pronto|provador online|bem-vind[oa]s? [àa] provou levou|"
                      r"seu acesso ao painel|j[aá] est[aá] na p[aá]gina|aqui vai o seu acesso")
SEM_SINAL = ("mensagem automática do anúncio", "resposta automática", "spam/propaganda", "suporte de CLIENTE FINAL")
INTERVALO = 20
POR_PASSADA = 8

CRITERIOS = {
    "novo": "Ainda não houve resposta de verdade do lojista: só clicou no anúncio, só cumprimentou, respondeu ok/emoji, mandou resposta automática, spam, ou ainda não respondeu nossas mensagens",
    "em_conversa": "O lojista respondeu de verdade e está se apresentando: disse onde vende (loja física, site, Instagram, WhatsApp), qual plataforma usa ou contou do negócio, mas AINDA NÃO perguntou preço, como funciona, nem pediu para testar",
    "interessado": "O lojista quer saber mais para comprar: perguntou preço/valor/planos, perguntou como funciona ou detalhes do provador (medidas, cadastro de modelos, integração), pediu reunião/ligação, disse que gostou e quer, ou negociou valor — mas ainda não aceitou começar o teste nem mandou dados",
    "aguardando_dados": "O lojista ACEITOU começar o teste ou a instalação: disse que quer testar / pode montar / vamos, ou mandou e-mail, logo, WhatsApp da loja ou dados de acesso; inclui quem já está com o catálogo sendo criado ou entregue",
    "stand_by": "O lojista adiou: pediu para falar depois, vai pensar/analisar e retorna, está sem tempo, viajando, organizando estoque ou fotos, esperando uma função (ex.: medida de DNP) ou disse 'no momento não, mas gostei'",
    "perdido": "Não vai seguir: disse que não tem interesse, não compensa, achou caro e recusou, já usa outra solução, quer cancelar, NÃO TEM LOJA, é um CLIENTE FINAL querendo comprar óculos para uso próprio, ou foi engano",
}
ETAPA = {"em_conversa": "EM CONVERSA", "interessado": "INTERESSADO", "aguardando_dados": "AGUARDANDO DADOS",
         "stand_by": "STAND-BY", "perdido": "PERDIDO"}
# De onde cada etapa pode partir (só avanço; nunca puxa um lead de volta).
PODE_SAIR_DE = {
    "EM CONVERSA": {"NOVO", "STAND-BY"},
    "INTERESSADO": {"NOVO", "EM CONVERSA", "STAND-BY"},
    "AGUARDANDO DADOS": {"NOVO", "EM CONVERSA", "INTERESSADO", "STAND-BY"},
    "STAND-BY": {"NOVO", "EM CONVERSA", "INTERESSADO", "AGUARDANDO DADOS"},
    "PERDIDO": {"NOVO", "EM CONVERSA", "INTERESSADO", "AGUARDANDO DADOS", "STAND-BY"},
}
AVALIA = ("NOVO", "EM CONVERSA", "INTERESSADO", "AGUARDANDO DADOS", "STAND-BY")


def init(c):
    c.execute("CREATE TABLE IF NOT EXISTS etapa_sugestao (chatid TEXT PRIMARY KEY, etapa TEXT, conf REAL, "
              "status_antes TEXT, ultimo_ts INTEGER, criado_ts INTEGER, decisao TEXT, decidido_ts INTEGER, decidido_por TEXT)")
    # v2 (09/10/2026, Jev + Haiku): sugestões pendentes da v1 (50% de acerto no gabarito) são refeitas
    c.execute("CREATE TABLE IF NOT EXISTS etapa_sugestao_versao (versao TEXT PRIMARY KEY)")
    if not c.execute("SELECT 1 FROM etapa_sugestao_versao WHERE versao='v2'").fetchone():
        c.execute("DELETE FROM etapa_sugestao WHERE decisao IS NULL")
        c.execute("INSERT INTO etapa_sugestao_versao(versao) VALUES('v2')")
    c.commit()


def _jev(conversa, status, chave):
    estado = ("Etapa atual no CRM: %s.\n" % (status or "NOVO") +
              "Conversa de prospecção no WhatsApp entre NÓS (Provou Levou, provador virtual com IA para óticas e lojas "
              "de moda) e um possível LOJISTA. Mensagens mais antigas primeiro; as nossas estão resumidas:\n" + "\n".join(conversa))
    body = {"model": "jev-latest", "state": estado,
            "questions": {"etapa": {"type": "choice", "criteria": CRITERIOS,
                                    "instructions": "Pelo que o LOJISTA disse (ignore o que nós dissemos), em que etapa do funil ele está "
                                                    "agora? Considere principalmente as últimas falas dele."}}}
    r = urllib.request.Request("https://api.typesafe.ai/v1/systemone", data=json.dumps(body).encode("utf-8"), method="POST",
                               headers={"Authorization": "Bearer " + chave, "Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=15) as x:
        a = json.loads(x.read().decode("utf-8"))["answers"]["etapa"]
    return ROTULO.get(a["choice"]), float(a["confidence"])


ROTULO = {"novo": "NOVO", "em_conversa": "EM CONVERSA", "interessado": "INTERESSADO", "aguardando_dados": "AGUARDANDO DADOS",
          "stand_by": "STAND-BY", "perdido": "PERDIDO"}
_SISTEMA_HAIKU = ("Você classifica conversas de prospecção da Provou Levou (provador virtual com IA para óticas e lojas de moda) "
                  "na etapa do funil em que o LOJISTA está, pelo que ELE disse. Etapas:\n" +
                  "\n".join("- %s: %s" % (ROTULO[k], v) for k, v in CRITERIOS.items()) +
                  "\nResponda APENAS com um JSON numa linha, sem mais nada: {\"etapa\": \"<NOVO|EM CONVERSA|INTERESSADO|"
                  "AGUARDANDO DADOS|STAND-BY|PERDIDO>\", \"certeza\": <0 a 1>}")


def _haiku(conversa, status):
    """Segunda opinião. Devolve (etapa, certeza) ou (None, 0) se não der."""
    chave = os.environ.get("ANTHROPIC_API_KEY", "")
    if not chave:
        return None, 0.0
    h = {"x-api-key": chave, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    if os.environ.get("ANTHROPIC_WORKSPACE_ID"):
        h["anthropic-workspace-id"] = os.environ["ANTHROPIC_WORKSPACE_ID"]
    body = {"model": MODELO_HAIKU, "max_tokens": 600, "system": _SISTEMA_HAIKU,
            "messages": [{"role": "user", "content": "Etapa atual no CRM: %s\n%s" % (status or "NOVO", "\n".join(conversa))}]}
    try:
        r = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode("utf-8"), method="POST", headers=h)
        with urllib.request.urlopen(r, timeout=30) as x:
            d = json.loads(x.read().decode("utf-8"))
        texto = "".join(b.get("text", "") for b in d.get("content", []) if b.get("type") == "text")
        m = re.search(r"\{[^{}]*\}", texto)
        j = json.loads(m.group(0)) if m else {}
        etapa = str(j.get("etapa", "")).upper().strip()
        return (etapa, float(j.get("certeza", 0))) if etapa in ROTULO.values() else (None, 0.0)
    except Exception:
        return None, 0.0


def combina(jev, haiku):
    """(etapa, certeza, automatico?) a partir das duas opiniões; None se nenhuma é confiável."""
    (ej, cj), (eh, ch) = jev, haiku
    if eh is None:                                   # Haiku fora: só o Jev, com a régua alta
        return (ej, cj, True) if ej and cj >= CONFIANCA_AUTO else None
    if ej and ej == eh and max(cj, ch) >= CONFIANCA:
        return ej, max(cj, ch), True                 # concordam: 75/75 no gabarito
    if cj >= CONFIANCA_AUTO:
        return ej, cj, False                         # discordam: vira sugestão
    if ch >= CONFIANCA:
        return eh, ch, False
    return None


def _conversa(c, chatid, transcreve):
    ms = c.execute("SELECT messageid, from_me, tipo, texto, file_url FROM mensagens WHERE chatid=? AND excluida=0 "
                   "ORDER BY ts DESC LIMIT 14", (chatid,)).fetchall()
    linhas = []
    for m in reversed(ms):
        t = (m["texto"] or "").strip().replace("\n", " ")
        if not t and m["tipo"] == "AudioMessage":
            t = ("[áudio] " + (transcreve(m["messageid"]) or "")).strip() if not m["from_me"] else "[áudio]"
        elif not t:
            t = {"ImageMessage": "[imagem]", "DocumentMessage": "[arquivo]", "VideoMessage": "[vídeo]"}.get(m["tipo"], "")
        if not t:
            continue
        if m["from_me"]:
            if ENTREGUE.search(t):
                linhas.append("NÓS: (entregamos o acesso ao catálogo/provador)")
                continue
            t = t[:140] + ("…" if len(t) > 140 else "")
            if linhas and linhas[-1].startswith("NÓS:") and len(linhas[-1]) > 300:
                continue                              # junta nossa sequência longa de mensagens
            linhas.append("NÓS: " + t)
            continue
        if "X-Wa-Biz" in t or "Phone (Celular)" in t:
            t = "(enviou um cartão de contato com o telefone da loja)"
        elif AUTOMATICA.search(t):
            t = "(resposta automática do WhatsApp Business, não foi uma pessoa)"
        elif SPAM.search(t):
            t = "(spam/propaganda, não tem relação com a conversa)"
        elif SUPORTE.search(t):
            t = "(mensagem padrão de suporte de CLIENTE FINAL de alguma loja, não é lojista)"
        elif ANUNCIO.search(t):
            t = "(clicou no anúncio; mensagem automática do anúncio)"
        elif re.search(r"[\w.+-]+@[\w-]+\.\w", t):
            t = t[:300] + "  (← mandou e-mail)"
        linhas.append("LOJISTA: " + t[:300])
    return linhas[-12:]


def passada(db_path, transcreve, mover=None):
    chave = os.environ.get("JEV_API_KEY", "")
    if not chave:
        return 0
    c = sqlite3.connect(db_path, timeout=30)
    c.row_factory = sqlite3.Row
    try:
        init(c)
        alvos = c.execute(
            "SELECT l.chatid, l.status, l.ultimo_ts FROM leads l LEFT JOIN etapa_sugestao s ON s.chatid = l.chatid "
            "WHERE COALESCE(l.oculto,0) = 0 AND l.chatid NOT LIKE '%@g.us' "
            "AND COALESCE(l.status,'NOVO') IN (" + ",".join("'%s'" % x for x in AVALIA) + ") "
            "AND (s.chatid IS NULL OR s.ultimo_ts < l.ultimo_ts) "
            # quem respondeu agora vem primeiro; depois o resto do funil (1ª passada)
            "ORDER BY (l.ultimo_de = 'lead') DESC, l.ultimo_ts DESC LIMIT ?", (POR_PASSADA,)).fetchall()
        feitos = 0
        for a in alvos:
            conversa = _conversa(c, a["chatid"], transcreve)
            etapa, conf, auto = None, 0.0, False
            falas = [x for x in conversa if x.startswith("LOJISTA") and not any(k in x for k in SEM_SINAL)]
            ja_entregue = any("entregamos o acesso" in x for x in conversa)
            if falas and not ja_entregue:
                try:
                    opiniao = combina(_jev(conversa, a["status"], chave), _haiku(conversa, a["status"]))
                except Exception as e:
                    print("  aviso: avaliação de etapa falhou (%s)" % str(e)[:120])
                    continue
                if opiniao:
                    alvo, conf, auto = opiniao
                    if alvo and alvo != a["status"] and (a["status"] or "NOVO") in PODE_SAIR_DE.get(alvo, ()):
                        etapa = alvo
            decisao = None
            if etapa and mover and auto and etapa in AUTO_OK:
                try:
                    mover(a["chatid"], etapa)
                    decisao = "auto"
                except Exception as e:
                    print("  aviso: Jev não conseguiu mover %s (%s)" % (a["chatid"][-12:], str(e)[:100]))
            # grava mesmo sem sugestão: marca a mensagem como avaliada e não repete a chamada
            c.execute("INSERT INTO etapa_sugestao(chatid,etapa,conf,status_antes,ultimo_ts,criado_ts,decisao,decidido_ts,decidido_por) "
                      "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(chatid) DO UPDATE SET etapa=excluded.etapa, conf=excluded.conf, "
                      "status_antes=excluded.status_antes, ultimo_ts=excluded.ultimo_ts, criado_ts=excluded.criado_ts, "
                      "decisao=excluded.decisao, decidido_ts=excluded.decidido_ts, decidido_por=excluded.decidido_por",
                      (a["chatid"], etapa, conf, a["status"], a["ultimo_ts"], int(time.time()),
                       decisao, int(time.time()) if decisao else None, "jev" if decisao else None))
            c.commit()
            feitos += 1
        return feitos
    finally:
        c.close()


def loop(db_path, transcreve, avisa, mover=None):
    if not os.environ.get("JEV_API_KEY"):
        print("  aviso: sugestão de etapa desligada (sem JEV_API_KEY)")
        return
    while True:
        try:
            if passada(db_path, transcreve, mover):
                avisa()
        except Exception as e:
            print("  aviso: sugestão de etapa falhou (%s)" % str(e)[:160])
        time.sleep(INTERVALO)


def pendente(c, chatid, status_atual):
    """Sugestão ainda válida para mostrar na conversa (some se a etapa já mudou)."""
    r = c.execute("SELECT etapa, conf, status_antes FROM etapa_sugestao WHERE chatid=? AND decisao IS NULL AND etapa IS NOT NULL",
                  (chatid,)).fetchone()
    if not r or (r["status_antes"] or "NOVO") != (status_atual or "NOVO"):
        return None
    return {"etapa": r["etapa"], "conf": round(r["conf"], 2)}


def decide(c, chatid, acao, usuario):
    if acao not in ("aplicada", "ignorada"):
        raise ValueError("Ação inválida.")
    r = c.execute("SELECT etapa FROM etapa_sugestao WHERE chatid=? AND decisao IS NULL AND etapa IS NOT NULL", (chatid,)).fetchone()
    if not r:
        raise ValueError("Essa sugestão não está mais disponível.")
    c.execute("UPDATE etapa_sugestao SET decisao=?, decidido_ts=?, decidido_por=? WHERE chatid=?",
              (acao, int(time.time()), (usuario or "").lower(), chatid))
    c.commit()
    return r["etapa"]
