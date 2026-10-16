"""Jornada do lead: painel.db temporário + CRM simulado (nada vai pra rede)."""
import os
import sqlite3
import tempfile
import threading
import time
import unittest
from datetime import datetime
from unittest.mock import patch

import jornada
import painel
from crm_bridge import CRM
from historico_lead import BRT

CID = "5511987654321@s.whatsapp.net"
GID = "120363000000000001@g.us"
LEAD = "11111111-2222-3333-4444-555555555555"
STORE = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
AGORA = datetime(2026, 10, 16, 12, 0, tzinfo=BRT)


def ms(dia, hora, minuto=0):
    return int(datetime(2026, 10, dia, hora, minuto, tzinfo=BRT).timestamp() * 1000)


class FakeCRM:
    def __init__(self, responsavel="Dione", rpc_falha=False, teste_30d=True):
        self.responsavel, self.rpc_falha, self.teste_30d = responsavel, rpc_falha, teste_30d
        self.chamadas = []

    def request(self, table, query=None, method="GET", body=None, prefer=None):
        self.chamadas.append(table)
        if method != "GET" and not table.startswith("rpc/"):
            raise AssertionError("a jornada não pode escrever no Supabase")
        if table == "leads":
            return [{"id": LEAD, "nome_loja": "Ótica Visão Clara", "telefone": "11987654321", "whatsapp": None,
                     "email": "dono@exemplo.com", "created_at": "2026-10-01T12:00:00+00:00", "updated_at": "2026-10-15T12:00:00+00:00",
                     "status": "passou_prazo", "responsavel": self.responsavel, "fonte_oportunidade": "Meta",
                     "teste_gratis_em": None, "retomar_em": None, "motivo_perda": None, "tentativas": 2,
                     "notas": "Registrado pelo PL Atendimento. Instagram não informado.\n"
                              "03/10/2026: catálogo criado pelo agente — provoulevou.com.br/catalogo/?loja=visaoclara\n"
                              "13/10/2026: movido para Teste parado (sem prova nos últimos 3 dias)."}]
        if table == "pl_catalog_stores":
            return [{"id": STORE, "slug": "visaoclara", "display_name": "Ótica Visão Clara", "owner_email": "dono@exemplo.com",
                     "whatsapp": "5511987654321", "created_at": "2026-10-03T13:00:00+00:00",
                     "entregue_em": "2026-10-04T15:00:00+00:00", "teste_30d": self.teste_30d}]
        if table == "interacoes":
            return [{"tipo": "nota", "conteudo": "Prefere falar à tarde", "created_at": "2026-10-02T18:00:00+00:00"}]
        if table == "pl_catalog_products":
            return [{"created_at": "2026-10-05T14:00:00+00:00"}, {"created_at": "2026-10-05T15:00:00+00:00"}]
        if table == "rpc/crm_jornada_loja":
            if self.rpc_falha:
                raise RuntimeError("função não existe")
            assert body["p_chave"] == "chave-teste" and body["p_lead_id"] == LEAD
            return {"store": {"id": STORE, "slug": "visaoclara", "nome": "Ótica Visão Clara", "criado_em": "2026-10-03T13:00:00+00:00",
                              "entregue_em": "2026-10-04T15:00:00+00:00", "teste_30d": self.teste_30d},
                    "onboarding": {"criado_em": "2026-10-03T13:01:00+00:00", "criado_por": "agente", "tem_grupo": True},
                    "produtos_por_dia": [{"dia": "2026-10-05", "n": 12}],
                    "provas_por_dia": [{"dia": "2026-10-06", "n": 5}, {"dia": "2026-10-08", "n": 2}],
                    "conta": {"status": "Teste Gratuito", "plano": "Starter"},
                    "pagamentos": [{"data": "2026-10-14", "tipo": "mensalidade", "valor": 147}],
                    "cobrancas": [{"criado_em": "2026-10-13T20:00:00+00:00", "aprovado_em": "2026-10-14T10:00:00+00:00",
                                   "status": "approved", "valor": 147, "tipo": "plano", "plano": "Crescimento"}],
                    "envios": [{"dia": 7, "etapa": "montagem_7", "agendado_para": "2026-10-10", "status": "enviado",
                                "enviado_em": "2026-10-10T12:00:00+00:00", "texto": "Já cadastrou seus produtos?"},
                               {"dia": 14, "etapa": "montagem_14", "agendado_para": "2026-10-17", "status": "agendado"}]}
        if table == "rpc/crm_jornada_catalogos_30d":
            raise RuntimeError("função não existe")
        raise AssertionError("tabela inesperada: " + table)


class JornadaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_db, self.old_local = painel.DB, painel._local
        painel.DB = os.path.join(self.tmp.name, "painel.db")
        painel._local = threading.local()
        painel.cria_banco()
        jornada._CACHE["stores"] = (0.0, None)
        c = self.c = painel.con()
        c.execute("INSERT INTO leads(chatid,fone,nome,status,ultimo_ts,ultimo_de,atualizado,oculto,responsavel) VALUES(?,?,?,?,?,?,?,?,?)",
                  (CID, "5511987654321", "Ótica Visão Clara", "TESTE PARADO", ms(15, 10), "lead", "", 0, "Dione"))
        msgs = [("m1", CID, ms(1, 9), 0, "Conversation", "Oi! Gostaria de saber mais sobre o Provou Catálogo!", None),
                ("m2", CID, ms(1, 9, 10), 1, "ExtendedTextMessage", "Olá! Onde você vende hoje?", None),
                ("m3", CID, ms(1, 9, 30), 0, "AudioMessage", "", 12),
                ("m4", CID, ms(1, 9, 50), 1, "Conversation", "Perfeito, vou montar seu catálogo", None),
                ("m5", CID, ms(3, 14), 1, "Conversation", "Aqui vai o seu acesso: provoulevou.com.br/catalogo/painel 🔑", None),
                ("m6", CID, ms(3, 14, 1), 0, "ReactionMessage", "👍", None),
                ("m7", CID, ms(15, 10), 0, "Conversation", "Vou ver com meu sócio", None),
                ("g1", GID, ms(6, 11), 1, "Conversation", "Novo cliente provou o óculos X", None),
                ("g2", GID, ms(6, 12), 1, "Conversation", "Novo cliente provou o óculos Y", None),
                ("g3", GID, ms(7, 9), 0, "Conversation", "Adorei!", None)]
        c.executemany("INSERT INTO mensagens(messageid,chatid,ts,from_me,tipo,texto,segundos) VALUES(?,?,?,?,?,?,?)", msgs)
        c.execute("INSERT INTO grupos_catalogos(chatid,lead_chatid,nome,responsavel) VALUES(?,?,?,?)",
                  (GID, CID, "Provou Levou & Ótica Visão Clara", "Dione"))
        c.execute("INSERT INTO conversas_atribuidas VALUES(?,?,?)", (CID, "Dione", ms(1, 9, 5) // 1000))
        c.execute("INSERT INTO etapa_historico(chatid,de,para,ts,origem,por) VALUES(?,?,?,?,?,?)",
                  (CID, "NOVO", "EM CONVERSA", ms(1, 9, 31) // 1000, "jev", "Jev"))
        c.execute("INSERT INTO etapa_historico(chatid,de,para,ts,origem,por) VALUES(?,?,?,?,?,?)",
                  (CID, "EM CONVERSA", "AGUARDANDO DADOS", ms(1, 10) // 1000, "manual", "Dione"))
        c.execute("INSERT INTO etapa_historico(chatid,de,para,ts,origem,por) VALUES(?,?,?,?,?,?)",
                  (CID, "EM TESTE", "TESTE PARADO", ms(13, 3) // 1000, "crm", None))
        c.execute("INSERT INTO tarefas(id,dono,titulo,notas,prazo,prioridade,feita,estado,criada_em,atualizada_em) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ("t1", "Dione", "Cobrar cadastro da Ótica Visão Clara", "", "2026-10-18", "normal", 0, "a_fazer",
                   "2026-10-15T09:00:00-03:00", "2026-10-15T09:00:00-03:00"))
        c.commit()

    def tearDown(self):
        painel.DB, painel._local = self.old_db, self.old_local
        self.tmp.cleanup()

    def roda(self, usuario="dione", crm=None, **kw):
        with patch.dict(os.environ, {"PL_IA_KEY": "chave-teste"}):
            return jornada.jornada(self.c, crm or FakeCRM(), usuario, CID, agora=AGORA, **kw)

    def de(self, j, tipo):
        return [e for e in j["eventos"] if e["tipo"] == tipo]

    def test_linha_do_tempo_completa(self):
        j = self.roda()
        cats = {e["cat"] for e in j["eventos"]}
        self.assertTrue({"mensagens", "etapas", "catalogo", "financeiro", "notas", "responsavel", "lead"} <= cats)
        self.assertEqual(sorted(e["ts"] for e in j["eventos"]), [e["ts"] for e in j["eventos"]])
        # mensagens: reação some, áudio vira rótulo, grupo entra (Dione é dona), provas não viram mensagem
        msgs = [e for e in j["eventos"] if e["cat"] == "mensagens"]
        self.assertEqual(7, len(msgs))
        self.assertIn("[áudio de 12s]", [e["detalhe"] for e in msgs])
        self.assertTrue(any(e["canal"] == "grupo" and e["quem"] == "lead" for e in msgs))
        self.assertFalse(any("novo cliente provou" in e["detalhe"].lower() for e in msgs))
        r = j["resumo"]
        self.assertEqual((3, 3, 1), (r["msgs_nossas"], r["msgs_dele"], r["msgs_dele_grupo"]))
        self.assertEqual("15 min", r["resposta_nossa_mediana"])          # 10 e 20 min
        self.assertEqual(15, r["dias_desde_entrada"])
        self.assertEqual("TESTE PARADO", r["etapa"])
        self.assertEqual("13/10/2026", r["etapa_desde"])
        self.assertEqual(3, r["dias_na_etapa"])
        self.assertEqual("Dione", r["responsavel"])
        self.assertEqual("lead", r["ultima_interacao"]["quem"])
        self.assertEqual(7, r["provas"])
        # etapas: Jev, manual com autor, automático da nota (o 'crm' do mesmo dia não duplica)
        self.assertEqual("Jev", self.de(j, "etapa_jev")[0]["quem_rotulo"])
        self.assertEqual("Dione", self.de(j, "etapa_manual")[0]["quem_rotulo"])
        self.assertEqual(1, len(self.de(j, "etapa_auto")))
        self.assertEqual("sem prova nos últimos 3 dias", self.de(j, "etapa_auto")[0]["detalhe"])
        self.assertEqual([], self.de(j, "etapa_crm"))
        # catálogo e régua dos 30 dias
        self.assertEqual("Catálogo criado", self.de(j, "catalogo")[0]["titulo"])
        self.assertEqual("Agente de catálogos", self.de(j, "catalogo")[0]["quem_rotulo"])
        self.assertEqual(1, len(self.de(j, "acesso")))
        env = self.de(j, "envio_auto")[0]
        self.assertEqual(("sistema", "grupo", "enviado"), (env["quem"], env["canal"], env["status"]))
        self.assertEqual("Já cadastrou seus produtos?", env["texto"])
        rg = j["regua"]
        self.assertEqual(("04/10/2026", 13, "montagem"), (rg["entregue_em"], rg["dia_atual"], rg["fase"]))
        self.assertEqual(["enviado", "agendado", "previsto", "previsto", "previsto"], [m["status"] for m in rg["mensagens"]])
        self.assertEqual("2026-10-24", rg["mensagens"][2]["data"])      # dia 21 = entrega + 20
        self.assertEqual("2026-10-17", r["proximos"][0]["data"])
        self.assertIn("Tarefa: Cobrar cadastro da Ótica Visão Clara", [p["titulo"] for p in r["proximos"]])
        # financeiro: a lead é da Dione, então ela vê
        self.assertEqual(1, len(self.de(j, "cobranca")))
        self.assertEqual(1, len(self.de(j, "pagamento")))
        self.assertFalse(r["financeiro_oculto"])
        self.assertTrue(j["fontes"]["rpc"])
        self.assertEqual(GID, j["lead"]["grupo"]["chatid"])
        self.assertLess(j["ms"], 1500)

    def test_visibilidade_igual_a_de_hoje(self):
        self.c.execute("UPDATE leads SET responsavel='Lucas' WHERE chatid=?", (CID,))
        self.c.commit()
        j = self.roda("dione", FakeCRM(responsavel="Lucas"))
        self.assertIsNone(j["lead"]["grupo"])                       # grupo do Lucas: a Dione não vê
        self.assertFalse(any(e["canal"] == "grupo" and e["cat"] == "mensagens" for e in j["eventos"]))
        self.assertTrue(j["resumo"]["financeiro_oculto"])
        self.assertEqual([], self.de(j, "cobranca") + self.de(j, "pagamento"))
        self.assertEqual(1, len(self.de(j, "tarefa")))              # a tarefa é dela: continua vendo
        j = self.roda("lucas", FakeCRM(responsavel="Lucas"))
        self.assertEqual(GID, j["lead"]["grupo"]["chatid"])
        self.assertEqual(1, len(self.de(j, "cobranca")))
        self.assertEqual([], self.de(j, "tarefa"))                  # tarefa é da Dione
        with self.assertRaises(ValueError):
            jornada.jornada(self.c, FakeCRM(), "dione", "x' OR 1=1", agora=AGORA)

    def test_sem_rpc_usa_o_que_a_anon_le(self):
        crm = FakeCRM(rpc_falha=True)
        j = self.roda(crm=crm)
        self.assertFalse(j["fontes"]["rpc"])
        self.assertTrue(j["fontes"]["avisos"])
        self.assertEqual(2, j["resumo"]["provas"])                  # contadas pelo grupo
        self.assertEqual(2, self.de(j, "produtos")[0]["n"])        # pl_catalog_products pela anon
        self.assertEqual([], self.de(j, "envio_auto"))
        self.assertEqual(["sem registro"] + ["previsto"] * 4, [m["status"] for m in j["regua"]["mensagens"]])

    def test_por_crm_id_sem_conversa_e_por_grupo(self):
        with patch.dict(os.environ, {"PL_IA_KEY": "chave-teste"}):
            j = jornada.jornada(self.c, FakeCRM(), "dione", None, LEAD, agora=AGORA)
            self.assertEqual(CID, j["lead"]["chatid"])            # achou a conversa pelo telefone
            j = jornada.jornada(self.c, FakeCRM(), "dione", GID, agora=AGORA)
            self.assertEqual(CID, j["lead"]["chatid"])
            with self.assertRaises(ValueError):
                jornada.jornada(self.c, FakeCRM(), "lucas2", GID, agora=AGORA)

    def test_rapido_com_conversa_longa(self):
        self.c.executemany("INSERT INTO mensagens(messageid,chatid,ts,from_me,tipo,texto) VALUES(?,?,?,?,?,?)",
                           [("x%d" % i, CID, ms(2, 0) + i * 60000, i % 2, "Conversation", "mensagem %d" % i) for i in range(4000)])
        self.c.commit()
        t = time.monotonic()
        j = self.roda()
        self.assertLess(time.monotonic() - t, 1.5)
        self.assertGreater(j["resumo"]["msgs_nossas"], 2000)

    def test_catalogos_30d_sem_rpc_calcula_proxima_mensagem(self):
        with patch.dict(os.environ, {"PL_IA_KEY": "chave-teste"}):
            d = jornada.catalogos_30d(FakeCRM(), "dione", AGORA)
        self.assertFalse(d["rpc"])
        it = d["itens"][0]
        self.assertEqual((13, "montagem"), (it["dia_atual"], it["fase"]))
        self.assertEqual({"dia": 14, "rotulo": "Montagem · dia 14", "data": "2026-10-17", "status": "previsto"}, it["proximo"])


class EtapaHistoricoTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE leads(chatid TEXT, fone TEXT, nome TEXT, status TEXT, oculto INTEGER, ultimo_ts INTEGER)")
        self.db.execute("INSERT INTO leads VALUES(?,?,?,?,0,1)", (CID, "5511987654321", "Loja", "NOVO"))
        self.crm = CRM(lambda: self.db)
        self.crm.setup()
        self.status = "interessado"
        self.crm.request = self.remote

    def remote(self, table, query=None, method="GET", body=None, prefer=None):
        if table == "leads" and method == "PATCH":
            self.status = body["status"]
            return None
        if table == "leads":
            if "select" in (query or {}) and query["select"] == "id,status":
                return [{"id": LEAD, "status": self.status}]
            return [{"id": LEAD, "status": self.status, "nome_loja": "Loja"}]
        if table == "crm_lead_etapas":
            return []
        raise AssertionError(table)

    def linhas(self):
        return [tuple(r) for r in self.db.execute("SELECT de, para, origem, por FROM etapa_historico ORDER BY id")]

    def test_registra_manual_e_mudanca_vinda_do_crm(self):
        self.db.execute("INSERT INTO crm_links VALUES(?,?)", (CID, LEAD))
        self.db.commit()
        self.crm.ensure(CID)                                        # CRM já estava em Interessado
        self.crm.change(CID, "testando", origem="manual", por="Dione")
        self.status = "testando_ativo"                              # rotina do funil mexeu lá
        self.crm.pull_statuses()
        self.crm.pull_statuses()                                    # sem mudança: não repete
        self.assertEqual([("NOVO", "INTERESSADO", "crm", None), ("INTERESSADO", "AGUARDANDO DADOS", "manual", "Dione"),
                          ("AGUARDANDO DADOS", "EM TESTE", "crm", None)], self.linhas())

    def test_mover_do_painel_grava_autor(self):
        tmp = tempfile.TemporaryDirectory()
        old = painel.DB, painel._local
        painel.DB = os.path.join(tmp.name, "painel.db")
        painel._local = threading.local()
        try:
            painel.cria_banco()
            c = painel.con()
            c.execute("INSERT INTO leads(chatid,fone,nome,status,ultimo_ts) VALUES(?,?,?,?,1)", (CID, "5511987654321", "Loja", "NOVO"))
            c.commit()
            with patch.object(painel.CRM_CLIENT, "change") as change, patch.object(painel.CRM_CLIENT, "details", return_value={}):
                painel.move_pipeline_dados(CID, "INTERESSADO", por="Dione")
                painel.move_pipeline_dados(CID, "EM CONVERSA", origem="jev", por="Jev")
            self.assertEqual(("manual", "Dione"), (change.call_args_list[0].kwargs["origem"], change.call_args_list[0].kwargs["por"]))
            self.assertEqual("jev", change.call_args_list[1].kwargs["origem"])
        finally:
            painel.DB, painel._local = old
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
