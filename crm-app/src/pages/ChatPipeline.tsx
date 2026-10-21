import { useEffect, useState } from "react";
import { DndContext, DragOverlay, MouseSensor, TouchSensor, useSensor, useSensors, useDraggable, useDroppable } from "@dnd-kit/core";
import type { DragEndEvent } from "@dnd-kit/core";
import { saoPauloDay, shiftDay } from "../lib/period";
import { supabase } from "../lib/supabase";
import { applyCustomLeadStatuses, persistLeadStatus } from "../lib/lead-status";
import { Link } from "react-router-dom";
import "./ChatPipeline.css";
import LeadHistorico from "../components/LeadHistorico";
import { BarChart, Bar, PieChart, Pie, Cell, XAxis, YAxis, Tooltip, CartesianGrid, ResponsiveContainer } from "recharts";

type Plan={nome:string;preco:string};
// Plano fora da tabela (acordo especial): grava "Personalizado — <descrição>"; o servidor aceita esse prefixo.
const CUSTOM_PLAN="Personalizado",CUSTOM_KEY="__personalizado__";
type Sale={plano:string;valor_centavos:number};
type Lead={venda?:Sale|null;chatid:string;nome:string;fone:string;status:string;responsavel:string|null;quando:string;ultimo_ts:number|null;ultimo_lead_ts?:number|null;ha:string;ultima:string;origem?:"crm";crmId?:string;hasConv?:boolean;grupoChatid?:string|null;grupoNome?:string|null;diasTeste?:number|null};
// 21/10/2026 (Dione): sem as colunas Novo e Em conversa — a atenção fica em Esperando e Sem resposta; dali ela move para as etapas.
const stages=[{label:"Esperando",value:"",color:"#7c3aed"},{label:"Sem resposta",value:"_sem_resposta",color:"#8490a3"},{label:"Interessado",value:"INTERESSADO",color:"#8b5cf6"},{label:"Aguardando dados",value:"AGUARDANDO DADOS",color:"#06b6d4"},{label:"Em teste",value:"EM TESTE",color:"#84cc16"},{label:"Teste parado",value:"TESTE PARADO",color:"#f97316"},{label:"Proposta enviada",value:"PROPOSTA ENVIADA",color:"#a855f7"},{label:"Aguardando pagamento",value:"AGUARDANDO PAGAMENTO",color:"#22c55e"},{label:"Convertido",value:"CONVERTIDO",color:"#10b981"},{label:"Stand-by",value:"STAND-BY",color:"#f59e0b"},{label:"Perdido",value:"PERDIDO",color:"#ef4444"},{label:"Removidos",value:"_ocultos",color:"#8490a3"}];
// Colunas comerciais: passam a ler do banco (Supabase) — fonte da verdade do CRM.
// As demais (Esperando, Sem resposta, Mensagem 1-3, Stand-by, Removidos) seguem do painel.
const COMMERCIAL=new Set(["INTERESSADO","AGUARDANDO DADOS","EM TESTE","TESTE PARADO","PROPOSTA ENVIADA","AGUARDANDO PAGAMENTO","CONVERTIDO","STAND-BY","PERDIDO"]);
// Mesmo mapa do backend (PIPELINE_REMOTE_STATUS): etapa do painel <-> slug do Supabase.
const PANEL_SLUG:Record<string,string>={"NOVO":"novo","EM CONVERSA":"respondeu","INTERESSADO":"interessado","AGUARDANDO DADOS":"testando","EM TESTE":"testando_ativo","TESTE PARADO":"passou_prazo","PROPOSTA ENVIADA":"proposta_enviada","AGUARDANDO PAGAMENTO":"aguardando_pagamento","CONVERTIDO":"fechou","STAND-BY":"stand_by","PERDIDO":"perdida"};
// Stand-by pede quando retomar; Perdido pede o motivo (funil out/2026).
const MOTIVOS=["caro","sem interesse","já tem solução","sem loja ou site","número errado","outro"];
function extrasDaEtapa(target:string):Record<string,unknown>|null{if(target==="STAND-BY"){const d=window.prompt("Retomar o contato em quantos dias?","14");if(d===null)return null;return {retomar_dias:parseInt(d,10)||14}}if(target==="PERDIDO"){const r=window.prompt("Motivo da perda:\n"+MOTIVOS.map((m,i)=>(i+1)+" - "+m).join("\n")+"\n\nDigite o número:","2");if(r===null)return null;return {motivo:MOTIVOS[(parseInt(r,10)||6)-1]||"outro"}}return {}}
async function salvaExtrasCrm(crmId:string,ex:Record<string,unknown>){const up:Record<string,unknown>={};if(ex.retomar_dias){const d=new Date();d.setDate(d.getDate()+Number(ex.retomar_dias));up.retomar_em=d.toISOString().slice(0,10)}if(ex.motivo)up.motivo_perda=ex.motivo;if(Object.keys(up).length){const {error}=await supabase.from("leads").update(up).eq("id",crmId);if(error)throw new Error(error.message)}}
function normFone(f:string){let d=(f||"").replace(/\D/g,"");if(d.length>11&&d.startsWith("55"))d=d.slice(2);return d.replace(/^0+/,"");}
function DragCard({lead,stage,disabled,onOpen,children}:{lead:Lead;stage:string;disabled:boolean;onOpen:()=>void;children:React.ReactNode}){
 const {attributes,listeners,setNodeRef,transform,isDragging}=useDraggable({id:stage+":"+(lead.crmId||lead.chatid),data:{lead,stage},disabled});
 return <button ref={setNodeRef} {...attributes} {...listeners} className="chat-pipeline-card" style={{opacity:isDragging?.3:1,transform:transform?`translate3d(${transform.x}px,${transform.y}px,0)`:undefined}} onClick={()=>{if(!isDragging)onOpen()}}>{children}</button>
}
function DropColumn({stage,disabled,children}:{stage:string;disabled:boolean;children:React.ReactNode}){
 const automatic=stage===""||stage==="_sem_resposta";
 const {setNodeRef,isOver}=useDroppable({id:stage||"waiting",disabled:disabled||automatic});
 return <section ref={setNodeRef} className={"chat-pipeline-column"+(isOver?" chat-pipeline-drop":"")} title={automatic?"Etapa automática conforme a última mensagem":undefined}>{children}</section>
}
export default function ChatPipeline(){
 const [from,setFrom]=useState(""),[to,setTo]=useState("");
 const [columns,setColumns]=useState<Lead[][]>(stages.map(()=>[])),[loading,setLoading]=useState(true),[error,setError]=useState("");
 const [search,setSearch]=useState(""),[owner,setOwner]=useState(""),[selected,setSelected]=useState<{lead:Lead;removed:boolean}|null>(null),[saving,setSaving]=useState(false);
 const [plans,setPlans]=useState<Plan[]>([]),[closing,setClosing]=useState(false),[plan,setPlan]=useState(""),[price,setPrice]=useState(""),[customDesc,setCustomDesc]=useState("");
 useEffect(()=>{fetch("/api/prontos").then(r=>{if(!r.ok)throw new Error();return r.json()}).then(d=>setPlans(d.planos||[])).catch(()=>setError("Não foi possível carregar os planos. Atualize a página."))},[]);
 function openSale(lead:Lead,removed=false){setError("");setSelected({lead,removed});setClosing(true);const _vp=lead.venda?.plano||"";if(_vp.startsWith(CUSTOM_PLAN)){setPlan(CUSTOM_KEY);setCustomDesc(_vp.slice(CUSTOM_PLAN.length).replace(/^\s*—\s*/,""));}else{setPlan(_vp);setCustomDesc("");}setPrice(lead.venda?(lead.venda.valor_centavos/100).toFixed(2):"");}
 const [dragged,setDragged]=useState<Lead|null>(null);
 const sensors=useSensors(useSensor(MouseSensor,{activationConstraint:{distance:6}}),useSensor(TouchSensor,{activationConstraint:{delay:350,tolerance:8}}));
 const [limits,setLimits]=useState(stages.map(()=>60));
 async function load(){try{
   // 1. Painel do WhatsApp (fluxo de conversa)
   const panel=await Promise.all(stages.map(async s=>{const r=await fetch(`/api/fila?status=${encodeURIComponent(s.value)}`);if(!r.ok)throw new Error(r.status===401?"Entre no Atendimento para acessar o pipeline de conversas.":"Não foi possível carregar as conversas.");return await r.json() as Lead[]}));
   // 2. Banco (CRM) + índice de conversas por telefone
   const [crmRes,catRes,convs]=await Promise.all([
     supabase.from("leads").select("id,nome_loja,telefone,whatsapp,email,status,responsavel,updated_at,teste_gratis_em"),
     supabase.from("pl_catalog_stores").select("display_name,owner_email,whatsapp,created_at"),
     fetch("/api/conversas").then(r=>r.ok?r.json():[]).catch(()=>[]) as Promise<Array<{chatid:string;fone:string;responsavel:string|null;ultimo_ts:number|null;ultimo_lead_ts?:number|null;quando:string;ultima:string;venda:Sale|null;grupo_chatid?:string|null;grupo_nome?:string|null;sem_conversa?:boolean}>>,
   ]);
   const crmLeads=await applyCustomLeadStatuses((crmRes.data||[]) as any[]) as Array<{id:string;nome_loja:string|null;telefone:string|null;whatsapp:string|null;status:string;responsavel:string|null;updated_at:string|null;email?:string|null;teste_gratis_em?:string|null}>;
   // Catálogo do lead (e-mail, telefone ou nome) -> dias desde a criação
   const cats=(catRes.data||[]) as Array<{display_name:string|null;owner_email:string|null;whatsapp:string|null;created_at:string}>;
   const coreNome=(v:string|null|undefined)=>String(v||"").replace(/\(.*?\)/g,"").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g,"").replace(/[^a-z0-9]/g,"").replace(/^(provoulevou|oticas|otica|opticas|optica)/,"");
   const catPorEmail=new Map<string,string>(),catPorFone=new Map<string,string>(),catPorNome=new Map<string,string>();
   for(const c of cats){if(c.owner_email)catPorEmail.set(c.owner_email.trim().toLowerCase(),c.created_at);const f=normFone(c.whatsapp||"").slice(-8);if(f.length===8&&!catPorFone.has(f))catPorFone.set(f,c.created_at);const n=coreNome(c.display_name);if(n.length>=4)catPorNome.set(n,c.created_at);}
   const hojeBR=Date.parse(saoPauloDay()+"T00:00:00-03:00");
   // sem catálogo (loja com widget/Nuvemshop etc.): usa a data de início do teste gravada no lead
   const diasDeTeste=(cl:{email?:string|null;nome_loja:string|null;teste_gratis_em?:string|null},f:string)=>{const iso=(cl.email&&catPorEmail.get(cl.email.trim().toLowerCase()))||catPorFone.get(f.slice(-8))||catPorNome.get(coreNome(cl.nome_loja))||(cl.teste_gratis_em?cl.teste_gratis_em.slice(0,10)+"T12:00:00-03:00":null);if(!iso)return null;const d=Date.parse(saoPauloDay(new Date(iso))+"T00:00:00-03:00");return Number.isFinite(d)?Math.max(0,Math.round((hojeBR-d)/86400000)):null;};
   const convByFone=new Map<string,typeof convs[number]>();
   const vendaByFone=new Map<string,Sale>();
   for(const c of convs){const f=normFone(c.fone);if(!f||!c.venda)continue;if(!vendaByFone.has(f))vendaByFone.set(f,c.venda);if(!vendaByFone.has(f.slice(-8)))vendaByFone.set(f.slice(-8),c.venda);}
   for(const c of convs){if(c.sem_conversa)continue;const f=normFone(c.fone);if(f){if(!convByFone.has(f))convByFone.set(f,c);const t=f.slice(-8);if(!convByFone.has(t))convByFone.set(t,c);}}
   const result=panel.map(col=>col.slice());
   const commercialPhones=new Set<string>();
   // 3. Colunas comerciais vêm do banco, enriquecidas com a conversa
   stages.forEach((s,i)=>{
     if(!COMMERCIAL.has(s.value))return;
     const slug=PANEL_SLUG[s.value];
     const cards:Lead[]=[];
     for(const cl of crmLeads){
       if(cl.status!==slug)continue;
       const f=normFone(cl.telefone||cl.whatsapp||"");if(!f)continue;
       const conv=convByFone.get(f)||convByFone.get(f.slice(-8));
       commercialPhones.add(f);commercialPhones.add(f.slice(-8));
       cards.push({origem:"crm",crmId:cl.id,hasConv:!!conv,chatid:conv?conv.chatid:("55"+f+"@s.whatsapp.net"),
         nome:cl.nome_loja||"",fone:conv?conv.fone:f,status:s.value,
         responsavel:conv?(conv.responsavel??cl.responsavel):cl.responsavel,venda:(conv&&conv.venda)||vendaByFone.get(f)||vendaByFone.get(f.slice(-8))||null,
         ultimo_ts:conv?conv.ultimo_ts:(cl.updated_at?Date.parse(cl.updated_at):null),ultimo_lead_ts:conv?(conv.ultimo_lead_ts??null):null,
         quando:conv?conv.quando:"",ha:"",ultima:conv?conv.ultima:"",grupoChatid:conv?.grupo_chatid??null,grupoNome:conv?.grupo_nome??null,diasTeste:["CONVERTIDO","PERDIDO"].includes(s.value)?null:diasDeTeste(cl,f)});
     }
     // 16/10/2026: quem respondeu por último fica no topo (a mensagem que a gente manda não reordena)
     cards.sort((a,b)=>((b.ultimo_lead_ts||0)-(a.ultimo_lead_ts||0))||((b.ultimo_ts||0)-(a.ultimo_ts||0)));
     result[i]=cards;
   });
   // 4. Dedup: quem está numa coluna comercial não repete nas colunas de fluxo
   stages.forEach((s,i)=>{if(COMMERCIAL.has(s.value))return;result[i]=result[i].filter(l=>{const f=normFone(l.fone);return !commercialPhones.has(f)&&!commercialPhones.has(f.slice(-8))})});
   setColumns(result);setError("");
  }catch(e){setError(e instanceof Error?e.message:"Erro ao carregar o pipeline.")}finally{setLoading(false)}}
 useEffect(()=>{void load();const timer=window.setInterval(()=>{void load()},30000);return()=>clearInterval(timer)},[]);
 async function update(path:string,data:Record<string,unknown>){if(!selected)return;if(path==="status"&&data.status==="CONVERTIDO"&&!("plano" in data)){openSale(selected.lead,selected.removed);return;}setSaving(true);try{
   const L=selected.lead;
   const ex=path==="status"?extrasDaEtapa(String(data.status)):{};if(ex===null){setSaving(false);return;}data={...data,...ex};
   if(L.origem==="crm"&&!L.hasConv){
     if(path==="status"){await persistLeadStatus(L.crmId!,(PANEL_SLUG[String(data.status)]||String(data.status)) as any);await salvaExtrasCrm(L.crmId!,ex);}
     else if(path==="responsavel"){const {error}=await supabase.from("leads").update({responsavel:(data.responsavel as string)||null}).eq("id",L.crmId!);if(error)throw new Error(error.message)}
   } else {
     const r=await fetch(`/api/${path}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chatid:L.chatid,...data})});if(!r.ok){const d=await r.json();throw new Error(d.erro||"Não foi possível salvar.")}
   }
   setSelected(null);await load()
  }catch(e){setError(e instanceof Error?e.message:"Falha ao salvar")}finally{setSaving(false)}}
 async function excluir(){
  if(!selected)return;
  const L=selected.lead;
  if(!window.confirm(`Excluir "${L.nome||L.fone}" do CRM? Essa ação não dá pra desfazer.`))return;
  setSaving(true);setError("");
  try{
   const body:Record<string,unknown>={};
   if(L.crmId)body.crm_id=L.crmId;
   if(L.hasConv!==false&&L.chatid)body.chatid=L.chatid;
   const r=await fetch("/api/lead/excluir",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
   if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.erro||"Não foi possível excluir o lead.")}
   setSelected(null);await load();
  }catch(e){setError(e instanceof Error?e.message:"Falha ao excluir")}finally{setSaving(false)}
 }
 async function move(event:DragEndEvent){
  setDragged(null);if(saving||!event.over)return;
  const target=String(event.over.id),source=event.active.data.current as {lead:Lead;stage:string}|undefined;
  if(!source||!stages.slice(2).some(s=>s.value===target)||target===source.stage)return;
  const crmOnly=source.lead.origem==="crm"&&!source.lead.hasConv;
  if(crmOnly&&target==="_ocultos"){setError("Lead de catálogo não fica na fila de conversas do painel.");return;}
  if(target==="CONVERTIDO"){
   if(crmOnly){setSaving(true);setError("");try{await persistLeadStatus(source.lead.crmId!,"fechou" as any);await load()}catch(e){await load();setError(e instanceof Error?e.message:"Falha ao mover o lead.")}finally{setSaving(false)}return;}
   openSale(source.lead,source.stage==="_ocultos");return;
  }
  const ex=extrasDaEtapa(target);if(ex===null)return;
  setSaving(true);setError("");
  try{
   if(crmOnly){await persistLeadStatus(source.lead.crmId!,(PANEL_SLUG[target]||target) as any);await salvaExtrasCrm(source.lead.crmId!,ex);}
   else{
    async function post(path:string,data:Record<string,unknown>){const r=await fetch(`/api/${path}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({chatid:source!.lead.chatid,...data})});if(!r.ok){const d=await r.json().catch(()=>({}));throw new Error(d.erro||"Não foi possível mover o lead.")}}
    if(target==="_ocultos")await post("ocultar",{oculto:true});else{await post("status",{status:target,...ex});if(source.stage==="_ocultos")await post("ocultar",{oculto:false})}
   }
   await load()
  }catch(e){await load();setError(e instanceof Error?e.message:"Falha ao mover o lead.")}finally{setSaving(false)}
 }
 const term=search.trim().toLocaleLowerCase("pt-BR");
 const visible=columns.map(list=>list.filter(l=>{const day=l.ultimo_ts?new Date(l.ultimo_ts>1e11?l.ultimo_ts:l.ultimo_ts*1000).toLocaleDateString("en-CA",{timeZone:"America/Sao_Paulo"}):"";return (!from||(!!day&&day>=from))&&(!to||(!!day&&day<=to))&&(!owner||(owner==="_sem"?!l.responsavel:l.responsavel===owner))&&(!term||`${l.nome} ${l.fone}`.toLocaleLowerCase("pt-BR").includes(term)||(/^[\d\s()+.-]+$/.test(term)&&l.fone.replace(/\D/g,"").includes(term.replace(/\D/g,""))))}));
 const chartData=stages.map((s,i)=>({label:s.label,color:s.color,value:visible[i].length})).filter((_,i)=>!["","_sem_resposta","_ocultos"].includes(stages[i].value));
 const chartPie=chartData.filter(d=>d.value>0);
 return <div className="chat-pipeline">

  <div className="chat-pipeline-filters"><label>Buscar lead<input placeholder="Nome ou telefone" value={search} onChange={e=>setSearch(e.target.value)}/></label><label>Responsável<select value={owner} onChange={e=>setOwner(e.target.value)}><option value="">Todos</option><option>Lucas</option><option>Dione</option><option value="_sem">Sem responsável</option></select></label><div className="pipeline-switch"><span>Atendimento · principal</span><Link to="/pipeline/anterior">Pipeline anterior</Link></div><button onClick={()=>{void load()}}>Atualizar</button><div className="pipeline-date-controls"><div className="pipeline-date-presets" aria-label="Atalhos de período">{[{label:"Hoje",days:1},{label:"Ontem",days:-1},{label:"7d",days:7},{label:"15d",days:15},{label:"30d",days:30},{label:"Mês",days:0}].map(p=>{const today=saoPauloDay(),end=p.days===-1?shiftDay(today,-1):today,start=p.days===-1?end:p.days?shiftDay(today,1-p.days):today.slice(0,7)+"-01";return <button key={p.label} aria-pressed={from===start&&to===end} onClick={()=>{setFrom(start);setTo(end)}}>{p.label}</button>})}</div><label>Última mensagem · de<input aria-label="Última mensagem desde" type="date" value={from} max={to||undefined} onChange={e=>setFrom(e.target.value)}/></label><label>Até<input aria-label="Última mensagem até" type="date" value={to} min={from||undefined} onChange={e=>setTo(e.target.value)}/></label>{(from||to)&&<button onClick={()=>{setFrom("");setTo("")}}>Limpar período</button>}</div></div>
  {error&&<div role="alert" className="chat-pipeline-error">{error} <Link to="/atendimento">Abrir Atendimento</Link></div>}
  {loading?<p role="status">Carregando conversas…</p>:<DndContext sensors={sensors} onDragStart={e=>setDragged(e.active.data.current?.lead||null)} onDragCancel={()=>setDragged(null)} onDragEnd={e=>{void move(e)}}><div className="chat-pipeline-board">{stages.map((s,i)=><DropColumn stage={s.value} disabled={saving} key={s.label}><h2><i style={{background:s.color}}/>{s.label}<span>{visible[i].length}</span></h2><div className="chat-pipeline-cards">{visible[i].slice(0,limits[i]).map(l=><DragCard lead={l} stage={s.value} disabled={saving} key={l.crmId||l.chatid} onOpen={()=>{setClosing(false);setSelected({lead:l,removed:s.value==="_ocultos"})}}><strong>{l.nome||l.fone}</strong><small>{l.fone}</small><span className="chat-pipeline-owner">♙ {l.responsavel||"Sem responsável"}</span>{l.diasTeste!=null&&<span className="chat-pipeline-owner pipeline-dias" title={"Catálogo criado há "+l.diasTeste+" dias"}>🕒 {l.diasTeste===0?"criado hoje":l.diasTeste===1?"1 dia testando":l.diasTeste+" dias testando"}</span>}{l.venda&&<span className="pipeline-sale-badge">{l.venda.plano} · {(l.venda.valor_centavos/100).toLocaleString("pt-BR",{style:"currency",currency:"BRL"})}/mês</span>}<p>{l.ultima||(l.origem==="crm"?"Catálogo — sem conversa no painel":"Sem mensagem disponível")}</p><footer><span>{l.status}</span><time>{l.quando}</time></footer></DragCard>)}{!visible[i].length&&<p className="chat-pipeline-empty">Nenhuma conversa</p>}{visible[i].length>limits[i]&&<button onClick={()=>setLimits(v=>v.map((n,j)=>i===j?n+60:n))}>Mostrar mais</button>}</div></DropColumn>)}</div><DragOverlay>{dragged&&<div className="chat-pipeline-card chat-pipeline-drag-preview"><strong>{dragged.nome||dragged.fone}</strong><small>{dragged.responsavel||"Sem responsável"}</small></div>}</DragOverlay></DndContext>}
  {!loading&&<div className="chat-pipeline-charts">
   <section className="chat-pipeline-chart"><h3>Leads por etapa</h3>
    <ResponsiveContainer width="100%" height={280}><BarChart data={chartData} margin={{top:8,right:8,left:-12,bottom:0}}>
     <CartesianGrid stroke="var(--color-edge-subtle)" vertical={false}/>
     <XAxis dataKey="label" interval={0} angle={-35} textAnchor="end" height={82} tick={{fill:"var(--color-muted)",fontSize:10}} tickLine={false} axisLine={false}/>
     <YAxis allowDecimals={false} tick={{fill:"var(--color-muted)",fontSize:10}} tickLine={false} axisLine={false}/>
     <Tooltip cursor={{fill:"var(--color-active-bg)"}} contentStyle={{background:"var(--color-surface)",border:"1px solid var(--color-edge)",borderRadius:8,fontSize:11}}/>
     <Bar dataKey="value" name="Leads" radius={[4,4,0,0]}>{chartData.map(d=><Cell key={d.label} fill={d.color}/>)}</Bar>
    </BarChart></ResponsiveContainer>
   </section>
   <section className="chat-pipeline-chart"><h3>Distribuição por etapa</h3>
    <ResponsiveContainer width="100%" height={280}><PieChart>
     <Pie data={chartPie} dataKey="value" nameKey="label" cx="50%" cy="50%" outerRadius={92} label={(e:any)=>`${e.name}: ${e.value}`} labelLine={false} isAnimationActive={false}>
      {chartPie.map(d=><Cell key={d.label} fill={d.color}/>)}
     </Pie>
     <Tooltip contentStyle={{background:"var(--color-surface)",border:"1px solid var(--color-edge)",borderRadius:8,fontSize:11}}/>
    </PieChart></ResponsiveContainer>
   </section>
  </div>}
  {selected&&<div className="chat-pipeline-overlay" onClick={()=>!saving&&setSelected(null)}><section role="dialog" aria-modal="true" aria-label="Detalhes do lead" className="chat-pipeline-detail" onClick={e=>e.stopPropagation()}><button autoFocus className="chat-pipeline-close" aria-label="Fechar detalhes" disabled={saving} onClick={()=>setSelected(null)}>×</button><h2>{selected.lead.nome||selected.lead.fone}</h2><p>{selected.lead.fone}</p><div className="pipeline-acoes">{selected.lead.hasConv!==false&&<Link className="pipeline-open-chat" to={`/atendimento?chatid=${encodeURIComponent(selected.lead.chatid)}`}>Abrir conversa no Atendimento →</Link>}<Link className="pipeline-open-chat pipeline-open-group" to={`/jornada?${new URLSearchParams({...(selected.lead.hasConv!==false?{chatid:selected.lead.chatid}:{}),...(selected.lead.crmId?{crm_id:selected.lead.crmId}:{})}).toString()}`}>🧭 Jornada do lead →</Link>{selected.lead.grupoChatid&&<Link className="pipeline-open-chat pipeline-open-group" to={`/atendimento?chatid=${encodeURIComponent(selected.lead.grupoChatid)}`}>👥 Abrir grupo da loja{selected.lead.grupoNome?` · ${selected.lead.grupoNome.replace(/^Provou Levou & /,"")}`:""} →</Link>}{closing?<form className="pipeline-sale-form" onSubmit={e=>{e.preventDefault();const cents=Math.round(Number(price.replace(",","."))*100);if(!plan||!Number.isFinite(cents)||cents<=0){setError("Selecione o plano e informe um valor válido.");return;}const _d=customDesc.trim().slice(0,60);const planoFinal=plan===CUSTOM_KEY?(_d?`${CUSTOM_PLAN} — ${_d}`:CUSTOM_PLAN):plan;void update("status",{status:"CONVERTIDO",plano:planoFinal,valor_centavos:cents})}}><h3>Plano fechado</h3>{error&&<p role="alert" className="chat-pipeline-error">{error}</p>}<label>Plano<select required disabled={saving} value={plan} onChange={e=>{setPlan(e.target.value);const p=plans.find(p=>p.nome===e.target.value);setPrice(p?p.preco.replace(/[^\d,]/g,"").replace(",","."):(e.target.value===CUSTOM_KEY?price:""))}}><option value="">Selecione o plano</option>{plans.map(p=><option key={p.nome} value={p.nome}>{p.nome} — {p.preco}/mês</option>)}<option value={CUSTOM_KEY}>Plano personalizado…</option></select></label>{plan===CUSTOM_KEY&&<label>Descrição do plano<input type="text" maxLength={60} disabled={saving} placeholder="Ex.: 1.000 provas · cabelos" value={customDesc} onChange={e=>setCustomDesc(e.target.value)}/></label>}<label>Mensalidade combinada (R$)<input required type="number" min="0.01" max="1000000" step="0.01" disabled={saving} value={price} onChange={e=>setPrice(e.target.value)}/></label><small>Você pode ajustar o valor em caso de desconto. Este registro não confirma pagamento.</small><button className="pipeline-open-chat" disabled={saving||!plans.length} type="submit">{saving?"Salvando…":"Salvar plano e converter"}</button><button type="button" disabled={saving} onClick={()=>setClosing(false)}>Cancelar</button></form>:<button className="pipeline-register-sale" onClick={()=>openSale(selected.lead,selected.removed)}><svg aria-hidden="true" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2v20m5-16H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg><span>{selected.lead.venda?`Editar plano fechado: ${selected.lead.venda.plano}`:"Registrar plano fechado"}</span></button>}</div>{!closing&&<LeadHistorico chatid={selected.lead.hasConv!==false?selected.lead.chatid:undefined} crmId={selected.lead.crmId}/>}{!closing&&<><label>Etapa comercial<select disabled={saving} value={selected.lead.status} onChange={e=>{void update("status",{status:e.target.value})}}>{!stages.slice(2,-1).some(s=>s.value===selected.lead.status)&&<option value={selected.lead.status}>{selected.lead.status||"Selecione"}</option>}{stages.slice(2,-1).map(s=><option key={s.value} value={s.value}>{s.label}</option>)}</select></label><label>Responsável<select disabled={saving} value={selected.lead.responsavel||""} onChange={e=>{void update("responsavel",{responsavel:e.target.value})}}><option value="">Sem responsável</option><option>Lucas</option><option>Dione</option></select></label>{selected.lead.origem!=="crm"&&<button disabled={saving} onClick={()=>{void update("ocultar",{oculto:!selected.removed})}}>{selected.removed?"Restaurar conversa":"Remover da fila"}</button>}<button className="chat-pipeline-excluir" disabled={saving} onClick={()=>{void excluir()}}>🗑 Excluir lead do CRM</button></>}<p className="chat-pipeline-note">As alterações são compartilhadas com o Atendimento.</p></section></div>}
 </div>
}
