import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { supabase } from "../lib/supabase";
import { fmtFone, getJson, normFone } from "../lib/jornada";
import JornadaVisao, { type AbrirLead } from "../components/JornadaVisao";
import JornadaLead, { type Jornada } from "../components/JornadaDetalhe";
import Responder from "../components/Responder";

// Aba Jornada: visão geral ("Painel de comando") sempre por baixo; clicar num lead abre a jornada completa
// num painel lateral largo, sem perder a lista. A URL guarda o lead aberto (?lead=<chatid ou id do CRM>).
type Resultado = { key: string; nome: string; fone: string; chatid?: string; crmId?: string; status?: string; responsavel?: string | null; grupo?: boolean };

export default function JornadaPage() {
  const [params, setParams] = useSearchParams();
  // ?lead= (novo) ou ?chatid=&crm_id= (links antigos do Pipeline/LeadDetalhe)
  const lead = params.get("lead") || "";
  const chatid = lead.includes("@") ? lead : params.get("chatid") || "";
  const crmId = !lead.includes("@") && lead ? lead : params.get("crm_id") || "";
  const [busca, setBusca] = useState(""), [resultados, setResultados] = useState<Resultado[]>([]), [buscando, setBuscando] = useState(false);
  const [enviados, setEnviados] = useState<Set<string>>(new Set());
  const onEnviado = useCallback((cid: string) => setEnviados(s => new Set(s).add(cid)), []);

  useEffect(() => {
    const termo = busca.trim();
    if (termo.length < 2) { setResultados([]); return; }
    let vivo = true;
    const t = window.setTimeout(async () => {
      setBuscando(true);
      try {
        const digitos = termo.replace(/\D/g, ""), ehFone = /^[\d\s()+.-]+$/.test(termo) && digitos.length >= 4;
        const safe = termo.replace(/[%,()*]/g, " ").trim();
        const [painel, crm] = await Promise.all([
          getJson<Array<{ chatid: string; nome: string; fone: string; status: string; responsavel: string | null; grupo?: boolean }>>("/api/fila?busca=" + encodeURIComponent(termo)).catch(() => []),
          supabase.from("leads").select("id,nome_loja,telefone,whatsapp,status,responsavel")
            .or(ehFone ? `telefone.ilike.*${digitos}*,whatsapp.ilike.*${digitos}*` : `nome_loja.ilike.*${safe}*`)
            .neq("status", "descartado").order("updated_at", { ascending: false }).limit(15),
        ]);
        const out: Resultado[] = [], vistos = new Map<string, Resultado>();
        for (const p of painel.slice(0, 20)) {
          const tail = p.grupo ? p.chatid : normFone(p.fone).slice(-8);
          const r: Resultado = { key: "p:" + p.chatid, nome: p.nome || fmtFone(p.fone), fone: p.grupo ? "" : p.fone, chatid: p.chatid, status: p.status, responsavel: p.responsavel, grupo: p.grupo };
          vistos.set(tail, r); out.push(r);
        }
        for (const l of (crm.data || []) as Array<{ id: string; nome_loja: string | null; telefone: string | null; whatsapp: string | null; status: string; responsavel: string | null }>) {
          const tail = normFone(l.telefone || l.whatsapp || "").slice(-8), ja = tail.length === 8 ? vistos.get(tail) : undefined;
          if (ja) { ja.crmId = l.id; continue; }
          out.push({ key: "c:" + l.id, nome: l.nome_loja || fmtFone(l.telefone), fone: l.telefone || l.whatsapp || "", crmId: l.id, status: l.status, responsavel: l.responsavel });
        }
        if (vivo) setResultados(out.slice(0, 25));
      } finally { if (vivo) setBuscando(false); }
    }, 300);
    return () => { vivo = false; clearTimeout(t); };
  }, [busca]);

  function abre(r: AbrirLead) {
    const p = new URLSearchParams();
    const id = r.chatid && r.chatid.endsWith("@s.whatsapp.net") ? r.chatid : r.crmId || r.chatid;
    if (id) p.set("lead", id);
    setParams(p); setBusca(""); setResultados([]);
  }
  const fecha = useCallback(() => setParams(new URLSearchParams()), [setParams]);
  const aberto = chatid || crmId;

  return (
    <div className="mx-auto max-w-[1280px] space-y-5 p-4 sm:p-6">
      <header className="flex flex-wrap items-center gap-3">
        <div className="mr-auto">
          <h1 className="text-2xl font-semibold text-bright">Jornada do lead</h1>
          <p className="mt-0.5 text-sm text-muted">Quem precisa de você hoje e tudo o que aconteceu com cada lead.</p>
        </div>
        <div className="relative w-full sm:w-80">
          <label className="flex items-center gap-2 rounded-xl border border-edge bg-raised px-3 py-2 focus-within:border-violet">
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 text-muted"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
            <input value={busca} onChange={e => setBusca(e.target.value)} placeholder="Buscar loja ou telefone…" aria-label="Buscar lead"
              className="min-w-0 flex-1 bg-transparent text-sm text-text placeholder:text-dim focus:outline-none" />
            {buscando && <span className="text-xs text-dim">…</span>}
          </label>
          {resultados.length > 0 && (
            <ul className="absolute right-0 z-30 mt-1 max-h-96 w-full overflow-auto rounded-xl border border-edge bg-raised p-1 shadow-lg sm:w-[420px]" role="listbox">
              {resultados.map(r => (
                <li key={r.key}>
                  <button onClick={() => abre(r)} className="flex w-full items-center gap-3 rounded-lg px-3 py-2 text-left hover:bg-active-bg">
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium text-bright">{r.grupo ? "👥 " : ""}{r.nome}</span>
                      <span className="block text-xs text-muted">{r.grupo ? "grupo do catálogo" : fmtFone(r.fone)}{r.responsavel ? ` · ${r.responsavel}` : ""}</span>
                    </span>
                    {r.status && <span className="shrink-0 rounded-full bg-panel px-2 py-0.5 text-[11px] text-sub">{r.status}</span>}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {busca.trim().length >= 2 && !buscando && !resultados.length && <p className="absolute mt-1 text-xs text-muted">Nenhum lead encontrado.</p>}
        </div>
      </header>

      <JornadaVisao onAbrir={abre} enviados={enviados} onEnviado={onEnviado} aberto={aberto} />
      {aberto && <PainelLead key={aberto} chatid={chatid || null} crmId={crmId || null} onFechar={fecha} onEnviado={onEnviado} />}
    </div>
  );
}

function PainelLead({ chatid, crmId, onFechar, onEnviado }: { chatid: string | null; crmId: string | null; onFechar: () => void; onEnviado: (c: string) => void }) {
  const [j, setJ] = useState<Jornada | null>(null), [responder, setResponder] = useState(false);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onFechar(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onFechar]);
  const conversa = j?.lead.chatid || (chatid && chatid.endsWith("@s.whatsapp.net") ? chatid : null);
  return (
    <>
      <div aria-hidden="true" onClick={onFechar} className="fixed inset-0 z-40 bg-black/40" />
      <aside role="dialog" aria-modal="true" aria-label="Jornada do lead" className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[1000px] flex-col border-l border-edge bg-base shadow-2xl">
        <div className="flex items-center gap-3 border-b border-edge px-4 py-3 sm:px-6">
          <h2 className="min-w-0 flex-1 truncate text-sm font-semibold text-bright">{j ? j.lead.nome : "Jornada do lead"}</h2>
          <button onClick={() => { void navigator.clipboard?.writeText(window.location.href); }} className="rounded-lg border border-edge px-2.5 py-1 text-xs text-muted hover:text-bright" title="Copiar link desta jornada">Copiar link</button>
          <button onClick={onFechar} autoFocus aria-label="Fechar jornada" className="rounded-lg border border-edge px-2.5 py-1 text-sm text-muted hover:text-bright">✕</button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6">
          <JornadaLead chatid={chatid} crmId={crmId} onCarregou={setJ} />
        </div>
        {conversa && (
          <div className="border-t border-edge bg-raised px-4 py-3 sm:px-6">
            <button onClick={() => setResponder(v => !v)} aria-expanded={responder}
              className="flex w-full items-center gap-2 text-left text-sm font-semibold text-bright">
              💬 Responder {j?.resumo.ultima_interacao?.quem === "lead" && <span className="rounded-full bg-emerald/10 px-2 py-0.5 text-[11px] font-medium text-emerald">cliente esperando</span>}
              <span className="ml-auto text-xs font-normal text-muted">{responder ? "recolher ▾" : "abrir com sugestão do Jev ▴"}</span>
            </button>
            {responder && <div className="mt-3 max-h-[48vh] overflow-y-auto"><Responder chatid={conversa} onEnviado={onEnviado} rodape /></div>}
          </div>
        )}
      </aside>
    </>
  );
}
