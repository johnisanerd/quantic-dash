import { useEffect, useMemo, useState, type ReactNode } from "react";

// Visão geral da Jornada (tela inicial): funil, quem está esperando, quem está parado e "o que fazer hoje".
// Dados: GET /api/jornada/visao (calculado em lote no painel; Dione recebe só os dela + sem responsável).
type Sinal = { k: string; t: string };
type ItemVisao = {
  chatid: string | null; crm_id: string | null; nome: string; fone: string; etapa: string; dias_na_etapa: number | null;
  responsavel: string | null; ultima: { quando: string; quem: string; canal: string; texto: string; aprox: boolean } | null;
  ultima_ts: number; dias_parado: number | null; esperando: boolean; espera_horas: number | null;
  catalogo: { slug: string; produtos: number | null; provas: number | null; teste30_dia: number | null; segunda_chance: string | null } | null;
  retomar_em: string | null; motivo_perda: string | null; sinais: Sinal[]; prioridade: number; motivo: string;
};
type Visao = {
  usuario: string; gerado_em: string; etapas: string[]; itens: ItemVisao[];
  resumo: { total: number; por_etapa: Record<string, number>; esperando: number; parados_3: number; parados_7: number; parados_15: number;
            catalogos: number; segunda_chance: number; para_hoje: number };
  fontes: { rpc: boolean; avisos: string[] };
};
type Ordem = "prioridade" | "parado" | "etapa" | "recente";

const ETAPA_COR: Record<string, string> = {
  "NOVO": "#3b82f6", "EM CONVERSA": "#0ea5e9", "INTERESSADO": "#8b5cf6", "AGUARDANDO DADOS": "#06b6d4", "EM TESTE": "#84cc16",
  "TESTE PARADO": "#f97316", "PROPOSTA ENVIADA": "#a855f7", "AGUARDANDO PAGAMENTO": "#22c55e", "CONVERTIDO": "#10b981",
  "STAND-BY": "#f59e0b", "PERDIDO": "#ef4444",
};
const ENCERRADO = new Set(["CONVERTIDO", "PERDIDO"]);
const titulo = (e: string) => e.charAt(0) + e.slice(1).toLowerCase();
const plural = (n: number, s: string, p: string) => `${n} ${n === 1 ? s : p}`;
const campo = "rounded-lg border border-edge bg-surface px-2.5 py-1.5 text-xs text-text focus:border-violet focus:outline-none";

export default function JornadaVisao({ onAbrir }: { onAbrir: (r: { chatid?: string | null; crmId?: string | null }) => void }) {
  const [v, setV] = useState<Visao | null>(null), [erro, setErro] = useState(""), [carregando, setCarregando] = useState(true);
  const [etapa, setEtapa] = useState(""), [resp, setResp] = useState(""), [ordem, setOrdem] = useState<Ordem>("prioridade");
  const [soParados, setSoParados] = useState(0), [soEsperando, setSoEsperando] = useState(false), [soCatalogos, setSoCatalogos] = useState(false);
  const [soSegunda, setSoSegunda] = useState(false), [soHoje, setSoHoje] = useState(false), [encerrados, setEncerrados] = useState(false);
  const [limite, setLimite] = useState(50);

  async function carrega() {
    setCarregando(true);
    try {
      const r = await fetch("/api/jornada/visao", { cache: "no-store" });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.erro || (r.status === 401 ? "Entre no Atendimento para ver a visão geral." : "Não foi possível carregar a visão geral."));
      setV(d); setErro("");
    } catch (e) { setErro(e instanceof Error ? e.message : "Falha ao carregar."); } finally { setCarregando(false); }
  }
  useEffect(() => { void carrega(); }, []);
  useEffect(() => { setLimite(50); }, [etapa, resp, ordem, soParados, soEsperando, soCatalogos, soSegunda, soHoje, encerrados]);

  const lista = useMemo(() => {
    if (!v) return [];
    const out = v.itens.filter(x =>
      (!etapa || x.etapa === etapa) && (encerrados || etapa || !ENCERRADO.has(x.etapa)) &&
      (!resp || (resp === "_sem" ? !x.responsavel : x.responsavel === resp)) &&
      (!soParados || (x.etapa !== "NOVO" && !ENCERRADO.has(x.etapa) && (x.dias_parado ?? 0) >= soParados)) &&
      (!soEsperando || x.esperando) && (!soCatalogos || !!x.catalogo) && (!soSegunda || !!x.catalogo?.segunda_chance) &&
      (!soHoje || x.prioridade >= 450));
    const cmp: Record<Ordem, (a: ItemVisao, b: ItemVisao) => number> = {
      prioridade: (a, b) => b.prioridade - a.prioridade || b.ultima_ts - a.ultima_ts,
      parado: (a, b) => (b.dias_parado ?? -1) - (a.dias_parado ?? -1),
      etapa: (a, b) => (b.dias_na_etapa ?? -1) - (a.dias_na_etapa ?? -1),
      recente: (a, b) => b.ultima_ts - a.ultima_ts,
    };
    return out.sort(cmp[ordem]);
  }, [v, etapa, resp, ordem, soParados, soEsperando, soCatalogos, soSegunda, soHoje, encerrados]);

  function limpa() { setEtapa(""); setResp(""); setSoParados(0); setSoEsperando(false); setSoCatalogos(false); setSoSegunda(false); setSoHoje(false); }
  function destaque(f: () => void) { limpa(); f(); }

  if (erro && !v) return <div role="alert" className="rounded-lg border border-rose/40 px-4 py-3 text-sm text-rose">{erro} <button onClick={() => void carrega()} className="ml-2 underline">Tentar de novo</button></div>;
  if (!v) return <p role="status" className="text-sm text-muted">Carregando a visão geral…</p>;
  const r = v.resumo, lucas = v.usuario === "lucas";
  const filtrando = !!(etapa || resp || soParados || soEsperando || soCatalogos || soSegunda || soHoje);

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-bright">Visão geral {lucas ? "· todos os leads" : "· seus leads e os sem responsável"}</h2>
          <span className="text-xs text-muted">{plural(r.total, "lead", "leads")} · atualizado {v.gerado_em.slice(11)}
            <button onClick={() => void carrega()} disabled={carregando} className="ml-2 text-violet-light disabled:opacity-50">{carregando ? "atualizando…" : "atualizar"}</button></span>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
          <Destaque cor="#22c55e" rotulo="Esperando resposta" valor={r.esperando} sub="cliente falou por último" ativo={soEsperando} onClick={() => destaque(() => setSoEsperando(true))} />
          <Destaque cor="#8b5cf6" rotulo="Para fazer hoje" valor={r.para_hoje} sub="com motivo pra agir" ativo={soHoje} onClick={() => destaque(() => setSoHoje(true))} />
          <Destaque cor="#f59e0b" rotulo="Parados 3+ dias" valor={r.parados_3} sub="sem interação" ativo={soParados === 3} onClick={() => destaque(() => setSoParados(3))} />
          <Destaque cor="#f97316" rotulo="Parados 7+ dias" valor={r.parados_7} sub="sem interação" ativo={soParados === 7} onClick={() => destaque(() => setSoParados(7))} />
          <Destaque cor="#ef4444" rotulo="Parados 15+ dias" valor={r.parados_15} sub="sem interação" ativo={soParados === 15} onClick={() => destaque(() => setSoParados(15))} />
          <Destaque cor="#e879f9" rotulo="Segunda chance" valor={r.segunda_chance} sub={`de ${plural(r.catalogos, "catálogo", "catálogos")}`} ativo={soSegunda} onClick={() => destaque(() => setSoSegunda(true))} />
        </div>
        <div className="flex gap-2 overflow-x-auto pb-1" role="list" aria-label="Leads por etapa do funil">
          {v.etapas.map(e => (
            <button key={e} role="listitem" onClick={() => setEtapa(etapa === e ? "" : e)} aria-pressed={etapa === e}
              className={`min-w-[104px] shrink-0 rounded-lg border px-3 py-2 text-left transition-colors ${etapa === e ? "border-violet bg-active-bg" : "border-edge bg-raised hover:border-violet/40"}`}>
              <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted"><i className="h-2 w-2 shrink-0 rounded-full" style={{ background: ETAPA_COR[e] }} />{titulo(e)}</span>
              <b className="mt-0.5 block text-lg font-semibold tabular-nums text-bright">{r.por_etapa[e] ?? 0}</b>
            </button>
          ))}
        </div>
        {v.fontes.avisos.map(a => <p key={a} className="text-[11px] text-amber">⚠ {a}</p>)}
      </section>

      <section className="rounded-xl border border-edge bg-raised p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap items-end gap-2">
          <h3 className="mr-auto text-sm font-semibold text-bright">O que fazer hoje <span className="font-normal text-muted">· {plural(lista.length, "lead", "leads")}</span></h3>
          <select aria-label="Etapa" className={campo} value={etapa} onChange={e => setEtapa(e.target.value)}>
            <option value="">Todas as etapas</option>{v.etapas.map(e => <option key={e} value={e}>{titulo(e)}</option>)}
          </select>
          <select aria-label="Responsável" className={campo} value={resp} onChange={e => setResp(e.target.value)}>
            <option value="">{lucas ? "Todos os responsáveis" : "Meus + sem responsável"}</option>
            {lucas && <option value="Lucas">Lucas</option>}<option value="Dione">{lucas ? "Dione" : "Só os meus"}</option><option value="_sem">Sem responsável</option>
          </select>
          <select aria-label="Ordenar" className={campo} value={ordem} onChange={e => setOrdem(e.target.value as Ordem)}>
            <option value="prioridade">Prioridade</option><option value="parado">Mais tempo parado</option>
            <option value="etapa">Mais tempo na etapa</option><option value="recente">Interação mais recente</option>
          </select>
        </div>
        <div className="mb-3 flex flex-wrap gap-1.5 text-[11px]">
          <Chip on={soEsperando} onClick={() => setSoEsperando(!soEsperando)}>🟢 Só esperando resposta</Chip>
          <Chip on={soParados > 0} onClick={() => setSoParados(soParados ? 0 : 3)}>⏰ Só parados ({soParados || 3}+ dias)</Chip>
          <Chip on={soCatalogos} onClick={() => setSoCatalogos(!soCatalogos)}>📦 Só catálogos</Chip>
          <Chip on={soSegunda} onClick={() => setSoSegunda(!soSegunda)}>🎁 Segunda chance</Chip>
          <Chip on={encerrados} onClick={() => setEncerrados(!encerrados)}>Mostrar convertidos e perdidos</Chip>
          {filtrando && <button onClick={limpa} className="px-2 text-violet-light">limpar filtros</button>}
        </div>
        {!lista.length && <p className="py-8 text-center text-xs text-muted">Nenhum lead com esses filtros.</p>}
        <ul className="divide-y divide-edge-subtle">
          {lista.slice(0, limite).map(x => (
            <li key={(x.chatid || "") + (x.crm_id || "")}>
              <button onClick={() => onAbrir({ chatid: x.chatid, crmId: x.crm_id })}
                className="grid w-full gap-x-4 gap-y-1 rounded-lg px-2 py-3 text-left hover:bg-active-bg md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)_minmax(0,1.4fr)_90px]">
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 text-sm font-medium text-bright">{x.esperando && <i className="h-2 w-2 shrink-0 rounded-full bg-emerald" title="Cliente esperando resposta" />}<span className="truncate">{x.nome}</span></span>
                  {x.motivo && <span className="block truncate text-[11px] text-violet-light">{x.motivo}</span>}
                  {x.motivo_perda && <span className="block text-[11px] text-muted">Motivo: {x.motivo_perda}</span>}
                </span>
                <span className="text-xs text-sub">
                  <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full" style={{ background: ETAPA_COR[x.etapa] || "#8490a3" }} />{titulo(x.etapa)}</span>
                  <small className="block text-[11px] text-muted">{x.dias_na_etapa == null ? "tempo na etapa: sem registro" : x.dias_na_etapa === 0 ? "entrou hoje na etapa" : `há ${plural(x.dias_na_etapa, "dia", "dias")} na etapa`}</small>
                </span>
                <span className="min-w-0 text-xs text-sub">
                  {x.ultima ? <>
                    <small className="block text-[11px] text-muted">{x.ultima.aprox ? "atualizado no CRM" : x.ultima.quem === "lead" ? "lead falou" : "nós falamos"} · {x.ultima.quando.slice(0, 5)}{x.dias_parado ? ` · há ${plural(x.dias_parado, "dia", "dias")}` : " · hoje"}{x.ultima.canal === "grupo" ? " · grupo" : ""}</small>
                    <span className="block truncate">{x.ultima.aprox ? "—" : x.ultima.texto || "[mídia]"}</span>
                  </> : <span className="text-muted">sem conversa</span>}
                </span>
                <span className="text-xs text-muted md:text-right">{x.responsavel || "Sem responsável"}</span>
                {x.sinais.some(s => s.k !== "esperando") && <span className="flex flex-wrap gap-1 md:col-span-4">
                  {x.sinais.filter(s => s.k !== "esperando").map((s, i) => <span key={i} className={`rounded-full px-2 py-0.5 text-[10px] ${s.k === "esperando" ? "bg-emerald/10 text-emerald" : s.k === "parado" ? "bg-amber/10 text-amber" : s.k === "financeiro" ? "bg-amber/10 text-amber" : "bg-panel text-sub"}`}>{s.t}</span>)}
                </span>}
              </button>
            </li>
          ))}
        </ul>
        {lista.length > limite && <button onClick={() => setLimite(l => l + 100)} className="mt-3 w-full rounded-lg border border-edge py-2 text-xs text-muted hover:text-bright">Mostrar mais ({lista.length - limite} restantes)</button>}
      </section>
    </div>
  );
}

function Destaque({ cor, rotulo, valor, sub, ativo, onClick }: { cor: string; rotulo: string; valor: number; sub: string; ativo: boolean; onClick: () => void }) {
  return <button onClick={onClick} aria-pressed={ativo}
    className={`rounded-xl border p-3 text-left transition-colors ${ativo ? "border-violet bg-active-bg" : "border-edge bg-raised hover:border-violet/40"}`}>
    <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted"><i className="h-2 w-2 rounded-full" style={{ background: cor }} />{rotulo}</span>
    <b className="mt-1 block text-2xl font-semibold tabular-nums text-bright">{valor}</b>
    <small className="text-[11px] text-muted">{sub}</small>
  </button>;
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return <button onClick={onClick} aria-pressed={on} className={`rounded-full border px-2.5 py-1 transition-colors ${on ? "border-violet bg-active-bg text-bright" : "border-edge text-muted hover:text-sub"}`}>{children}</button>;
}
