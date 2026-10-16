import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ETAPA_COR, getJson, ha, plural, tituloEtapa } from "../lib/jornada";
import Responder from "./Responder";

// Visão geral da Jornada — layout "Painel de comando" (escolhido pelo Lucas em 16/10/2026):
// KPIs clicáveis, faixa do funil, lista "O que fazer hoje" com faixa de urgência e botão Responder,
// e lateral com Segunda chance e Régua de 30 dias. Dados: GET /api/jornada/visao (lote; Dione = dela + sem responsável).
type Sinal = { k: string; t: string };
type ItemVisao = {
  chatid: string | null; crm_id: string | null; nome: string; fone: string; etapa: string; dias_na_etapa: number | null;
  responsavel: string | null; ultima: { quando: string; quem: string; canal: string; texto: string; aprox: boolean } | null;
  ultima_ts: number; dias_parado: number | null; esperando: boolean; espera_horas: number | null;
  catalogo: { slug: string; produtos: number | null; provas: number | null; teste30_dia: number | null; segunda_chance: string | null;
              sc_respondeu?: boolean; sc_produtos?: number | null; sc_provas?: number | null; entregue_em?: string | null;
              proximo?: { dia: number; rotulo: string; data: string } | null } | null;
  retomar_em: string | null; motivo_perda: string | null; sinais: Sinal[]; prioridade: number; motivo: string;
};
type Visao = {
  usuario: string; gerado_em: string; etapas: string[]; itens: ItemVisao[];
  resumo: { total: number; por_etapa: Record<string, number>; esperando: number; parados_3: number; parados_7: number; parados_15: number;
            catalogos: number; segunda_chance: number; sc_responderam?: number; sc_cadastraram?: number; sc_provaram?: number;
            teste30?: number; para_hoje: number };
  fontes: { rpc: boolean; avisos: string[] };
};
type Ordem = "prioridade" | "parado" | "etapa" | "recente";
type Kpi = "esperando" | "hoje" | "p3" | "p7" | "p15" | "sc" | "";

const ENCERRADO = new Set(["CONVERTIDO", "PERDIDO"]);
const PARA_HOJE = 450;
const campo = "rounded-lg border border-edge bg-surface px-2.5 py-1.5 text-xs text-text focus:border-violet focus:outline-none";
const urgencia = (p: number) => p >= 700 ? "bg-rose" : p >= PARA_HOJE ? "bg-amber" : "bg-edge";
export type AbrirLead = { chatid?: string | null; crmId?: string | null };

export default function JornadaVisao({ onAbrir, enviados, onEnviado, aberto }: {
  onAbrir: (r: AbrirLead) => void; enviados: Set<string>; onEnviado: (chatid: string) => void; aberto?: string | null;
}) {
  const [v, setV] = useState<Visao | null>(null), [erro, setErro] = useState(""), [carregando, setCarregando] = useState(true);
  const [kpi, setKpi] = useState<Kpi>(""), [etapa, setEtapa] = useState(""), [resp, setResp] = useState(""), [ordem, setOrdem] = useState<Ordem>("prioridade");
  const [soCatalogos, setSoCatalogos] = useState(false), [encerrados, setEncerrados] = useState(false);
  const [limite, setLimite] = useState(40), [respondendo, setRespondendo] = useState<string | null>(null);

  async function carrega() {
    setCarregando(true);
    try { setV(await getJson<Visao>("/api/jornada/visao")); setErro(""); }
    catch (e) { setErro(e instanceof Error ? e.message : "Falha ao carregar."); } finally { setCarregando(false); }
  }
  useEffect(() => { void carrega(); }, []);
  useEffect(() => { setLimite(40); }, [kpi, etapa, resp, ordem, soCatalogos, encerrados]);

  // enviou pelo painel: a linha sai de "esperando" na hora (o servidor já marcou ultimo_de='nos')
  const itens = useMemo(() => (v?.itens || []).map(x => x.chatid && enviados.has(x.chatid) && x.esperando
    ? { ...x, esperando: false, motivo: "Respondido agora pelo painel", sinais: x.sinais.filter(s => s.k !== "esperando") } : x), [v, enviados]);

  const lista = useMemo(() => {
    const p = (x: ItemVisao) => x.etapa !== "NOVO" && !ENCERRADO.has(x.etapa);
    const out = itens.filter(x =>
      (!etapa || x.etapa === etapa) && (encerrados || etapa || !ENCERRADO.has(x.etapa)) &&
      (!resp || (resp === "_sem" ? !x.responsavel : x.responsavel === resp)) && (!soCatalogos || !!x.catalogo) &&
      (kpi !== "esperando" || x.esperando) && (kpi !== "hoje" || x.prioridade >= PARA_HOJE) &&
      (kpi !== "p3" || (p(x) && (x.dias_parado ?? 0) >= 3)) && (kpi !== "p7" || (p(x) && (x.dias_parado ?? 0) >= 7)) &&
      (kpi !== "p15" || (p(x) && (x.dias_parado ?? 0) >= 15)) && (kpi !== "sc" || !!x.catalogo?.segunda_chance));
    const cmp: Record<Ordem, (a: ItemVisao, b: ItemVisao) => number> = {
      prioridade: (a, b) => b.prioridade - a.prioridade || b.ultima_ts - a.ultima_ts,
      parado: (a, b) => (b.dias_parado ?? -1) - (a.dias_parado ?? -1),
      etapa: (a, b) => (b.dias_na_etapa ?? -1) - (a.dias_na_etapa ?? -1),
      recente: (a, b) => b.ultima_ts - a.ultima_ts,
    };
    return out.sort(cmp[ordem]);
  }, [itens, kpi, etapa, resp, ordem, soCatalogos, encerrados]);

  if (erro && !v) return <div role="alert" className="rounded-lg border border-rose/40 px-4 py-3 text-sm text-rose">{erro} <button onClick={() => void carrega()} className="ml-2 underline">Tentar de novo</button></div>;
  if (!v) return <p role="status" className="text-sm text-muted">Carregando a visão geral…</p>;
  const r = v.resumo, lucas = v.usuario === "lucas";
  const esperandoAgora = itens.filter(x => x.esperando).length;
  const maxFunil = Math.max(1, ...v.etapas.map(e => r.por_etapa[e] ?? 0));
  const regua = itens.filter(x => x.catalogo?.teste30_dia != null).sort((a, b) => (a.catalogo!.teste30_dia! - b.catalogo!.teste30_dia!));
  const filtrando = !!(kpi || etapa || resp || soCatalogos);
  const limpa = () => { setKpi(""); setEtapa(""); setResp(""); setSoCatalogos(false); };
  const KPIS: [Kpi, string, number, string][] = [
    ["esperando", "Esperando resposta", esperandoAgora, "var(--color-rose)"], ["hoje", "Para fazer hoje", r.para_hoje, "var(--color-amber)"],
    ["p3", "Parados 3+ dias", r.parados_3, "#3b82f6"], ["p7", "Parados 7+ dias", r.parados_7, "#8b5cf6"],
    ["p15", "Parados 15+ dias", r.parados_15, "#64748b"], ["sc", "Segunda chance", r.segunda_chance, "var(--color-emerald)"]];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-xs text-muted">
        <span>Visão geral · {lucas ? "todos os leads" : "seus leads e os sem responsável"} · {plural(r.total, "lead", "leads")}</span>
        <span>atualizado {v.gerado_em.slice(11)} <button onClick={() => void carrega()} disabled={carregando} className="ml-1 text-violet-light disabled:opacity-50">{carregando ? "atualizando…" : "atualizar"}</button></span>
      </div>

      <section className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6" aria-label="Indicadores">
        {KPIS.map(([id, rot, n, cor]) => (
          <button key={id} onClick={() => setKpi(kpi === id ? "" : id)} aria-pressed={kpi === id}
            className={`rounded-xl border bg-raised px-4 py-3 text-left transition hover:-translate-y-px hover:border-violet/40 ${kpi === id ? "border-violet ring-1 ring-violet" : "border-edge"}`}>
            <b className="block text-2xl font-semibold tabular-nums tracking-tight text-bright">{n}</b>
            <span className="text-xs font-semibold text-muted"><i className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ background: cor }} />{rot}</span>
          </button>
        ))}
      </section>

      <section className="flex gap-1.5 overflow-x-auto pb-1" aria-label="Funil por etapa">
        {v.etapas.map(e => {
          const n = r.por_etapa[e] ?? 0;
          return <button key={e} onClick={() => setEtapa(etapa === e ? "" : e)} aria-pressed={etapa === e}
            className={`min-w-[92px] flex-1 rounded-lg border bg-raised px-2.5 py-2 text-left ${etapa === e ? "border-violet" : "border-edge hover:border-violet/40"}`}>
            <small className="block whitespace-nowrap text-[11px] text-muted">{tituloEtapa(e)}</small>
            <b className="text-base font-semibold tabular-nums text-bright">{n}</b>
            <span className="mt-1.5 block h-1 overflow-hidden rounded bg-panel"><i className="block h-full" style={{ width: `${n / maxFunil * 100}%`, background: ETAPA_COR[e] }} /></span>
          </button>;
        })}
      </section>
      {v.fontes.avisos.map(a => <p key={a} className="text-[11px] text-amber">⚠ {a}</p>)}

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <div className="min-w-0 rounded-xl border border-edge bg-raised">
          <div className="flex flex-wrap items-center gap-2 border-b border-edge px-4 py-3">
            <h2 className="text-sm font-semibold text-bright">🔥 O que fazer hoje</h2>
            <span className="text-xs text-muted">{plural(lista.length, "lead", "leads")} · ordenado por {ordem === "prioridade" ? "prioridade" : ordem === "parado" ? "tempo parado" : ordem === "etapa" ? "tempo na etapa" : "interação recente"}</span>
            <div className="ml-auto flex flex-wrap gap-1.5">
              <select aria-label="Etapa" className={campo} value={etapa} onChange={e => setEtapa(e.target.value)}>
                <option value="">Todas as etapas</option>{v.etapas.map(e => <option key={e} value={e}>{tituloEtapa(e)}</option>)}
              </select>
              <select aria-label="Responsável" className={campo} value={resp} onChange={e => setResp(e.target.value)}>
                <option value="">{lucas ? "Todos" : "Meus + sem responsável"}</option>
                {lucas && <option value="Lucas">Lucas</option>}<option value="Dione">{lucas ? "Dione" : "Só os meus"}</option><option value="_sem">Sem responsável</option>
              </select>
              <select aria-label="Ordenar" className={campo} value={ordem} onChange={e => setOrdem(e.target.value as Ordem)}>
                <option value="prioridade">Prioridade</option><option value="parado">Mais tempo parado</option>
                <option value="etapa">Mais tempo na etapa</option><option value="recente">Interação mais recente</option>
              </select>
            </div>
          </div>
          <div className="flex flex-wrap gap-1.5 border-b border-edge-subtle px-4 py-2 text-[11px]">
            <Chip on={kpi === "esperando"} onClick={() => setKpi(kpi === "esperando" ? "" : "esperando")}>🟢 Esperando resposta</Chip>
            <Chip on={kpi === "p3"} onClick={() => setKpi(kpi === "p3" ? "" : "p3")}>⏰ Parados 3+ dias</Chip>
            <Chip on={soCatalogos} onClick={() => setSoCatalogos(!soCatalogos)}>📦 Só catálogos</Chip>
            <Chip on={kpi === "sc"} onClick={() => setKpi(kpi === "sc" ? "" : "sc")}>🎁 Segunda chance</Chip>
            <Chip on={encerrados} onClick={() => setEncerrados(!encerrados)}>Convertidos e perdidos</Chip>
            {filtrando && <button onClick={limpa} className="px-2 text-violet-light">limpar filtros</button>}
          </div>
          {!lista.length && <p className="py-10 text-center text-xs text-muted">Nenhum lead com esses filtros.</p>}
          <ul>
            {lista.slice(0, limite).map(x => {
              const key = (x.chatid || "") + (x.crm_id || ""), resp_ = respondendo === key, sel = aberto && (aberto === x.chatid || aberto === x.crm_id);
              return (
                <li key={key} className={`border-b border-edge-subtle ${sel ? "bg-active-bg" : ""}`}>
                  <div role="button" tabIndex={0} onClick={() => onAbrir({ chatid: x.chatid, crmId: x.crm_id })}
                    onKeyDown={e => { if (e.key === "Enter") onAbrir({ chatid: x.chatid, crmId: x.crm_id }); }}
                    className="grid cursor-pointer grid-cols-[6px_minmax(0,1fr)_auto] gap-3 px-4 py-3 hover:bg-active-bg">
                    <span className={`rounded ${urgencia(x.prioridade)}`} aria-hidden="true" />
                    <span className="min-w-0">
                      <span className="flex flex-wrap items-center gap-2">
                        <b className="truncate text-sm font-semibold text-bright">{x.nome}</b>
                        <span className="rounded-full px-2 py-0.5 text-[11px] font-semibold" style={{ background: (ETAPA_COR[x.etapa] || "#8490a3") + "22", color: ETAPA_COR[x.etapa] || "var(--color-muted)" }}>{tituloEtapa(x.etapa)}</span>
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted">
                        {x.motivo ? <b className="font-medium text-sub">{x.motivo}</b> : null}{x.motivo && x.ultima ? " · " : ""}
                        {x.ultima && (x.ultima.aprox ? `atualizado no CRM ${ha(x.ultima_ts)}` : <>{x.ultima.quem === "lead" ? "Cliente" : "Nós"} {ha(x.ultima_ts)}{x.ultima.canal === "grupo" ? " (grupo)" : ""}: “{x.ultima.texto || "mídia"}”</>)}
                        {!x.ultima && "sem conversa no painel"}
                      </span>
                      {x.sinais.length > 0 && <span className="mt-1.5 flex flex-wrap gap-1.5">
                        {x.sinais.map((s, i) => <span key={i} className={`rounded-full px-2 py-0.5 text-[11px] ${s.k === "esperando" ? "bg-emerald/10 text-emerald" : s.k === "parado" || s.k === "financeiro" ? "bg-amber/10 text-amber" : "bg-panel text-sub"}`}>{s.t}</span>)}
                      </span>}
                    </span>
                    <span className="flex flex-col items-end gap-1.5 text-right text-xs text-muted">
                      <span>{x.responsavel || "Sem responsável"}</span>
                      <span>{x.dias_na_etapa == null ? "—" : x.dias_na_etapa === 0 ? "entrou hoje" : plural(x.dias_na_etapa, "dia", "dias") + " na etapa"}</span>
                      {x.chatid && <button onClick={e => { e.stopPropagation(); setRespondendo(resp_ ? null : key); }} aria-expanded={resp_}
                        className={`rounded-lg px-3 py-1 text-[11px] font-semibold ${resp_ ? "bg-panel text-sub" : "bg-violet text-white"}`}>{resp_ ? "Fechar" : "Responder"}</button>}
                    </span>
                  </div>
                  {resp_ && x.chatid && <div className="px-4 pb-4"><Responder chatid={x.chatid} onEnviado={onEnviado} /></div>}
                </li>
              );
            })}
          </ul>
          {lista.length > limite && <button onClick={() => setLimite(l => l + 60)} className="w-full py-3 text-xs text-muted hover:text-bright">Mostrar mais ({lista.length - limite} restantes)</button>}
        </div>

        <aside className="h-fit rounded-xl border border-edge bg-raised xl:sticky xl:top-4">
          <h2 className="flex items-center gap-2 border-b border-edge px-4 py-3 text-sm font-semibold text-bright">🎁 Segunda chance <small className="ml-auto font-normal text-muted">{plural(r.segunda_chance, "loja", "lojas")}</small></h2>
          {r.segunda_chance ? <>
            <Lado titulo={`${plural(r.segunda_chance, "mensagem enviada", "mensagens enviadas")}`} sub="no grupo e no privado de cada loja" />
            <Lado titulo={`${r.sc_responderam ?? 0} responderam depois`} sub="falaram no privado ou no grupo depois da mensagem" />
            <Lado titulo={`${r.sc_cadastraram ?? 0} cadastraram produto depois`} sub={`${r.sc_provaram ?? 0} tiveram prova depois`} />
            <button onClick={() => setKpi("sc")} className="w-full border-b border-edge px-4 py-2.5 text-left text-xs text-violet-light hover:bg-active-bg">Ver as {r.segunda_chance} lojas →</button>
          </> : <p className="border-b border-edge px-4 py-3 text-xs text-muted">{v.fontes.rpc ? "Nenhuma segunda chance enviada." : "Aguardando a função crm_jornada_visao no Supabase."}</p>}
          <h2 className="flex items-center gap-2 border-b border-edge px-4 py-3 text-sm font-semibold text-bright">🗓 Régua 30 dias <small className="ml-auto font-normal text-muted">{plural(regua.length, "catálogo", "catálogos")}</small></h2>
          {!regua.length && <p className="px-4 py-3 text-xs text-muted">Nenhum catálogo na régua ainda.</p>}
          {regua.map(x => (
            <button key={(x.chatid || "") + (x.crm_id || "")} onClick={() => onAbrir({ chatid: x.chatid, crmId: x.crm_id })}
              className="block w-full border-b border-edge-subtle px-4 py-3 text-left hover:bg-active-bg">
              <b className="block text-sm font-semibold text-bright">{x.nome} · dia {x.catalogo!.teste30_dia}</b>
              <span className="text-xs text-muted">{x.catalogo!.proximo ? `próxima msg: ${x.catalogo!.proximo.rotulo} (${x.catalogo!.proximo.data.slice(8, 10)}/${x.catalogo!.proximo.data.slice(5, 7)})` : "sem mensagem agendada"}
                {x.catalogo!.entregue_em ? ` · entregue ${x.catalogo!.entregue_em}` : ""}</span>
            </button>
          ))}
        </aside>
      </section>
    </div>
  );
}

function Lado({ titulo, sub }: { titulo: string; sub: string }) {
  return <div className="border-b border-edge px-4 py-3"><b className="block text-sm font-semibold text-bright">{titulo}</b><span className="text-xs text-muted">{sub}</span></div>;
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} aria-pressed={on} className={`rounded-full border px-2.5 py-1 transition-colors ${on ? "border-violet bg-active-bg text-bright" : "border-edge text-muted hover:text-sub"}`}>{children}</button>;
}
