import { useEffect, useMemo, useState } from "react";

type Situacao = "a_receber" | "paga";
type Item = {
  chatid: string; cliente: string; fone: string | null; responsavel: string | null; plano: string;
  mensalidade_centavos: number; comissao_centavos: number; fechado_em: string;
  cliente_pagou_em: string | null; comissao_paga_em: string | null; situacao: Situacao;
};
type Resp = { pct: number; canEdit: boolean; usuario: string; itens: Item[]; totais: Record<Situacao, number> };

const brl = (c: number) => (c / 100).toLocaleString("pt-BR", { style: "currency", currency: "BRL" });
const data = (v: string | null) => v ? new Date(v).toLocaleDateString("pt-BR", { timeZone: "America/Sao_Paulo" }) : "—";

const SIT: Record<Situacao, { label: string; cls: string; hint: string }> = {
  a_receber: { label: "A receber", cls: "bg-cyan/10 text-cyan", hint: "Cliente pagou — comissão liberada" },
  paga: { label: "Paga", cls: "bg-emerald/10 text-emerald", hint: "Comissão já paga ao vendedor" },
};

export default function Comissoes() {
  const [d, setD] = useState<Resp | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState<string | null>(null);
  const [resp, setResp] = useState("");
  const [sit, setSit] = useState<"" | Situacao>("");

  async function load() {
    setError("");
    try {
      const r = await fetch("/api/comissoes", { credentials: "same-origin" });
      if (!r.ok) throw new Error(r.status === 401 ? "Entre no Atendimento para ver suas comissões." : "Não foi possível carregar as comissões.");
      setD(await r.json());
    } catch (e) { setError(e instanceof Error ? e.message : "Erro ao carregar."); }
    finally { setLoading(false); }
  }
  useEffect(() => { void load(); }, []);

  async function marcar(it: Item, campo: "cliente_pagou" | "comissao_paga", marcado: boolean) {
    setSaving(it.chatid + campo); setError("");
    try {
      const r = await fetch("/api/comissoes/marcar", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ chatid: it.chatid, campo, marcado }),
      });
      if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.erro || "Não foi possível salvar."); }
      await load();
    } catch (e) { setError(e instanceof Error ? e.message : "Falha ao salvar."); }
    finally { setSaving(null); }
  }

  const responsaveis = useMemo(() => [...new Set((d?.itens || []).map(i => i.responsavel || "Sem responsável"))], [d]);
  const itens = (d?.itens || []).filter(i => (!resp || (i.responsavel || "Sem responsável") === resp) && (!sit || i.situacao === sit));
  const tot = itens.reduce((a, i) => { a[i.situacao] += i.comissao_centavos; return a; }, { a_receber: 0, paga: 0 } as Record<Situacao, number>);

  return (
    <div className="mx-auto max-w-6xl space-y-6 p-4 sm:p-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold text-bright">Comissões</h1>
          <p className="mt-1 text-sm text-muted">
            {d ? `${d.pct}% sobre a 1ª mensalidade — só clientes que já pagaram.` : "Comissão do comercial por cliente que já pagou."}
            {d && !d.canEdit && ` Mostrando as comissões de ${d.usuario}.`}
          </p>
        </div>
        <button onClick={() => { setLoading(true); void load(); }} className="rounded-lg border border-edge px-4 py-2 text-sm text-muted hover:text-bright">Atualizar</button>
      </header>

      {error && <div role="alert" className="rounded-lg border border-rose/40 px-4 py-3 text-sm text-rose">{error}</div>}

      <section className="grid gap-3 sm:grid-cols-2">
        {(["a_receber", "paga"] as Situacao[]).map(k => (
          <button key={k} onClick={() => setSit(sit === k ? "" : k)} aria-pressed={sit === k}
            className={`rounded-xl border p-4 text-left transition ${sit === k ? "border-violet bg-active-bg" : "border-edge-subtle bg-raised hover:border-edge"}`}>
            <span className="text-xs text-muted">{SIT[k].label}</span>
            <strong className="mt-1 block text-2xl tabular-nums text-bright">{brl(tot[k])}</strong>
            <span className="text-[11px] text-dim">{SIT[k].hint}</span>
          </button>
        ))}
      </section>

      {d?.canEdit && responsaveis.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-muted">Responsável:</span>
          {["", ...responsaveis].map(r => (
            <button key={r || "todos"} onClick={() => setResp(r)} aria-pressed={resp === r}
              className={`rounded-full border px-3 py-1 ${resp === r ? "border-violet bg-violet text-white" : "border-edge text-muted"}`}>{r || "Todos"}</button>
          ))}
        </div>
      )}

      <section className="overflow-x-auto rounded-xl border border-edge-subtle bg-raised">
        {loading ? <p className="p-6 text-sm text-muted">Carregando…</p> :
          !itens.length ? <p className="p-6 text-sm text-muted">Nenhum cliente pagante{sit ? " nessa situação" : ""}. Para contar aqui, o cliente precisa estar em <b>Convertido</b> com o plano registrado e a 1ª mensalidade paga.</p> :
          <table className="w-full min-w-[760px] text-sm">
            <thead className="text-left text-xs text-muted">
              <tr className="border-b border-edge-subtle">
                <th className="px-4 py-3 font-medium">Cliente</th>
                {d?.canEdit && <th className="px-4 py-3 font-medium">Responsável</th>}
                <th className="px-4 py-3 font-medium">Plano</th>
                <th className="px-4 py-3 text-right font-medium">Mensalidade</th>
                <th className="px-4 py-3 text-right font-medium">Comissão</th>
                <th className="px-4 py-3 font-medium">Fechado em</th>
                <th className="px-4 py-3 font-medium">Situação</th>
                {d?.canEdit && <th className="px-4 py-3 font-medium">Ações</th>}
              </tr>
            </thead>
            <tbody>
              {itens.map(i => (
                <tr key={i.chatid} className="border-b border-edge-subtle last:border-0">
                  <td className="px-4 py-3"><strong className="block text-bright">{i.cliente}</strong><small className="text-dim">{i.fone}</small></td>
                  {d?.canEdit && <td className="px-4 py-3 text-muted">{i.responsavel || "Sem responsável"}</td>}
                  <td className="px-4 py-3">{i.plano}</td>
                  <td className="px-4 py-3 text-right tabular-nums">{brl(i.mensalidade_centavos)}</td>
                  <td className="px-4 py-3 text-right font-semibold tabular-nums text-bright">{brl(i.comissao_centavos)}</td>
                  <td className="px-4 py-3 text-muted">{data(i.fechado_em)}</td>
                  <td className="px-4 py-3">
                    <span className={`inline-block rounded-md px-2 py-1 text-xs font-medium ${SIT[i.situacao].cls}`}>{SIT[i.situacao].label}</span>
                    {i.situacao === "a_receber" && <small className="mt-1 block text-dim">cliente pagou {data(i.cliente_pagou_em)}</small>}
                    {i.situacao === "paga" && <small className="mt-1 block text-dim">paga em {data(i.comissao_paga_em)}</small>}
                  </td>
                  {d?.canEdit && (
                    <td className="px-4 py-3">
                      <div className="flex flex-col gap-1.5">
                        <button disabled={!!saving || i.situacao === "paga"} onClick={() => void marcar(i, "cliente_pagou", !i.cliente_pagou_em)}
                          className="rounded-md border border-edge px-2.5 py-1 text-xs text-muted hover:text-bright disabled:opacity-40">
                          {i.cliente_pagou_em ? "Desfazer “cliente pagou”" : "Cliente pagou"}
                        </button>
                        <button disabled={!!saving || !i.cliente_pagou_em} onClick={() => void marcar(i, "comissao_paga", !i.comissao_paga_em)}
                          className="rounded-md border border-edge px-2.5 py-1 text-xs text-muted hover:text-bright disabled:opacity-40">
                          {i.comissao_paga_em ? "Desfazer “paga”" : "Comissão paga"}
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>}
      </section>
    </div>
  );
}
