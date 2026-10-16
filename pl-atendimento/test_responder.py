"""Responder pela Jornada: envio e sugestão mockados (nada vai pra Uazapi nem pra IA)."""
import json
import os
import tempfile
import threading
import unittest
from datetime import datetime
from unittest.mock import patch

import painel
import resposta_jev
from historico_lead import BRT

CID = "5511987654321@s.whatsapp.net"
GID = "120363000000000001@g.us"


def ms(dia, hora, minuto=0):
    return int(datetime(2026, 10, dia, hora, minuto, tzinfo=BRT).timestamp() * 1000)


JORNADA = {"lead": {"nome": "Ótica Visão Clara", "catalogo": {"link": "provoulevou.com.br/catalogo/?loja=visaoclara"}},
           "resumo": {"etapa": "EM TESTE", "dias_na_etapa": 4, "dias_desde_entrada": 10, "responsavel": "Dione",
                      "msgs_nossas": 3, "msgs_dele": 3, "provas": 0, "proximos": []},
           "regua": {"entregue_em": "04/10/2026", "dia_atual": 13, "fase": "montagem", "teste_de": "25/10", "teste_ate": "31/10"},
           "eventos": [{"tipo": "produtos", "n": 0, "cat": "catalogo"},
                       {"tipo": "envio_auto", "cat": "catalogo", "titulo": "Mensagem automática enviada · Segunda chance · grupo",
                        "quando": "16/10/2026 13:00", "texto": "Seu teste grátis já tinha terminado, mas..."}]}


class ResponderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = painel.DB, painel._local
        painel.DB = os.path.join(self.tmp.name, "painel.db")
        painel._local = threading.local()
        painel.cria_banco()
        c = self.c = painel.con()
        c.execute("INSERT INTO leads(chatid,fone,nome,status,responsavel,ultimo_ts,ultimo_de,oculto) VALUES(?,?,?,?,?,?,?,0)",
                  (CID, "5511987654321", "Ótica Visão Clara", "EM TESTE", "Dione", ms(16, 11), "lead"))
        c.executemany("INSERT INTO mensagens(messageid,chatid,ts,from_me,tipo,texto,segundos) VALUES(?,?,?,?,?,?,?)", [
            ("m1", CID, ms(16, 9), 1, "Conversation", "Conseguiu cadastrar os produtos?", None),
            ("m2", CID, ms(16, 10), 0, "AudioMessage", "", 21),
            ("m3", CID, ms(16, 10, 1), 0, "ReactionMessage", "👍", None),
            ("m4", CID, ms(16, 11), 0, "Conversation", "Quanto fica o plano de 200 provas?", None)])
        c.execute("INSERT INTO transcricoes(url,texto) VALUES('msg:m2','Ainda não cadastrei, tô sem tempo essa semana')")
        c.commit()
        self.chamadas = []

    def tearDown(self):
        painel.DB, painel._local = self.old
        self.tmp.cleanup()

    def claude_fake(self, resposta='{"resposta": "O Profissional sai R$ 159/mês com 200 provas 😊 Quer que eu ative?", "porque": "cliente perguntou o preço do plano de 200 provas"}'):
        def f(sistema, pedido, timeout, temperatura):
            self.chamadas.append((sistema, pedido, timeout, temperatura))
            return resposta, "claude-haiku-5-5"
        return f

    def test_conversa_ultimas_mensagens_com_rotulo_e_transcricao(self):
        d = resposta_jev.conversa(self.c, "dione", CID)
        self.assertTrue(d["esperando"])
        self.assertEqual(["m1", "m2", "m4"], [m["id"] for m in d["mensagens"]])     # reação fica de fora
        self.assertEqual("[áudio de 21s]", d["mensagens"][1]["texto"])
        self.assertIn("sem tempo", d["mensagens"][1]["transcricao"])
        with self.assertRaises(ValueError):
            resposta_jev.conversa(self.c, "dione", GID)
        with self.assertRaises(PermissionError):
            resposta_jev.conversa(self.c, "visitante", CID)

    def test_sugestao_usa_contexto_base_e_cache(self):
        with patch.object(resposta_jev, "_claude", self.claude_fake()):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
            self.assertFalse(r["cache"])
            self.assertIn("R$ 159", r["resposta"])
            self.assertEqual("cliente perguntou o preço do plano de 200 provas", r["porque"])
            self.assertEqual("", r["alerta"])
            sistema, pedido, timeout, _ = self.chamadas[0]
            self.assertIn("Profissional R$ 159 (200)", sistema)                  # base do Assistente
            self.assertIn("a Dione", sistema)
            self.assertIn("Etapa atual: EM TESTE há 4 dias", pedido)
            self.assertIn("hoje é o dia 13", pedido)
            self.assertIn("SEGUNDA CHANCE", pedido)
            self.assertIn("transcrição: Ainda não cadastrei", pedido)
            self.assertIn("Quanto fica o plano de 200 provas?", pedido)
            self.assertLessEqual(timeout, resposta_jev.TIMEOUT)
            # mesma última mensagem: não chama de novo
            r2 = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
            self.assertTrue(r2["cache"])
            self.assertEqual(r["id"], r2["id"])
            self.assertEqual(1, len(self.chamadas))
            # gerar outra: nova chamada, anterior vira descartada
            r3 = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA, nova=True)
            self.assertNotEqual(r["id"], r3["id"])
            self.assertEqual(2, len(self.chamadas))
            self.assertIn("alternativa diferente", self.chamadas[1][1])
        self.assertEqual("descartada", self.c.execute("SELECT resultado FROM resposta_sugestao WHERE id=?", (r["id"],)).fetchone()[0])

    def test_valor_fora_da_tabela_vira_alerta(self):
        with patch.object(resposta_jev, "_claude", self.claude_fake('{"resposta": "Faço por R$ 123 pra você", "porque": "x"}')):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
        self.assertIn("R$ 123", r["alerta"])
        self.assertEqual("", resposta_jev.confere_valores("Escala sai R$ 369/mês e o Volume 2.500 R$ 1.499"))

    def test_ia_fora_do_ar_mensagem_amigavel(self):
        def falha(*a):
            raise RuntimeError("HTTP 529")
        with patch.object(resposta_jev, "_claude", falha), patch.object(resposta_jev, "_gemini", falha):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
        self.assertIn("não conseguiu sugerir", r["erro"])
        self.assertEqual(0, self.c.execute("SELECT count(*) FROM resposta_sugestao").fetchone()[0])

    def test_claude_falha_cai_no_gemini(self):
        def falha(*a):
            raise RuntimeError("sem crédito")
        with patch.object(resposta_jev, "_claude", falha), \
                patch.object(resposta_jev, "_gemini", lambda *a: ('{"resposta":"Oi!","porque":"p"}', "gemini-2.5-flash")):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: None)
        self.assertEqual(("Oi!", "gemini-2.5-flash"), (r["resposta"], r["modelo"]))

    def test_enviar_igual_a_sugestao_e_editada(self):
        with patch.object(resposta_jev, "_claude", self.claude_fake()):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
        with patch.object(painel, "envia_texto") as envia:
            out = painel.envia_pela_jornada(CID, r["resposta"], "dione", r["id"])
        envia.assert_called_once_with(CID, "5511987654321", r["resposta"], "Dione")
        self.assertEqual("enviada", out["resultado"])
        self.assertEqual("nos", self.c.execute("SELECT ultimo_de FROM leads WHERE chatid=?", (CID,)).fetchone()[0])
        self.assertTrue(self.c.execute("SELECT 1 FROM conversas_vistas WHERE chatid=? AND usuario='dione'", (CID,)).fetchone())
        # nova mensagem do cliente -> nova sugestão; Dione edita antes de mandar
        self.c.execute("INSERT INTO mensagens(messageid,chatid,ts,from_me,tipo,texto) VALUES('m5',?,?,0,'Conversation','E o de 500?')", (CID, ms(16, 12)))
        self.c.commit()
        with patch.object(resposta_jev, "_claude", self.claude_fake('{"resposta":"O Escala sai R$ 369/mês.","porque":"p"}')):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
            self.assertFalse(r["cache"])
        with patch.object(painel, "envia_texto"):
            out = painel.envia_pela_jornada(CID, "O Escala sai R$ 369/mês, com 500 provas 😉", "lucas", r["id"])
        self.assertEqual("editada", out["resultado"])
        linha = self.c.execute("SELECT resultado, texto_enviado FROM resposta_sugestao WHERE id=?", (r["id"],)).fetchone()
        self.assertEqual("editada", linha[0])
        self.assertIn("500 provas", linha[1])

    def test_envio_bloqueado(self):
        with patch.object(painel, "envia_texto") as envia:
            for args, erro in [((CID, "  ", "dione"), ValueError), ((GID, "oi", "dione"), ValueError),
                               (("5511000000000@s.whatsapp.net", "oi", "dione"), ValueError),
                               ((CID, "oi", "visitante"), PermissionError), ((CID, "x" * 4001, "dione"), ValueError)]:
                with self.assertRaises(erro):
                    painel.envia_pela_jornada(*args)
            envia.assert_not_called()
        # falha na Uazapi: não marca como respondido
        with patch.object(painel, "envia_texto", side_effect=RuntimeError("WhatsApp indisponível")):
            with self.assertRaises(RuntimeError):
                painel.envia_pela_jornada(CID, "oi", "dione")
        self.assertEqual("lead", self.c.execute("SELECT ultimo_de FROM leads WHERE chatid=?", (CID,)).fetchone()[0])

    def test_descartar(self):
        with patch.object(resposta_jev, "_claude", self.claude_fake()):
            r = resposta_jev.sugere(self.c, "dione", CID, lambda: JORNADA)
        self.assertEqual("descartada", resposta_jev.decide(self.c, r["id"], "descartada"))
        self.assertIsNone(resposta_jev.decide(self.c, "x", "descartada"))
        json.dumps(r)


if __name__ == "__main__":
    unittest.main()
