from unittest.mock import patch
from test_busca import BuscaTest
import painel

class PlanoFechadoTest(BuscaTest):
    def test_valida_antes_de_converter(self):
        with patch.object(painel.CRM_CLIENT, "change") as change:
            for plan, value in [("Inexistente",3900),("Essencial",0),("Essencial",True),("Essencial",39.1)]:
                with self.assertRaises(ValueError):
                    painel.salva_plano_fechado("a",plan,value)
            change.assert_not_called()

    def test_salva_edita_e_preserva_data_de_fechamento(self):
        with patch.object(painel.CRM_CLIENT,"change",return_value={"id":"crm-a"}):
            painel.salva_plano_fechado("a","Essencial",3500)
            first=painel.fila(chatid="a")[0]["venda"]
            painel.salva_plano_fechado("a","Profissional",15900)
        saved=painel.fila(chatid="a")[0]["venda"]
        self.assertEqual("Profissional",saved["plano"])
        self.assertEqual(15900,saved["valor_centavos"])
        self.assertEqual(first["fechado_em"],saved["fechado_em"])
        self.assertEqual("crm-a",saved["lead_id"])

    def test_plano_personalizado(self):
        with patch.object(painel.CRM_CLIENT,"change",return_value={"id":"crm-a"}):
            painel.salva_plano_fechado("a","Personalizado — 1.000 provas",207200)
        saved=painel.fila(chatid="a")[0]["venda"]
        self.assertEqual("Personalizado — 1.000 provas",saved["plano"])
        self.assertEqual(207200,saved["valor_centavos"])
        for ruim in ["Personalizadox","Personal","Personalizado — "+"x"*90, None]:
            self.assertIsNone(painel.plano_valido(ruim))

    def test_falha_crm_nao_salva_plano(self):
        with patch.object(painel.CRM_CLIENT,"change",side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):painel.salva_plano_fechado("a","Essencial",3900)
        self.assertIsNone(painel.fila(chatid="a")[0]["venda"])

    def test_audio_conta_so_envio_real_bem_sucedido(self):
        painel.envia_midia_atendimento(lambda: {}, "5511987654321", "Dione", teste=True)
        self.assertEqual(0,painel.con().execute("SELECT count(*) FROM atendimentos_iniciados").fetchone()[0])
        painel.envia_midia_atendimento(lambda: {}, "5511987654321", "Dione")
        painel.envia_midia_atendimento(lambda: {}, "5511987654321", "Dione")
        self.assertEqual(1,painel.con().execute("SELECT count(*) FROM atendimentos_iniciados").fetchone()[0])

    def test_migracao_preserva_envios_e_ignora_atribuicoes(self):
        c=painel.con()
        c.execute("DELETE FROM metricas_migracoes")
        c.execute("INSERT INTO conversas_iniciadas VALUES('a',1789434000,'Dione')")
        c.execute("INSERT INTO conversas_atribuidas VALUES('b','Lucas',1789434000)")
        c.commit()
        painel.cria_banco()
        painel.cria_banco()
        rows=c.execute("SELECT chatid,responsavel FROM atendimentos_iniciados").fetchall()
        self.assertEqual([('a','Dione')],[(r[0],r[1]) for r in rows])

    def test_dados_do_lead_expoem_etapas_do_pipeline_principal(self):
        with patch.object(painel.CRM_CLIENT,"details",return_value={"lead":{"status":"meta"}}):
            data=painel.dados_pipeline("a")
        self.assertEqual(set(painel.STATUS),set(data["pipeline"]["etapas"]))
        self.assertEqual("INTERESSADO",data["pipeline"]["status"])
        self.assertNotIn("novo_tiktok",data["pipeline"]["etapas"])

    def test_dados_movem_etapa_nova_e_rejeitam_etapa_antiga(self):
        with patch.object(painel.CRM_CLIENT,"change",return_value={"id":"crm-a"}) as change, patch.object(painel,"dados_pipeline",return_value={}):
            painel.move_pipeline_dados("a","EM CONVERSA")
            change.assert_called_once_with("a","respondeu",origem="manual",por=None)
            with self.assertRaises(ValueError):painel.move_pipeline_dados("a","novo_tiktok")
            change.assert_called_once()
