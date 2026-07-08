import { useEffect, useState } from "react";
import { t } from "./i18n";
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
  { id: "board", label: t.nav.board },
  { id: "components", label: t.nav.components },
  { id: "triage", label: t.nav.triage },
  { id: "outbox", label: t.nav.outbox },
  { id: "dashboard", label: t.nav.dashboard },
] as const;

type ScreenId = (typeof SCREENS)[number]["id"];

export default function App() {
  const [screen, setScreen] = useState<ScreenId>("board");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);

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

  return (
    <div className="frame">
      <aside className="rail">
        <div className="brand">
          itk<span>Flow</span>
        </div>
        <nav aria-label="Main navigation">
          {SCREENS.map((s) => (
            <button
              key={s.id}
              className="nav-btn"
              aria-current={screen === s.id ? "page" : undefined}
              onClick={() => setScreen(s.id)}
            >
              {s.label}
            </button>
          ))}
        </nav>
        <div className="rail-foot">
          {healthError && <span className="badge crit">backend offline</span>}
          {health && (
            <>
              <span className="badge good">API v{health.version}</span>
              <span className={health.pdb_instance === "test" ? "badge good" : "badge crit"}>
                PDB: {health.pdb_instance}
              </span>
            </>
          )}
        </div>
      </aside>
      <main className="content">
        <h1>{SCREENS.find((s) => s.id === screen)?.label}</h1>
        {screen === "components" ? (
          <ComponentsScreen />
        ) : screen === "outbox" ? (
          <OutboxScreen />
        ) : screen === "triage" ? (
          <TriageScreen />
        ) : screen === "dashboard" ? (
          <DashboardScreen />
        ) : (
          <p className="placeholder">
            {t.placeholder.shell} {screen === "board" ? "3" : screen === "triage" ? "2" : "1"}.{" "}
            {t.placeholder.backendHint} <code>/api</code>.
          </p>
        )}
      </main>
    </div>
  );
}
