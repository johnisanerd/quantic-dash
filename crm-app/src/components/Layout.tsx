import { NavLink, Outlet } from "react-router-dom";
import { useEffect, useState } from "react";
import { useGoalConfig } from "./SharedGoals";
import logoProvouLevouClaro from "../assets/provou-levou-logo-claro.png";
import logoProvouLevouEscuro from "../assets/provou-levou-logo-escuro.png";

const NAV_ITEMS = [
  {
    to: "/metas",
    label: "Metas",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="8" cy="8" r="6.5" />
        <circle cx="8" cy="8" r="3.5" />
        <circle cx="8" cy="8" r="0.75" fill="currentColor" stroke="none" />
      </svg>
    ),
  },

  {
    to: "/pipeline",
    label: "Pipeline",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
        <rect x="1" y="2" width="4" height="12" rx="1" />
        <rect x="6" y="5" width="4" height="9" rx="1" />
        <rect x="11" y="8" width="4" height="6" rx="1" />
      </svg>
    ),
  },
  {
    to: "/atendimento",
    label: "Atendimento",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 2.5h12v8H7l-3.5 3v-3H2z" />
        <path d="M5 6.5h6M5 8.5h4" />
      </svg>
    ),
  },
  {
    to: "/jornada",
    label: "Jornada do lead",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="3.5" cy="3.5" r="1.75" />
        <circle cx="12.5" cy="12.5" r="1.75" />
        <path d="M5.25 3.5H10a2.5 2.5 0 0 1 0 5H6a2.5 2.5 0 0 0 0 5h4.75" />
      </svg>
    ),
  },
  {
    to: "/assistente",
    label: "Assistente IA",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M8 1.5l1.4 3.1 3.1 1.4-3.1 1.4L8 10.5 6.6 7.4 3.5 6l3.1-1.4z" />
        <path d="M12.5 10.5l.6 1.4 1.4.6-1.4.6-.6 1.4-.6-1.4-1.4-.6 1.4-.6z" />
      </svg>
    ),
  },
  {
    to: "/mensagens-personalizadas",
    label: "Mensagens Personalizadas",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M2 2.5h12v8H7l-3.5 3v-3H2z" />
        <path d="m9 5 2 2-3.5 3.5H5.5V8.5z" />
      </svg>
    ),
  },
  {
    to: "/tarefas",
    label: "Tarefas",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2.5" y="2.5" width="11" height="11" rx="2" />
        <path d="m5.5 8 1.8 1.8L10.8 6.2" />
      </svg>
    ),
  },
  {
    to: "/comissoes",
    label: "Comissões",
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <circle cx="8" cy="8" r="6.5" />
        <path d="M10 5.8c-.4-.6-1.1-.9-2-.9-1.1 0-1.9.6-1.9 1.4 0 1.9 4 1 4 2.9 0 .8-.8 1.5-2.1 1.5-.9 0-1.7-.4-2.1-1M8 3.8v1.1M8 11.1v1.1" />
      </svg>
    ),
  },
  {
    to: "/trafego-pago",
    label: "Tráfego pago",
    icon: <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 20V10M10 20V4M16 20v-7M22 20H2" /></svg>,
  },

];

type Theme = "dark" | "light";

function getInitialTheme(): Theme {
  if (typeof window === "undefined") return "dark";
  const saved = localStorage.getItem("quantic-crm-theme") as Theme | null;
  if (saved === "light" || saved === "dark") return saved;
  return "dark";
}

export default function Layout() {
  const {canEdit:isLucas}=useGoalConfig();
  const [theme, setTheme] = useState<Theme>(getInitialTheme);
  const [navOpen, setNavOpen] = useState(false);
  const [navCollapsed, setNavCollapsed] = useState(false);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem("quantic-crm-theme", theme);
  }, [theme]);

  const [loggingOut,setLoggingOut]=useState(false);
  const [logoutError,setLogoutError]=useState("");
  async function logout(){setLoggingOut(true);setLogoutError("");try{const r=await fetch("/prospeccao/logout",{method:"POST",credentials:"same-origin"});if(!r.ok)throw new Error();window.location.replace("/prospeccao/login")}catch{setLogoutError("Não foi possível sair. Tente novamente.");setLoggingOut(false)}}

  const closeNav = () => setNavOpen(false);
  const logoProvouLevou = theme === "light" ? logoProvouLevouClaro : logoProvouLevouEscuro;
  // Compensa diferença de aspect ratio entre os dois PNGs (claro 5.73:1, escuro 3.78:1)
  // pra que o "provou levou." apareça do mesmo tamanho visual em ambos os temas.
  const logoSize =
    theme === "light"
      ? { sidebar: "h-8", topBar: "h-6" }
      : { sidebar: "h-11", topBar: "h-8" };

  return (
    <div className="crm-shell flex h-screen text-text" style={{ background: "transparent" }}>
      {/* Backdrop do drawer (apenas mobile, quando aberto) */}
      {navOpen && (
        <div
          aria-hidden="true"
          onClick={closeNav}
          className="fixed inset-0 z-40 bg-black/50 lg:hidden"
        />
      )}

      {/* Sidebar — padrão Quantic (glass + gradient border + left accent no active)
          Desktop: coluna fixa 250px. Mobile: drawer deslizante. */}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-[250px] flex flex-col transition-[width,transform] duration-200 lg:relative lg:z-auto lg:translate-x-0 ${navCollapsed ? "lg:w-[72px]" : "lg:w-[250px]"} ${
          navOpen ? "translate-x-0" : "-translate-x-full"
        }`}
        style={{
          background: "var(--color-sidebar)",
          backdropFilter: "blur(20px)",
          WebkitBackdropFilter: "blur(20px)",
          borderRight: "1px solid var(--color-sidebar-border)",
        }}
      >
        {/* Brand header */}
        <div
          className={`flex h-[72px] items-center gap-2 ${navCollapsed ? "lg:justify-center lg:px-2" : "px-5"}`}
          style={{ borderBottom: "1px solid var(--color-sidebar-border)" }}
        >
          <img
            src={logoProvouLevou}
            alt="Provou Levou"
            className={`flex-1 min-w-0 ${logoSize.sidebar} object-contain object-left ${navCollapsed ? "lg:hidden" : ""}`}
          />
          <button onClick={() => setNavCollapsed(v => !v)} aria-label={navCollapsed ? "Expandir menu" : "Recolher menu"} title={navCollapsed ? "Expandir menu" : "Recolher menu"} className="hidden h-8 w-8 shrink-0 items-center justify-center rounded-md border border-edge-subtle text-muted hover:bg-active-bg hover:text-violet-light lg:flex">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d={navCollapsed ? "m9 18 6-6-6-6" : "m15 18-6-6 6-6"}/></svg>
          </button>
          <button onClick={closeNav} aria-label="Fechar menu" className="ml-auto flex h-8 w-8 items-center justify-center rounded-md border border-edge-subtle text-muted lg:hidden"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m6 6 12 12M18 6 6 18"/></svg></button>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.filter(item=>item.to!=="/trafego-pago"||isLucas).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              title={navCollapsed ? item.label : undefined}
              end={item.to === "/"}
              onClick={closeNav}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-[9px] rounded-md text-[13px] font-medium transition-all duration-150 border-l-2 ${navCollapsed ? "lg:justify-center lg:px-2" : ""} ${
                  isActive
                    ? "border-l-[var(--color-violet)]"
                    : "border-l-transparent hover:border-l-[var(--color-violet-light)]"
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? {
                      background: "var(--color-active-bg)",
                      color: "var(--color-bright)",
                      boxShadow: "none",
                    }
                  : { color: "var(--color-muted)" }
              }
            >
              {({ isActive }) => (
                <>
                  <span
                    style={{
                      color: isActive ? "var(--color-violet)" : "currentColor",
                      filter: "none",
                      display: "inline-flex",
                    }}
                  >
                    {item.icon}
                  </span>
                  <span className={navCollapsed ? "lg:hidden" : ""}>{item.label}</span>
                </>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-edge-subtle p-3"><button type="button" onClick={()=>setTheme(theme==="dark"?"light":"dark")} title={theme==="dark"?"Mudar para o tema claro":"Mudar para o tema escuro"} aria-label={theme==="dark"?"Mudar para o tema claro":"Mudar para o tema escuro"} className="mb-1 flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm text-muted hover:bg-active-bg hover:text-violet-light">{theme==="dark"?<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/></svg>:<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>}<span className={navCollapsed?"lg:hidden":""}>{theme==="dark"?"Tema claro":"Tema escuro"}</span></button><button onClick={()=>{void logout()}} disabled={loggingOut} title="Sair" aria-label="Sair" className="flex w-full items-center gap-3 rounded-lg px-3 py-3 text-sm text-muted hover:bg-active-bg hover:text-violet-light"><svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4m7 14 5-5-5-5M21 12H9"/></svg><span className={navCollapsed?"lg:hidden":""}>{loggingOut?"Saindo…":"Sair"}</span></button>{logoutError&&<p role="alert" className="text-xs text-rose">{logoutError}</p>}</div>
      </aside>

      {/* Main */}
      <main className="flex-1 overflow-auto relative">
        {/* Top bar mobile (hambúrguer) — oculta no desktop */}
        <div
          className="lg:hidden sticky top-0 z-30 flex items-center gap-3 px-4 h-14"
          style={{
            background: "var(--color-sidebar)",
            backdropFilter: "blur(20px)",
            WebkitBackdropFilter: "blur(20px)",
            borderBottom: "1px solid var(--color-sidebar-border)",
          }}
        >
          <button
            onClick={() => setNavOpen(true)}
            aria-label="Abrir menu"
            className="flex items-center justify-center w-9 h-9 rounded-md flex-shrink-0"
            style={{ border: "1px solid var(--color-edge-subtle)", color: "var(--color-sub)" }}
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <path d="M3 6h18M3 12h18M3 18h18" />
            </svg>
          </button>
          <img src={logoProvouLevou} alt="Provou Levou" className={`${logoSize.topBar} object-contain`} />
        </div>
        <Outlet />
      </main>
    </div>
  );
}
