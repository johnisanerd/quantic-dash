import { useEffect, useState } from "react";
import { useParams, useNavigate, Link } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { applyCustomLeadStatus, persistLeadStatus } from "../lib/lead-status";
import type { Lead, Interacao, LeadStatus } from "../types";
import StatusBadge from "../components/StatusBadge";
import InteracaoForm from "../components/InteracaoForm";
import DataTesteGratis from "../components/DataTesteGratis";

const TIPO_LABELS: Record<string, string> = {
  dm_enviada: "DM Enviada",
  resposta: "Resposta",
  follow_up: "Follow-up",
  nota: "Nota",
};

const TIPO_ACCENT: Record<string, string> = {
  dm_enviada: "text-cyan",
  resposta: "text-amber",
  follow_up: "text-violet-light",
  nota: "text-dim",
};

export default function LeadDetalhe() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [lead, setLead] = useState<Lead | null>(null);
  const [interacoes, setInteracoes] = useState<Interacao[]>([]);
  const [notas, setNotas] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => { if (id) { fetchLead(); fetchInteracoes(); } }, [id]);

  async function fetchLead() {
    setLoading(true);
    const { data } = await supabase.from("leads").select("*").eq("id", id).single();
    if (data) { setLead(await applyCustomLeadStatus(data)); setNotas(data.notas ?? ""); }
    setLoading(false);
  }

  async function fetchInteracoes() {
    const { data } = await supabase.from("interacoes").select("*").eq("lead_id", id).order("created_at", { ascending: false });
    setInteracoes(data ?? []);
  }

  async function updateStatus(status: LeadStatus) {
    if (!id) return;
    await persistLeadStatus(id, status);
    await fetchLead();
  }

  async function salvarNotas() {
    await supabase.from("leads").update({ notas }).eq("id", id);
  }

  async function deletarLead() {
    if (!confirm("Tem certeza que quer deletar esse lead?")) return;
    await supabase.from("interacoes").delete().eq("lead_id", id);
    await supabase.from("leads").delete().eq("id", id);
    navigate("/");
  }

  if (loading) return <div className="flex items-center justify-center h-full"><div className="w-5 h-5 border-2 border-violet border-t-transparent rounded-full animate-spin" /></div>;
  if (!lead) return <div className="flex items-center justify-center h-full"><p className="text-dim text-sm">Lead nao encontrado.</p></div>;

  return (
    <div className="p-8 max-w-3xl">
      {/* Back */}
      <button onClick={() => navigate(-1)} className="flex items-center gap-1.5 text-dim hover:text-sub text-xs mb-6 transition-colors group">
        <svg className="w-3.5 h-3.5 group-hover:-translate-x-0.5 transition-transform" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
          <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Voltar
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6 stagger-in">
        <div>
          <h1 className="text-[22px] font-bold text-bright tracking-tight">
            {lead.nome_loja || `@${lead.instagram}`}
          </h1>
          <div className="flex items-center gap-2 mt-1.5">
            <span className="text-muted text-xs">@{lead.instagram}</span>
            <span className="text-edge text-xs">/</span>
            <span className="text-muted text-xs tabular-nums">{lead.seguidores.toLocaleString("pt-BR")} seguidores</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={lead.status} onChange={updateStatus} />
          <button
            onClick={deletarLead}
            className="text-dim hover:text-rose text-xs p-1.5 rounded-lg hover:bg-rose/10 transition-all"
            title="Deletar lead"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
            </svg>
          </button>
        </div>
      </div>

      {/* Actions */}
      <div className="flex gap-2 mb-8 stagger-in" style={{ animationDelay: "50ms" }}>
        <Link
          to={`/jornada?crm_id=${lead.id}`}
          className="flex items-center gap-2 bg-violet text-white text-xs font-semibold px-3.5 py-2 rounded-lg transition-all"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"><circle cx="3.5" cy="3.5" r="1.75" /><circle cx="12.5" cy="12.5" r="1.75" /><path d="M5.25 3.5H10a2.5 2.5 0 0 1 0 5H6a2.5 2.5 0 0 0 0 5h4.75" /></svg>
          Jornada
        </Link>
        <a
          href={`https://instagram.com/${lead.instagram}`}
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2 bg-surface border border-edge-subtle hover:border-edge text-xs font-medium text-sub hover:text-bright px-3.5 py-2 rounded-lg transition-all"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.163c3.204 0 3.584.012 4.85.07 3.252.148 4.771 1.691 4.919 4.919.058 1.265.069 1.645.069 4.849 0 3.205-.012 3.584-.069 4.849-.149 3.225-1.664 4.771-4.919 4.919-1.266.058-1.644.07-4.85.07-3.204 0-3.584-.012-4.849-.07-3.26-.149-4.771-1.699-4.919-4.92-.058-1.265-.07-1.644-.07-4.849 0-3.204.013-3.583.07-4.849.149-3.227 1.664-4.771 4.919-4.919 1.266-.057 1.645-.069 4.849-.069zm0-2.163c-3.259 0-3.667.014-4.947.072-4.358.2-6.78 2.618-6.98 6.98-.059 1.281-.073 1.689-.073 4.948 0 3.259.014 3.668.072 4.948.2 4.358 2.618 6.78 6.98 6.98 1.281.058 1.689.072 4.948.072 3.259 0 3.668-.014 4.948-.072 4.354-.2 6.782-2.618 6.979-6.98.059-1.28.073-1.689.073-4.948 0-3.259-.014-3.667-.072-4.947-.196-4.354-2.617-6.78-6.979-6.98-1.281-.059-1.69-.073-4.949-.073zm0 5.838c-3.403 0-6.162 2.759-6.162 6.162s2.759 6.163 6.162 6.163 6.162-2.759 6.162-6.163c0-3.403-2.759-6.162-6.162-6.162zm0 10.162c-2.209 0-4-1.79-4-4 0-2.209 1.791-4 4-4s4 1.791 4 4c0 2.21-1.791 4-4 4zm6.406-11.845c-.796 0-1.441.645-1.441 1.44s.645 1.44 1.441 1.44c.795 0 1.439-.645 1.439-1.44s-.644-1.44-1.439-1.44z"/></svg>
          Instagram
        </a>
        {lead.site && (
          <a
            href={lead.site}
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-2 bg-surface border border-edge-subtle hover:border-edge text-xs font-medium text-sub hover:text-bright px-3.5 py-2 rounded-lg transition-all"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path strokeLinecap="round" strokeLinejoin="round" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1" /></svg>
            Site
          </a>
        )}
      </div>

      {/* Observações do chat de prospecção (interações tipo "nota") */}
      {interacoes.some((i) => i.tipo === "nota") && (
        <div className="mb-8 stagger-in" style={{ animationDelay: "80ms" }}>
          <label className="text-[10px] font-semibold text-dim uppercase tracking-widest mb-2 block">Observações do chat</label>
          <div className="space-y-2">
            {interacoes.filter((i) => i.tipo === "nota").map((int) => (
              <div key={int.id} className="bg-surface border border-edge-subtle rounded-lg px-3.5 py-2.5">
                <p className="text-xs text-sub leading-relaxed whitespace-pre-wrap">{int.conteudo}</p>
                <span className="text-[10px] text-dim mt-1 block">{new Date(int.created_at).toLocaleString("pt-BR")}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Notas */}
      <DataTesteGratis leadId={lead.id} value={lead.teste_gratis_em} onSaved={fetchLead} />
      <div className="mb-8 stagger-in" style={{ animationDelay: "100ms" }}>
        <label className="text-[10px] font-semibold text-dim uppercase tracking-widest mb-2 block">Notas</label>
        <textarea
          value={notas}
          onChange={(e) => setNotas(e.target.value)}
          onBlur={salvarNotas}
          placeholder="Adicione notas..."
          rows={3}
          className="w-full bg-surface border border-edge-subtle rounded-lg px-3.5 py-2.5 text-xs text-text placeholder:text-dim/50 focus:outline-none focus:border-violet/30 focus:ring-1 focus:ring-violet/10 resize-none transition-all"
        />
      </div>

      {/* Interacoes */}
      <div className="stagger-in" style={{ animationDelay: "150ms" }}>
        <label className="text-[10px] font-semibold text-dim uppercase tracking-widest mb-3 block">Interacoes</label>
        <InteracaoForm leadId={lead.id} onSaved={() => { fetchLead(); fetchInteracoes(); }} />

        <div className="mt-5 space-y-1">
          {interacoes.map((int, i) => (
            <div
              key={int.id}
              className="stagger-in flex items-start gap-3 py-3 border-b border-edge-subtle/40 last:border-0"
              style={{ animationDelay: `${200 + i * 30}ms` }}
            >
              {/* Timeline dot */}
              <div className="mt-1 flex flex-col items-center">
                <div className="w-2 h-2 rounded-full bg-edge" />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className={`text-[11px] font-semibold ${TIPO_ACCENT[int.tipo] ?? "text-dim"}`}>
                    {TIPO_LABELS[int.tipo] ?? int.tipo}
                  </span>
                  <span className="text-[10px] text-dim">
                    {new Date(int.created_at).toLocaleString("pt-BR")}
                  </span>
                </div>
                <p className="text-xs text-sub mt-0.5 leading-relaxed">{int.conteudo}</p>
              </div>
            </div>
          ))}
          {interacoes.length === 0 && (
            <p className="text-dim text-xs py-6 text-center">Nenhuma interacao.</p>
          )}
        </div>
      </div>
    </div>
  );
}
