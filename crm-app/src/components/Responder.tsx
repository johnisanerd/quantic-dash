import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getJson, postJson } from "../lib/jornada";

// Quadro "Responder" (aba Jornada): últimas mensagens + sugestão do Jev já preenchida e editável.
// Só envia quando a pessoa clica em Enviar (mesmo envio do Atendimento, no servidor).
type Msg = { id: string; de: "nos" | "lead"; hora: string; texto: string; midia: boolean; transcricao: string };
type Conversa = { chatid: string; nome: string; esperando: boolean; mensagens: Msg[] };
type Sugestao = { id?: number; resposta?: string; porque?: string; alerta?: string; modelo?: string; cache?: boolean; erro?: string };

export default function Responder({ chatid, onEnviado, rodape = false }: { chatid: string; onEnviado?: (chatid: string) => void; rodape?: boolean }) {
  const [conv, setConv] = useState<Conversa | null>(null), [erroConv, setErroConv] = useState("");
  const [sug, setSug] = useState<Sugestao | null>(null), [gerando, setGerando] = useState(true);
  const [texto, setTexto] = useState(""), [editou, setEditou] = useState(false);
  const [enviando, setEnviando] = useState(false), [enviado, setEnviado] = useState(false), [erro, setErro] = useState("");
  const pendente = useRef<number | null>(null);   // sugestão aberta que ainda não foi enviada
  const lista = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let vivo = true;
    setConv(null); setSug(null); setTexto(""); setEditou(false); setEnviado(false); setErro(""); setGerando(true);
    getJson<Conversa>("/api/jornada/conversa?chatid=" + encodeURIComponent(chatid))
      .then(d => { if (vivo) setConv(d); }).catch(e => { if (vivo) setErroConv(e instanceof Error ? e.message : "Falha ao carregar a conversa."); });
    postJson<Sugestao>("/api/jornada/sugestao", { chatid })
      .then(d => { if (!vivo) return; setSug(d); if (d.resposta) { setTexto(t => t || d.resposta!); pendente.current = d.id ?? null; } })
      .catch(e => { if (vivo) setSug({ erro: e instanceof Error ? e.message : "O Jev não conseguiu sugerir agora." }); })
      .finally(() => { if (vivo) setGerando(false); });
    return () => {
      vivo = false;
      // fechou sem enviar: registra a sugestão como descartada (serve pra medir o Jev)
      if (pendente.current) void postJson("/api/jornada/descartar", { id: pendente.current }, true).catch(() => {});
    };
  }, [chatid]);
  useEffect(() => { lista.current?.scrollTo({ top: lista.current.scrollHeight }); }, [conv]);

  async function outra() {
    setGerando(true); setErro("");
    try {
      const d = await postJson<Sugestao>("/api/jornada/sugestao", { chatid, nova: true });
      setSug(d);
      if (d.resposta) { setTexto(d.resposta); setEditou(false); pendente.current = d.id ?? null; }
    } catch (e) { setSug({ erro: e instanceof Error ? e.message : "O Jev não conseguiu sugerir agora." }); } finally { setGerando(false); }
  }

  async function envia() {
    if (!texto.trim() || enviando) return;
    setEnviando(true); setErro("");
    try {
      await postJson("/api/jornada/enviar", { chatid, texto, sugestao_id: pendente.current });
      pendente.current = null;
      setEnviado(true);
      setConv(c => c ? { ...c, esperando: false, mensagens: [...c.mensagens, { id: "local", de: "nos", hora: "agora", texto, midia: false, transcricao: "" }] } : c);
      onEnviado?.(chatid);
    } catch (e) { setErro(e instanceof Error ? e.message : "Não foi possível enviar."); } finally { setEnviando(false); }
  }

  return (
    <div className={`grid gap-3 ${rodape ? "" : "rounded-xl border border-violet/40 bg-surface p-3"} md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]`}>
      <div ref={lista} className="max-h-64 space-y-1.5 overflow-y-auto pr-1" aria-label="Últimas mensagens">
        {erroConv && <p className="text-xs text-rose">{erroConv}</p>}
        {!conv && !erroConv && <p className="text-xs text-muted">Carregando conversa…</p>}
        {conv && !conv.mensagens.length && <p className="text-xs text-muted">Conversa ainda sem mensagens.</p>}
        {conv?.mensagens.map(m => (
          <div key={m.id} className={`max-w-[90%] rounded-lg px-2.5 py-1.5 text-xs ${m.de === "nos" ? "ml-auto bg-violet/10" : "bg-raised"} text-sub`}>
            <span className="block text-[10px] text-muted">{m.hora} · {m.de === "nos" ? "nós" : "cliente"}</span>
            <span className="whitespace-pre-wrap break-words">{m.texto || "[mensagem vazia]"}</span>
            {m.transcricao && <span className="mt-0.5 block italic text-muted">“{m.transcricao}”</span>}
          </div>
        ))}
      </div>
      <div className="flex min-w-0 flex-col gap-2">
        <div className="flex items-center gap-2 text-[11px]">
          <span className="shrink-0 whitespace-nowrap font-semibold text-violet-light">✨ Jev sugere</span>
          {gerando && <span className="text-muted">pensando na resposta…</span>}
          {!gerando && sug?.porque && <span className="truncate text-muted" title={sug.porque}>· {sug.porque}</span>}
        </div>
        {sug?.erro && <p className="text-[11px] text-amber">{sug.erro}</p>}
        {sug?.alerta && <p className="text-[11px] text-rose">⚠ {sug.alerta}</p>}
        <textarea value={texto} onChange={e => { setTexto(e.target.value); setEditou(true); }} rows={4} maxLength={4000}
          aria-label="Mensagem para enviar" placeholder={gerando ? "O Jev está escrevendo uma sugestão…" : "Escreva a mensagem"}
          className="w-full resize-y rounded-lg border border-edge bg-raised px-3 py-2 text-xs text-text placeholder:text-dim focus:border-violet focus:outline-none" />
        {erro && <p role="alert" className="text-[11px] text-rose">{erro}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => void envia()} disabled={!texto.trim() || enviando || enviado}
            className="rounded-lg bg-violet px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
            {enviado ? "Enviado ✓" : enviando ? "Enviando…" : "Enviar"}</button>
          <button onClick={() => void outra()} disabled={gerando || enviado} className="rounded-lg border border-edge px-3 py-1.5 text-xs text-sub hover:text-bright disabled:opacity-50">
            Gerar outra sugestão</button>
          <Link to={`/atendimento?chatid=${encodeURIComponent(chatid)}`} className="text-xs text-muted hover:text-bright">Abrir no Atendimento →</Link>
          {editou && sug?.resposta && !enviado && <span className="text-[10px] text-dim">editada</span>}
        </div>
      </div>
    </div>
  );
}
