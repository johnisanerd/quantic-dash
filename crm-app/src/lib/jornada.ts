// Utilitários compartilhados da aba Jornada (página, visão geral, drawer e Responder).
export function normFone(f: string) { let d = (f || "").replace(/\D/g, ""); if (d.length > 11 && d.startsWith("55")) d = d.slice(2); return d.replace(/^0+/, ""); }
export function fmtFone(v: string | null | undefined) {
  const d = normFone(String(v || ""));
  if (d.length === 11) return `(${d.slice(0, 2)}) ${d.slice(2, 7)}-${d.slice(7)}`;
  if (d.length === 10) return `(${d.slice(0, 2)}) ${d.slice(2, 6)}-${d.slice(6)}`;
  return d;
}
export const plural = (n: number, s: string, p: string) => `${n} ${n === 1 ? s : p}`;
export const ETAPA_COR: Record<string, string> = {
  "NOVO": "#3b82f6", "EM CONVERSA": "#0ea5e9", "INTERESSADO": "#8b5cf6", "AGUARDANDO DADOS": "#06b6d4", "EM TESTE": "#84cc16",
  "TESTE PARADO": "#f97316", "PROPOSTA ENVIADA": "#a855f7", "AGUARDANDO PAGAMENTO": "#22c55e", "CONVERTIDO": "#10b981",
  "STAND-BY": "#f59e0b", "PERDIDO": "#ef4444",
};
export const tituloEtapa = (e: string) => e.charAt(0) + e.slice(1).toLowerCase();
export function ha(seg: number) {
  if (!seg) return "";
  const s = Math.max(0, Date.now() / 1000 - seg);
  if (s < 3600) return `há ${Math.max(1, Math.round(s / 60))} min`;
  if (s < 86400) return `há ${Math.round(s / 3600)} h`;
  const d = Math.floor(s / 86400);
  return d === 1 ? "ontem" : `há ${d} dias`;
}
export async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url, { cache: "no-store" });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((d as { erro?: string }).erro || (r.status === 401 ? "Entre no Atendimento para ver a jornada." : "Falha ao carregar."));
  return d as T;
}
export async function postJson<T>(url: string, body: unknown, keepalive = false): Promise<T> {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), keepalive });
  const d = await r.json().catch(() => ({}));
  if (!r.ok || (d as { ok?: boolean }).ok === false) throw new Error((d as { erro?: string }).erro || "Não foi possível concluir.");
  return d as T;
}
