import { useEffect, useRef, useState } from "react";
import { getInstitutes } from "./api";
import type { Institute } from "./api";
import { t } from "./i18n";
import BoardScreen from "./screens/BoardScreen";
import ComponentsScreen from "./screens/ComponentsScreen";
import DashboardScreen from "./screens/DashboardScreen";
import OutboxScreen from "./screens/OutboxScreen";
import TriageScreen from "./screens/TriageScreen";

type Health = {
  status: string;
  app: string;
  version: string;
  pdb_instance: string;
};

const SCREENS = [
  { id: "board", label: t.nav.board, icon: "▦" },
  { id: "components", label: t.nav.components, icon: "▣" },
  { id: "triage", label: t.nav.triage, icon: "⇪" },
  { id: "outbox", label: t.nav.outbox, icon: "⇅" },
  { id: "dashboard", label: t.nav.dashboard, icon: "◔" },
] as const;

const SOON = [
  { label: t.nav.glueBatches, icon: "⬡" },
  { label: t.nav.shipments, icon: "⛟" },
  { label: t.nav.tools, icon: "⚒" },
  { label: t.nav.reminders, icon: "✉" },
] as const;

type ScreenId = (typeof SCREENS)[number]["id"];

/** Cross-screen navigation intent (open a component, or seed the search). */
export type NavIntent = { token: number; sn?: string; q?: string };

export default function App() {
  const [screen, setScreen] = useState<ScreenId>("board");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [nav, setNav] = useState<NavIntent>({ token: 0 });
  const [scanText, setScanText] = useState("");
  const scanRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let cancelled = false;
    const poll = () =>
      fetch("/health")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.statusText))))
        .then((body: Health) => {
          if (!cancelled) {
            setHealth(body);
            setHealthError(false);
          }
        })
        .catch(() => {
          if (!cancelled) setHealthError(true);
        });
    poll();
    const timer = setInterval(poll, 15_000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  useEffect(() => {
    getInstitutes()
      .then(setInstitutes)
      .catch(() => setInstitutes([]));
  }, []);

  // F2 focuses the scan field (scanner-first ergonomics, as in the mockup).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "F2") {
        e.preventDefault();
        scanRef.current?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function navigateTo(intent: Omit<NavIntent, "token">) {
    setNav((prev) => ({ token: prev.token + 1, ...intent }));
    setScreen("components");
  }

  function handleScan(e: React.FormEvent) {
    e.preventDefault();
    const value = scanText.trim();
    if (value === "") return;
    navigateTo({ q: value });
    setScanText("");
  }

  const activeLabel = SCREENS.find((s) => s.id === screen)?.label ?? "";
  const instituteCode = institutes[0]?.code;

  return (
    <div className="frame">
      <aside className="rail">
        <div className="brand">
          itk<span>Flow</span>
          {instituteCode && <span className="inst">{instituteCode}</span>}
        </div>
        <div className="grp">{t.nav.groupProduction}</div>
        <nav aria-label="Main navigation">
          {SCREENS.map((s) => (
            <button
              key={s.id}
              type="button"
              className="nav-btn"
              aria-current={screen === s.id ? "page" : undefined}
              onClick={() => setScreen(s.id)}
            >
              <span className="ic" aria-hidden="true">
                {s.icon}
              </span>{" "}
              {s.label}
            </button>
          ))}
        </nav>
        <div className="grp">{t.nav.groupSite}</div>
        {SOON.map((s) => (
          <button key={s.label} type="button" className="nav-btn dis" disabled>
            <span className="ic" aria-hidden="true">
              {s.icon}
            </span>{" "}
            {s.label} <span className="soon">P4</span>
          </button>
        ))}
        <div className="me">
          <span className="ava">it</span>
          <span>
            itkFlow
            <br />
            <span className="role">
              {instituteCode ? `${t.nav.operator} · ${instituteCode}` : t.nav.operator}
            </span>
          </span>
        </div>
      </aside>

      <div className="main">
        <header className="top">
          <span className="crumb">
            <b>itkFlow</b> · {activeLabel}
          </span>
          <form className="scan" role="search" onSubmit={handleScan}>
            <span aria-hidden="true">⌕</span>
            <input
              ref={scanRef}
              value={scanText}
              onChange={(e) => setScanText(e.target.value)}
              placeholder={t.nav.scanPlaceholder}
              aria-label={t.nav.scanPlaceholder}
            />
            <kbd>F2</kbd>
          </form>
          <span className="sync">
            <span className={healthError ? "dot off" : "dot"} />
            {healthError
              ? t.nav.backendOffline
              : health
                ? `${t.nav.pdb} ${health.pdb_instance} · API v${health.version}`
                : t.common.loading}
          </span>
        </header>

        <div className="content">
          {screen === "board" ? (
            <BoardScreen onOpen={(sn) => navigateTo({ sn })} />
          ) : screen === "components" ? (
            <ComponentsScreen nav={nav} />
          ) : screen === "triage" ? (
            <TriageScreen />
          ) : screen === "outbox" ? (
            <OutboxScreen />
          ) : (
            <DashboardScreen />
          )}
        </div>
      </div>
    </div>
  );
}
