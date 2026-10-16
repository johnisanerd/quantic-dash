import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { fmtFone, getJson, plural } from "../lib/jornada";

// Jornada completa de um lead: cabeçalho de resumo, régua de 30 dias, próximos marcos e linha do tempo por dia.
// Dados: GET /api/lead/jornada (painel) — mesma regra de visibilidade do Atendimento.
type Cat = "mensagens" | "etapas" | "catalogo" | "financeiro" | "notas" | "responsavel" | "lead";
type Evento = {
  ts: string; dia: string; quando: string; hora: string; cat: Cat; tipo: string; titulo: string; detalhe: string;
  quem: string; quem_rotulo: string; canal: string; midia?: boolean; texto?: string; status?: string; marco?: boolean;
};
type Envio = { dia: number; etapa: string; rotulo: string; data: string | null; status: string; enviado_em: string | null; texto: string; erro: string };
type Regua = { entregue_em: string | null; dia_atual: number | null; fase: string | null; teste_de: string | null; teste_ate: string | null; mensagens: Envio[] };
type Marco = { data: string; titulo: string; detalhe: string; tipo: string };
export type Jornada = {
  lead: { nome: string; fone: string; chatid: string | null; crm_id: string | null; grupo: { chatid: string; nome: string } | null;
          catalogo: { slug: string; link: string; teste_30d: boolean } | null };
  resumo: {
    dias_desde_entrada: number | null; entrou_em: string | null; etapa: string; etapa_desde: string | null; dias_na_etapa: number | null;
    responsavel: string | null; msgs_nossas: number; msgs_dele: number; msgs_nossas_grupo: number; msgs_dele_grupo: number;
    resposta_nossa_media: string | null; resposta_nossa_mediana: string | null; resposta_dele_mediana: string | null; respostas_medidas: number;
    ultima_interacao: { quando: string; quem: string; canal: string; texto: string; ha_dias: number } | null;
    provas: number; tentativas: number | null; motivo_perda: string | null;
    conta: { status?: string; plano?: string; ultimo_pagamento?: string } | null; financeiro_oculto: boolean; proximos: Marco[];
  };
  regua: Regua | null;
  eventos: Evento[];
  fontes: { rpc: boolean; avisos: string[] };
};
const CATS: { id: Cat; label: string; cor: string; icon: ReactNode }[] = [
  { id: "mensagens", label: "Mensagens", cor: "#38bdf8", icon: <path d="M3 5h18v11H9l-5 4v-4H3z" /> },
  { id: "etapas", label: "Etapas", cor: "#8b5cf6", icon: <><path d="M4 20V9M10 20V4M16 20v-7" /><path d="M2 20h20" /></> },
  { id: "catalogo", label: "Catálogo", cor: "#10b981", icon: <><path d="M3 9 5 3h14l2 6M5 13v8h14v-8" /><path d="M3 9a3 3 0 0 0 6 0 3 3 0 0 0 6 0 3 3 0 0 0 6 0" /></> },
  { id: "financeiro", label: "Financeiro", cor: "#f59e0b", icon: <><circle cx="12" cy="12" r="9" /><path d="M15 9.2c-.6-.8-1.6-1.2-3-1.2-1.7 0-2.8.8-2.8 2 0 2.8 6 1.5 6 4.2 0 1.2-1.2 2.1-3.1 2.1-1.4 0-2.5-.5-3.1-1.4M12 6v2M12 16.4v1.6" /></> },
  { id: "notas", label: "Tarefas e notas", cor: "#94a3b8", icon: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 8h8M8 12h8M8 16h5" /></> },
  { id: "responsavel", label: "Responsável", cor: "#06b6d4", icon: <><circle cx="12" cy="8" r="4" /><path d="M4 21a8 8 0 0 1 16 0" /></> },
  { id: "lead", label: "Lead", cor: "#e879f9", icon: <><path d="M12 2l2.6 6.3L21 9l-5 4.4L17.5 20 12 16.6 6.5 20 8 13.4 3 9l6.4-.7z" /></> },
];
const CAT = Object.fromEntries(CATS.map(c => [c.id, c])) as Record<Cat, (typeof CATS)[number]>;
const ETAPA_COR_D: Record<string, string> = {
  "NOVO": "#3b82f6", "EM CONVERSA": "#0ea5e9", "INTERESSADO": "#8b5cf6", "AGUARDANDO DADOS": "#06b6d4", "EM TESTE": "#84cc16",
  "TESTE PARADO": "#f97316", "PROPOSTA ENVIADA": "#a855f7", "AGUARDANDO PAGAMENTO": "#22c55e", "CONVERTIDO": "#10b981",
  "STAND-BY": "#f59e0b", "PERDIDO": "#ef4444",
};
const CANAL: Record<string, string> = { privado: "WhatsApp privado", grupo: "grupo do catálogo", crm: "CRM", sistema: "sistema", instagram: "Instagram" };
const STATUS_ENVIO: Record<string, { label: string; cls: string }> = {
  enviado: { label: "enviada", cls: "bg-emerald/10 text-emerald" }, agendado: { label: "agendada", cls: "bg-cyan/10 text-cyan" },
  previsto: { label: "prevista", cls: "bg-violet/10 text-violet-light" }, erro: { label: "falhou", cls: "bg-rose/10 text-rose" },
  pulado: { label: "pulada", cls: "bg-amber/10 text-amber" }, "sem registro": { label: "sem registro", cls: "bg-panel text-muted" },
  "aguardando entrega": { label: "aguardando entrega", cls: "bg-panel text-muted" },
};

function Svg({ children, className = "h-4 w-4" }: { children: ReactNode; className?: string }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className={className}>{children}</svg>;
}
function diaTitulo(dia: string) {
  const d = new Date(dia + "T12:00:00-03:00");
  const hoje = new Date().toLocaleDateString("en-CA", { timeZone: "America/Sao_Paulo" });
  const ontem = new Date(Date.now() - 86400000).toLocaleDateString("en-CA", { timeZone: "America/Sao_Paulo" });
  const base = d.toLocaleDateString("pt-BR", { weekday: "short", day: "2-digit", month: "2-digit", year: "numeric", timeZone: "America/Sao_Paulo" });
  return dia === hoje ? "Hoje · " + base : dia === ontem ? "Ontem · " + base : base;
}
const br = (iso: string | null | undefined) => iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) : "—";

export default function JornadaLead({ chatid, crmId, onCarregou }: { chatid?: string | null; crmId?: string | null; onCarregou?: (j: Jornada | null) => void }) {
  const [j, setJ] = useState<Jornada | null>(null), [erro, setErro] = useState("");
  const [filtro, setFiltro] = useState<Set<Cat>>(new Set(CATS.map(c => c.id)));
  const [abertos, setAbertos] = useState<Set<string>>(new Set());
  const [envioAberto, setEnvioAberto] = useState<string | null>(null);
  useEffect(() => {
    let vivo = true;
    setJ(null); setErro(""); setAbertos(new Set());
    const q = new URLSearchParams(); if (chatid) q.set("chatid", chatid); if (crmId) q.set("crm_id", crmId);
    getJson<Jornada>("/api/lead/jornada?" + q.toString())
      .then(d => { if (vivo) { setJ(d); onCarregou?.(d); } })
      .catch(e => { if (vivo) { setErro(e instanceof Error ? e.message : "Falha ao carregar a jornada."); onCarregou?.(null); } });
    return () => { vivo = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chatid, crmId]);
  if (erro) return <div role="alert" className="rounded-lg border border-rose/40 px-4 py-3 text-sm text-rose">{erro}</div>;
  if (!j) return <p role="status" className="text-sm text-muted">Montando a jornada…</p>;
  return <Detalhe j={j} filtro={filtro} setFiltro={setFiltro} abertos={abertos} setAbertos={setAbertos} envioAberto={envioAberto} setEnvioAberto={setEnvioAberto} />;
}

function Detalhe({ j, filtro, setFiltro, abertos, setAbertos, envioAberto, setEnvioAberto }: {
  j: Jornada; filtro: Set<Cat>; setFiltro: (s: Set<Cat>) => void; abertos: Set<string>; setAbertos: (s: Set<string>) => void;
  envioAberto: string | null; setEnvioAberto: (s: string | null) => void;
}) {
  const r = j.resumo, L = j.lead;
  const contagem = useMemo(() => {
    const c = Object.fromEntries(CATS.map(x => [x.id, 0])) as Record<Cat, number>;
    for (const e of j.eventos) c[e.cat] = (c[e.cat] || 0) + 1;
    return c;
  }, [j]);
  const dias = useMemo(() => {
    const m = new Map<string, Evento[]>();
    for (const e of j.eventos) { if (!filtro.has(e.cat)) continue; if (!m.has(e.dia)) m.set(e.dia, []); m.get(e.dia)!.push(e); }
    return [...m.entries()].sort((a, b) => b[0].localeCompare(a[0]));
  }, [j, filtro]);
  const todos = filtro.size === CATS.length;
  const toggle = (c: Cat) => { const s = new Set(filtro); if (todos) { setFiltro(new Set([c])); return; } if (s.has(c)) s.delete(c); else s.add(c); setFiltro(s.size ? s : new Set(CATS.map(x => x.id))); };
  const etapaCor = ETAPA_COR_D[r.etapa] || "#8490a3";
  const diasComMsg = dias.filter(([, evs]) => evs.some(e => e.cat === "mensagens")).map(([d]) => d);
  const tudoAberto = diasComMsg.length > 0 && diasComMsg.every(d => abertos.has(d));

  return (
    <div className="space-y-5">
      <section className="rounded-xl border border-edge bg-raised p-4 sm:p-5">
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-xl font-semibold text-bright">{L.nome}</h2>
            <p className="mt-0.5 text-xs text-muted">{fmtFone(L.fone)}{L.catalogo ? <> · <a className="text-violet-light hover:underline" href={"https://" + L.catalogo.link} target="_blank" rel="noreferrer">{L.catalogo.link}</a></> : ""}</p>
          </div>
          <div className="flex flex-wrap gap-2 text-xs">
            {L.chatid && <Link to={`/atendimento?chatid=${encodeURIComponent(L.chatid)}`} className="rounded-lg bg-violet px-3 py-2 font-semibold text-white">Abrir conversa →</Link>}
            {L.grupo && <Link to={`/atendimento?chatid=${encodeURIComponent(L.grupo.chatid)}`} className="rounded-lg border border-edge px-3 py-2 text-sub hover:text-bright">👥 Grupo da loja</Link>}
            {L.crm_id && <Link to={`/leads/${L.crm_id}`} className="rounded-lg border border-edge px-3 py-2 text-sub hover:text-bright">Lead no CRM</Link>}
          </div>
        </div>
        <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <Kpi label="Etapa atual"><span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: etapaCor }} />{r.etapa.charAt(0) + r.etapa.slice(1).toLowerCase()}</span>
            <small>{r.dias_na_etapa != null ? `há ${plural(r.dias_na_etapa, "dia", "dias")} (desde ${r.etapa_desde})` : "desde quando: sem registro"}</small></Kpi>
          <Kpi label="No funil">{r.dias_desde_entrada != null ? plural(r.dias_desde_entrada, "dia", "dias") : "—"}<small>{r.entrou_em ? "entrou em " + r.entrou_em : ""}</small></Kpi>
          <Kpi label="Responsável">{r.responsavel || "Sem responsável"}<small>{r.tentativas ? plural(r.tentativas, "tentativa", "tentativas") : ""}</small></Kpi>
          <Kpi label="Mensagens">{r.msgs_nossas} nossas · {r.msgs_dele} dele<small>{r.msgs_nossas_grupo + r.msgs_dele_grupo ? `+ ${r.msgs_nossas_grupo + r.msgs_dele_grupo} no grupo` : "conversa privada"}</small></Kpi>
          <Kpi label="Nosso tempo de resposta">{r.resposta_nossa_mediana || "—"}<small>{r.respostas_medidas ? `mediana · média ${r.resposta_nossa_media}` : "sem resposta medida"}{r.resposta_dele_mediana ? ` · ele: ${r.resposta_dele_mediana}` : ""}</small></Kpi>
          <Kpi label="Provas">{r.provas}<small>{L.catalogo ? "no catálogo" : "sem catálogo"}</small></Kpi>
        </dl>
        {r.ultima_interacao && (
          <p className="mt-4 rounded-lg bg-surface px-3 py-2 text-xs text-sub">
            <span className="text-muted">Última interação · {r.ultima_interacao.quando} · {r.ultima_interacao.quem === "lead" ? "do lead" : "nossa"} · {CANAL[r.ultima_interacao.canal] || r.ultima_interacao.canal}
              {r.ultima_interacao.ha_dias > 0 ? ` · há ${plural(r.ultima_interacao.ha_dias, "dia", "dias")}` : ""}</span><br />
            “{r.ultima_interacao.texto || "[mídia]"}”
          </p>
        )}
        {(r.conta || r.motivo_perda || r.financeiro_oculto) && (
          <p className="mt-2 text-xs text-muted">
            {r.motivo_perda && <>Motivo da perda: <b className="text-sub">{r.motivo_perda}</b>. </>}
            {r.conta && <>Conta: <b className="text-sub">{r.conta.status || "—"}</b>{r.conta.plano ? ` · plano ${r.conta.plano}` : ""}{r.conta.ultimo_pagamento ? ` · último pagamento ${r.conta.ultimo_pagamento}` : ""}. </>}
            {r.financeiro_oculto && "Cobranças e pagamentos aparecem só para o responsável do lead."}
          </p>
        )}
        {j.fontes.avisos.map(a => <p key={a} className="mt-2 text-[11px] text-amber">⚠ {a}</p>)}
      </section>

      {(j.regua || r.proximos.length > 0) && (
        <div className="grid gap-4 md:grid-cols-[2fr_1fr]">
          {j.regua ? <ReguaCard regua={j.regua} aberto={envioAberto} setAberto={setEnvioAberto} /> : <div />}
          {r.proximos.length > 0 && (
            <section className="rounded-xl border border-edge bg-raised p-4">
              <h3 className="mb-3 text-sm font-semibold text-bright">Próximos marcos</h3>
              <ol className="space-y-2">
                {r.proximos.map((p, i) => (
                  <li key={i} className="flex gap-3 text-xs">
                    <span className="w-12 shrink-0 font-semibold tabular-nums text-violet-light">{br(p.data)}</span>
                    <span className="text-sub">{p.titulo}{p.detalhe && <small className="block text-muted">{p.detalhe}</small>}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </div>
      )}

      <section className="rounded-xl border border-edge bg-raised p-4 sm:p-5">
        <div className="mb-4 flex flex-wrap items-center gap-2">
          <h3 className="mr-2 text-sm font-semibold text-bright">Linha do tempo</h3>
          {CATS.map(c => {
            const on = filtro.has(c.id) && !todos;
            return <button key={c.id} onClick={() => toggle(c.id)} aria-pressed={on}
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] transition-colors ${on ? "border-transparent text-bright" : "border-edge text-muted hover:text-sub"}`}
              style={on ? { background: c.cor + "26" } : undefined}>
              <span style={{ color: c.cor }}><Svg className="h-3.5 w-3.5">{c.icon}</Svg></span>{c.label}<span className="tabular-nums text-dim">{contagem[c.id]}</span>
            </button>;
          })}
          {!todos && <button onClick={() => setFiltro(new Set(CATS.map(x => x.id)))} className="text-[11px] text-violet-light">mostrar tudo</button>}
          {diasComMsg.length > 0 && <button onClick={() => setAbertos(tudoAberto ? new Set() : new Set(diasComMsg))} className="ml-auto text-[11px] text-muted hover:text-bright">
            {tudoAberto ? "Recolher mensagens" : "Expandir todas as mensagens"}</button>}
        </div>
        {!dias.length && <p className="py-6 text-center text-xs text-muted">Nada registrado nessa categoria.</p>}
        <ol className="space-y-6">
          {dias.map(([dia, evs]) => {
            const msgs = evs.filter(e => e.cat === "mensagens"), outros = evs.filter(e => e.cat !== "mensagens");
            const nossas = msgs.filter(e => e.quem === "nos").length, aberto = abertos.has(dia);
            const itens: Array<Evento | "msgs"> = [];
            let pos = false;
            for (const e of [...evs].reverse()) {           // mais recente primeiro dentro do dia
              if (e.cat === "mensagens") { if (!pos) { itens.push("msgs"); pos = true; } continue; }
              itens.push(e);
            }
            return (
              <li key={dia}>
                <h4 className="sticky top-0 z-10 -mx-1 mb-2 bg-raised px-1 py-1 text-xs font-semibold uppercase tracking-wide text-muted">
                  {diaTitulo(dia)} <span className="font-normal normal-case tracking-normal text-dim">· {plural(outros.length + msgs.length, "evento", "eventos")}</span></h4>
                <ol className="relative ml-3 space-y-3 border-l border-edge pl-5">
                  {itens.map((e, i) => e === "msgs" ? (
                    <li key={"m" + i} className="relative">
                      <Dot cat="mensagens" />
                      <button onClick={() => { const s = new Set(abertos); if (aberto) s.delete(dia); else s.add(dia); setAbertos(s); }}
                        className="text-left text-sm text-sub hover:text-bright" aria-expanded={aberto}>
                        <b className="font-medium text-bright">{plural(msgs.length, "mensagem", "mensagens")}</b>
                        <span className="text-muted"> — {nossas} nossa{nossas === 1 ? "" : "s"}, {msgs.length - nossas} do lead · {aberto ? "recolher" : "expandir"}</span>
                      </button>
                      {aberto && (
                        <ul className="mt-2 space-y-1.5">
                          {msgs.map((m, k) => (
                            <li key={k} className={`max-w-[85%] rounded-lg px-3 py-1.5 text-xs ${m.quem === "nos" ? "ml-auto bg-violet/10 text-sub" : "bg-surface text-sub"}`}>
                              <span className="block text-[10px] text-muted">{m.hora} · {m.quem === "nos" ? "nós" : "lead"} · {CANAL[m.canal] || m.canal}</span>
                              <span className="whitespace-pre-wrap break-words">{m.detalhe}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </li>
                  ) : (
                    <li key={i} className="relative">
                      <Dot cat={e.cat} />
                      <div className="flex flex-wrap items-baseline gap-x-2">
                        <b className="text-sm font-medium text-bright">{e.titulo}</b>
                        {e.status && <span className={`rounded-full px-2 py-0.5 text-[10px] ${(STATUS_ENVIO[e.status] || STATUS_ENVIO.previsto).cls}`}>{(STATUS_ENVIO[e.status] || { label: e.status }).label}</span>}
                      </div>
                      <small className="block text-[11px] text-muted">{e.hora || "dia todo"} · {e.quem_rotulo} · {CANAL[e.canal] || e.canal}</small>
                      {e.texto ? (
                        <p className="mt-1 whitespace-pre-wrap break-words text-xs text-sub">
                          {envioAberto === e.ts ? e.texto : e.texto.slice(0, 180) + (e.texto.length > 180 ? "…" : "")}
                          {e.texto.length > 180 && <button className="ml-1 text-violet-light" onClick={() => setEnvioAberto(envioAberto === e.ts ? null : e.ts)}>{envioAberto === e.ts ? "menos" : "ver texto"}</button>}
                          {e.detalhe && e.detalhe !== e.texto && <span className="block text-rose">{e.detalhe}</span>}
                        </p>
                      ) : e.detalhe && <p className="mt-1 whitespace-pre-wrap break-words text-xs text-sub">{e.detalhe}</p>}
                    </li>
                  ))}
                </ol>
              </li>
            );
          })}
        </ol>
      </section>
    </div>
  );
}

function Kpi({ label, children }: { label: string; children: ReactNode }) {
  return <div className="rounded-lg bg-surface px-3 py-2.5"><dt className="text-[10px] font-semibold uppercase tracking-widest text-dim">{label}</dt>
    <dd className="mt-1 text-sm font-medium text-bright [&>small]:mt-0.5 [&>small]:block [&>small]:text-[11px] [&>small]:font-normal [&>small]:text-muted">{children}</dd></div>;
}

function Dot({ cat }: { cat: Cat }) {
  const c = CAT[cat];
  return <span className="absolute -left-[31px] top-0 flex h-5 w-5 items-center justify-center rounded-full border border-edge bg-raised" style={{ color: c.cor }} title={c.label}>
    <Svg className="h-3 w-3">{c.icon}</Svg></span>;
}

function ReguaCard({ regua, aberto, setAberto }: { regua: Regua; aberto: string | null; setAberto: (s: string | null) => void }) {
  const dia = regua.dia_atual, pct = (d: number) => `${((d - 1) / 29) * 100}%`;
  return (
    <section className="rounded-xl border border-edge bg-raised p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-bright">Régua de 30 dias do catálogo</h3>
        <span className="text-xs text-muted">{regua.entregue_em ? <>entregue em {regua.entregue_em}{dia != null && <> · <b className="text-sub">dia {dia}</b> ({regua.fase === "montagem" ? "montagem" : regua.fase === "teste" ? "teste grátis" : "régua encerrada"})</>}</> : "catálogo ainda não entregue"}</span>
      </div>
      <div className="relative mb-6 mt-2 h-2 rounded-full bg-panel" aria-hidden="true">
        <div className="absolute inset-y-0 left-0 rounded-l-full bg-violet/40" style={{ width: pct(22) }} />
        <div className="absolute inset-y-0 rounded-r-full bg-emerald/50" style={{ left: pct(22), width: `calc(${pct(28)} - ${pct(22)})` }} />
        {regua.mensagens.map(m => <i key={m.etapa} className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-raised"
          style={{ left: pct(m.dia), background: m.status === "enviado" ? "var(--color-emerald)" : m.status === "erro" ? "var(--color-rose)" : "var(--color-edge)" }} />)}
        {dia != null && dia >= 1 && dia <= 30 && <span className="absolute -top-1 h-4 w-0.5 bg-bright" style={{ left: pct(dia) }} title={"hoje: dia " + dia} />}
        <span className="absolute left-0 top-3 text-[10px] text-muted">dia 1 · entrega</span>
        <span className="absolute top-3 -translate-x-1/2 text-[10px] text-muted" style={{ left: pct(22) }}>22 · teste{regua.teste_de ? ` ${regua.teste_de}–${regua.teste_ate}` : ""}</span>
      </div>
      <ul className="divide-y divide-edge-subtle">
        {regua.mensagens.map(m => {
          const st = STATUS_ENVIO[m.status] || { label: m.status, cls: "bg-panel text-muted" };
          return (
            <li key={m.etapa} className="py-2 text-xs">
              <div className="flex flex-wrap items-center gap-2">
                <span className="w-12 font-semibold tabular-nums text-sub">{br(m.data)}</span>
                <span className="flex-1 text-sub">{m.rotulo}</span>
                <span className={`rounded-full px-2 py-0.5 text-[10px] ${st.cls}`}>{st.label}{m.enviado_em ? " " + m.enviado_em.slice(0, 5) : ""}</span>
                {m.texto && <button onClick={() => setAberto(aberto === m.etapa ? null : m.etapa)} className="text-[11px] text-violet-light">{aberto === m.etapa ? "ocultar" : "ver texto"}</button>}
              </div>
              {aberto === m.etapa && <p className="mt-1.5 whitespace-pre-wrap rounded-lg bg-surface px-3 py-2 text-sub">{m.texto}</p>}
              {m.erro && <p className="mt-1 text-rose">{m.erro}</p>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}

