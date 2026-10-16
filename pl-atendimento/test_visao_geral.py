"""Visão geral da Jornada: painel.db temporário + CRM simulado (nada vai pra rede)."""
import os
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch

import painel
import visao_geral
from historico_lead import BRT

AGORA = datetime(2026, 10, 16, 12, 0, tzinfo=BRT)


def seg(dia, hora=10, minuto=0):
    return int(datetime(2026, 10, dia, hora, minuto, tzinfo=BRT).timestamp())


def cid(n):
    return "55119%08d@s.whatsapp.net" % n


class FakeCRM:
    def __init__(self, leads, cats=None):
        self.leads, self.cats, self.chamadas = leads, cats, []

    def request(self, table, query=None, method="GET", body=None, prefer=None):
        self.chamadas.append(table)
        assert method == "GET" or table.startswith("rpc/"), "a visão geral não pode escrever no Supabase"
        if table == "leads":
            off = int(query.get("offset", 0))
            return self.leads[off:off + int(query["limit"])]
        if table == "rpc/crm_jornada_visao":
            if self.cats is None:
                raise RuntimeError("função não existe")
            assert body["p_chave"] == "chave-teste"
            return self.cats
        if table == "pl_catalog_stores":
            return []
        raise AssertionError(table)


def crm_lead(i, status, resp=None, notas="", **kw):
    return dict({"id": "00000000-0000-0000-0000-%012d" % i, "nome_loja": "Loja %d" % i, "telefone": "119%08d" % i,
                 "whatsapp": None, "status": status, "responsavel": resp, "created_at": "2026-09-20T12:00:00+00:00",
                 "updated_at": "2026-10-01T12:00:00+00:00", "teste_gratis_em": None, "retomar_em": None,
                 "motivo_perda": None, "notas": notas}, **kw)


class VisaoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = painel.DB, painel._local
        painel.DB = os.path.join(self.tmp.name, "painel.db")
        painel._local = threading.local()
        painel.cria_banco()
        visao_geral._CACHE.update({"crm": (0.0, None), "cat": (0.0, None, False)})
        self.c = painel.con()

    def tearDown(self):
        painel.DB, painel._local = self.old
        self.tmp.cleanup()

    def lead(self, n, status, resp, msgs, ultimo_de=None):
        self.c.execute("INSERT INTO leads(chatid,fone,nome,status,responsavel,ultimo_ts,ultimo_de,oculto) VALUES(?,?,?,?,?,?,?,0)",
                       (cid(n), cid(n).split("@")[0], "Loja %d" % n, status, resp, max(t for t, _ in msgs) if msgs else 0,
                        ultimo_de or (("lead" if not msgs[-1][1] else "nos") if msgs else None)))
        self.c.executemany("INSERT INTO mensagens(messageid,chatid,ts,from_me,tipo,texto) VALUES(?,?,?,?,?,?)",
                           [("%d-%d" % (n, k), cid(n), t * 1000, f, "Conversation", "msg %d" % k) for k, (t, f) in enumerate(msgs)])
        self.c.execute("INSERT INTO crm_links VALUES(?,?)", (cid(n), "00000000-0000-0000-0000-%012d" % n))

    def roda(self, usuario, crm):
        with patch.dict(os.environ, {"PL_IA_KEY": "chave-teste"}):
            return visao_geral.visao(self.c, crm, usuario, AGORA)

    def cenario(self):
        # 1: Dione, cliente acabou de falar · 2: Lucas, esperando há 20 dias · 3: sem responsável, teste parado
        # 4: Dione, stand-by com retomar vencido · 5: Dione, Interessado parado 9 dias · 6: Dione, convertido
        self.lead(1, "EM CONVERSA", "Dione", [(seg(16, 9), 1), (seg(16, 11), 0)])
        self.lead(2, "INTERESSADO", "Lucas", [(seg(6, 9), 1), (seg(6, 10), 0)])
        self.lead(3, "TESTE PARADO", None, [(seg(10, 9), 1), (seg(10, 10), 1)])
        self.lead(4, "STAND-BY", "Dione", [(seg(5), 1)])
        self.lead(5, "INTERESSADO", "Dione", [(seg(7), 0), (seg(7, 11), 1)])
        self.lead(6, "CONVERTIDO", "Dione", [(seg(2), 1)])
        self.c.execute("INSERT INTO planos_fechados VALUES(?,?,?,?,?,?)", (cid(6), "x", "Crescimento", 14700, "2026-10-02", "2026-10-02"))
        self.c.execute("INSERT INTO etapa_historico(chatid,de,para,ts,origem,por) VALUES(?,?,?,?,?,?)",
                       (cid(5), "EM CONVERSA", "INTERESSADO", seg(4), "manual", "Dione"))
        self.c.commit()
        leads = [crm_lead(1, "respondeu", "Dione"), crm_lead(2, "interessado", "Lucas"),
                 crm_lead(3, "passou_prazo", None, "13/10/2026: movido para Teste parado (sem produto cadastrado)."),
                 crm_lead(4, "stand_by", "Dione", retomar_em="2026-10-15"), crm_lead(5, "interessado", "Dione"),
                 crm_lead(6, "fechou", "Dione"),
                 crm_lead(7, "testando_ativo", None),            # catálogo sem conversa no painel: entra
                 crm_lead(8, "novo", None),                      # lista fria sem conversa: não entra
                 crm_lead(9, "proposta_enviada", "Lucas")]       # do Lucas: a Dione não vê
        cats = [{"store_id": "s3", "slug": "loja3", "lead_id": leads[2]["id"], "fone8": "", "produtos": 0, "provas": 0,
                 "teste_30d": False, "criado_em": "2026-10-01T12:00:00+00:00", "segunda_chance": "2026-10-16T13:00:00+00:00", "produtos_pos_sc": 2, "provas_pos_sc": 0},
                {"store_id": "s7", "slug": "loja7", "lead_id": leads[6]["id"], "fone8": "", "produtos": 12, "provas": 40,
                 "teste_30d": True, "entregue_em": "2026-10-04T15:00:00+00:00", "criado_em": "2026-10-03T12:00:00+00:00",
                 "cobranca_pendente": {"valor": 147, "criado_em": "2026-10-15T12:00:00+00:00"}}]
        return leads, cats

    def test_dione_ve_os_dela_e_sem_responsavel_priorizados(self):
        leads, cats = self.cenario()
        v = self.roda("dione", FakeCRM(leads, cats))
        ids = [x["crm_id"][-1] for x in v["itens"]]
        self.assertNotIn("2", ids)
        self.assertNotIn("9", ids)
        self.assertNotIn("8", ids)
        self.assertEqual(["1", "4", "7", "3", "5", "6"], ids)
        it = {x["crm_id"][-1]: x for x in v["itens"]}
        self.assertTrue(it["1"]["esperando"])
        self.assertIn("🟢 esperando resposta há 1 h", [s["t"] for s in it["1"]["sinais"]])
        self.assertEqual("Data de retomar o contato chegou", it["4"]["motivo"])
        self.assertEqual("Cobrança gerada e ainda não paga", it["7"]["motivo"])
        self.assertEqual({"📦 12 produtos", "👓 40 provas", "🗓 teste 30d dia 13", "💰 PIX pendente R$ 147,00", "⏰ parado 15 dias"},
                         {s["t"] for s in it["7"]["sinais"]})
        self.assertIsNone(it["7"]["chatid"])
        self.assertIn("🎁 segunda chance 16/10", [s["t"] for s in it["3"]["sinais"]])
        self.assertIn("📦 sem produto", [s["t"] for s in it["3"]["sinais"]])
        self.assertEqual(3, it["3"]["dias_na_etapa"])                    # da nota "movido para Teste parado"
        self.assertEqual(12, it["5"]["dias_na_etapa"])                   # do etapa_historico
        self.assertEqual(9, it["5"]["dias_parado"])
        self.assertEqual("Sem interação há 9 dias (esfriando)", it["5"]["motivo"])
        self.assertEqual(0, it["6"]["prioridade"])
        r = v["resumo"]
        self.assertEqual(6, r["total"])
        self.assertEqual(1, r["esperando"])
        self.assertEqual(1, r["por_etapa"]["INTERESSADO"])                # o 2 é do Lucas
        # parados (Em conversa em diante, sem convertido): 3 (6 dias), 5 (9), 4 (11) e 7 (15, pela data do CRM)
        self.assertEqual((4, 3, 1), (r["parados_3"], r["parados_7"], r["parados_15"]))
        self.assertEqual(1, r["segunda_chance"])
        self.assertEqual((0, 1, 0), (r["sc_responderam"], r["sc_cadastraram"], r["sc_provaram"]))
        self.assertEqual(1, r["teste30"])
        self.assertTrue(it["3"]["catalogo"]["sc_produtos"] == 2 and not it["3"]["catalogo"]["sc_respondeu"])
        self.assertTrue(v["fontes"]["rpc"])

    def test_lucas_ve_todos(self):
        leads, cats = self.cenario()
        v = self.roda("lucas", FakeCRM(leads, cats))
        self.assertEqual(8, v["resumo"]["total"])
        dois = next(x for x in v["itens"] if x["crm_id"].endswith("2"))
        self.assertTrue(dois["esperando"])
        self.assertEqual(400, dois["prioridade"])                          # esperando há 10 dias: esfriando
        with self.assertRaises(PermissionError):
            self.roda("visitante", FakeCRM(leads, cats))

    def test_sem_rpc_continua_funcionando(self):
        leads, _ = self.cenario()
        v = self.roda("dione", FakeCRM(leads, None))
        self.assertFalse(v["fontes"]["rpc"])
        self.assertTrue(v["fontes"]["avisos"])
        self.assertEqual(6, v["resumo"]["total"])
        self.assertFalse(any(s["k"] == "produtos" for x in v["itens"] for s in x["sinais"]))

    def test_rapido_com_1500_leads(self):
        leads = []
        for n in range(1, 1501):
            self.c.execute("INSERT INTO leads(chatid,fone,nome,status,responsavel,ultimo_ts,ultimo_de,oculto) VALUES(?,?,?,?,?,?,?,0)",
                           (cid(n), cid(n).split("@")[0], "Loja %d" % n, "EM CONVERSA", "Dione", seg(15) * 1000, "lead"))
            self.c.executemany("INSERT INTO mensagens(messageid,chatid,ts,from_me,tipo,texto) VALUES(?,?,?,?,?,?)",
                               [("%d-%d" % (n, k), cid(n), (seg(1) + k * 3600 + n) * 1000, k % 2, "Conversation", "oi") for k in range(25)])
            leads.append(crm_lead(n, "respondeu", "Dione"))
        self.c.commit()
        t = time.monotonic()
        v = self.roda("dione", FakeCRM(leads, []))
        self.assertLess(time.monotonic() - t, 2.0)
        self.assertEqual(1500, v["resumo"]["total"])


if __name__ == "__main__":
    unittest.main()
