import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import ChatPipeline from "./pages/ChatPipeline";
import Pipeline from "./pages/Pipeline";
import Leads from "./pages/Leads";
import Dashboard from "./pages/Dashboard";
import Objecoes from "./pages/Objecoes";
import Metas from "./pages/Metas";
import Atendimento from "./pages/Atendimento";
import MensagensPersonalizadas from "./pages/MensagensPersonalizadas";
import TrafegoPago from "./pages/TrafegoPago";
import TestesGratis from "./pages/TestesGratis";
import Comissoes from "./pages/Comissoes";
import Tarefas from "./pages/Tarefas";
import Assistente from "./pages/Assistente";
import Jornada from "./pages/Jornada";
import LeadDetalhe from "./pages/LeadDetalhe";

export default function App() {
  return (
    <BrowserRouter basename="/crm">
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Dashboard />} />
          <Route path="/pipeline" element={<ChatPipeline />} />
          <Route path="/pipeline/anterior" element={<Pipeline />} />
          <Route path="/testes-gratis" element={<TestesGratis />} />
          <Route path="/leads" element={<Leads />} />
          <Route path="/leads/:id" element={<LeadDetalhe />} />
          <Route path="/jornada" element={<Jornada />} />
          <Route path="/objecoes" element={<Objecoes />} />
          <Route path="/trafego-pago" element={<TrafegoPago />} />
          <Route path="/metas" element={<Metas />} />
          <Route path="/atendimento" element={<Atendimento />} />
          <Route path="/mensagens-personalizadas" element={<MensagensPersonalizadas />} />
          <Route path="/comissoes" element={<Comissoes />} />
          <Route path="/tarefas" element={<Tarefas />} />
          <Route path="/assistente" element={<Assistente />} />
          {/* Compat: rota antiga /dashboard ainda funciona */}
          <Route path="/dashboard" element={<Dashboard />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
