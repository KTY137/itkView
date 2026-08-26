import { useEffect, useRef, useState } from "react";
import { getInstitutes, patchInstitute, postNotificationTest } from "./api";
import type { Institute } from "./api";
import { useAuth } from "./auth";
import { useComponentSyncJob, useEvidenceSyncJob } from "./componentSync";
import { roleName, t } from "./i18n";
import { CompactSyncStatus } from "./SyncProgress";
import AccountScreen from "./screens/AccountScreen";
import AdminSettingsScreen from "./screens/AdminSettingsScreen";
import type { AdminSettingsUpdate } from "./screens/AdminSettingsScreen";
import AssemblyWizardScreen from "./screens/AssemblyWizardScreen";
import BoardScreen from "./screens/BoardScreen";
import ComponentsScreen from "./screens/ComponentsScreen";
import DashboardScreen from "./screens/DashboardScreen";
import GlueBatchesScreen from "./screens/GlueBatchesScreen";
import LoginScreen from "./screens/LoginScreen";
import OpsHealthScreen from "./screens/OpsHealthScreen";
import SetupScreen from "./screens/SetupScreen";
import StagedScreen from "./screens/StagedScreen";
import RemindersScreen from "./screens/RemindersScreen";
import ShipmentsScreen from "./screens/ShipmentsScreen";
import StatisticsScreen from "./screens/StatisticsScreen";
import ToolsScreen from "./screens/ToolsScreen";
import TriageScreen from "./screens/TriageScreen";
import UsersScreen from "./screens/UsersScreen";

type Health = {
  status: string;
  app: string;
  version: string;
  pdb_instance: string;
  pdb_write_scope?: string;
};

const SCREENS = [
  { id: "board", label: t.nav.board, icon: "▦" },
  { id: "components", label: t.nav.components, icon: "▣" },
  { id: "triage", label: t.nav.triage, icon: "⇪" },
  { id: "staged", label: t.nav.staged, icon: "⇅" },
  { id: "dashboard", label: t.nav.dashboard, icon: "◔" },
  { id: "statistics", label: t.nav.statistics, icon: "📈" },
] as const;

// Rail order matches the mockup: Tools, then the Phase-4 logistics screens.
const SITE_SCREENS = [
  { id: "tools", label: t.nav.tools, icon: "⚒" },
  { id: "glue", label: t.nav.glueBatches, icon: "⬡" },
  { id: "shipments", label: t.nav.shipments, icon: "⛟" },
  { id: "reminders", label: t.nav.reminders, icon: "✉" },
] as const;

// Admin-only; kept out of SITE_SCREENS so the nav entry is gated on the role.
const USERS_NAV = { id: "users", label: t.nav.users, icon: "◈" } as const;
const OPS_HEALTH_NAV = { id: "opsHealth", label: t.nav.opsHealth, icon: "◉" } as const;
const SETTINGS_NAV = { id: "adminSettings", label: t.nav.settings, icon: "⚙" } as const;
const ACCOUNT_SCREEN = { id: "account", label: t.nav.account } as const;
const ASSEMBLY_SCREEN = { id: "assembly", label: t.nav.assembly } as const;

export type ScreenId =
  | (typeof SCREENS)[number]["id"]
  | (typeof SITE_SCREENS)[number]["id"]
  | (typeof USERS_NAV)["id"]
  | (typeof OPS_HEALTH_NAV)["id"]
  | (typeof SETTINGS_NAV)["id"]
  | (typeof ACCOUNT_SCREEN)["id"]
  | (typeof ASSEMBLY_SCREEN)["id"];

/** Cross-screen navigation intent (open a component, seed search, or pin a test form). */
export type NavIntent = {
  token: number;
  sn?: string;
  q?: string;
  testType?: string;
  returnTo?: ScreenId;
};

/** Auth gate: session probe → splash, no session → login, otherwise the shell.
 * Demo mode (backend unreachable) renders the shell too, so the app stays
 * usable offline instead of trapping the user on a dead login screen. */
export default function App() {
  const { status } = useAuth();
  if (status === "loading") {
    return (
      <div className="auth-splash">
        <div className="login-brand">
          itk<span>Flow</span>
        </div>
        <p className="muted">{t.auth.checkingSession}</p>
      </div>
    );
  }
  if (status === "setup") return <SetupScreen />;
  if (status === "unauthenticated") return <LoginScreen />;
  return <AppShell />;
}

/** Initials for the rail avatar, e.g. "Anna Abel" → "AA". */
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

function AppShell() {
  const { user, demo, logout, isAdmin } = useAuth();
  const componentSync = useComponentSyncJob(!demo);
  const evidenceSync = useEvidenceSyncJob(!demo, componentSync.job);
  const [screen, setScreen] = useState<ScreenId>("board");
  const [health, setHealth] = useState<Health | null>(null);
  const [healthError, setHealthError] = useState(false);
  const [institutes, setInstitutes] = useState<Institute[]>([]);
  const [adminInstituteCode, setAdminInstituteCode] = useState("");
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

  useEffect(() => {
    const ownCode = user?.institute_code ?? null;
    setAdminInstituteCode((current) => {
      if (ownCode !== null) {
        return institutes.some((institute) => institute.code === ownCode) ? ownCode : "";
      }
      return institutes.some((institute) => institute.code === current)
        ? current
        : (institutes[0]?.code ?? "");
    });
  }, [institutes, user?.institute_code]);

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

  /** Primary/site nav click. Selecting "Components" also sends an empty nav
   * intent so the screen drops any open component detail and shows the list —
   * clicking the nav item that you're already on still resets it. */
  function goToScreen(id: ScreenId) {
    if (id === "components") setNav((prev) => ({ token: prev.token + 1 }));
    setScreen(id);
  }

  function handleScan(e: React.FormEvent) {
    e.preventDefault();
    const value = scanText.trim();
    if (value === "") return;
    navigateTo({ q: value });
    setScanText("");
  }

  async function handleSaveAdminSettings(code: string, update: AdminSettingsUpdate) {
    const updated = await patchInstitute(code, update);
    setInstitutes((current) =>
      [...current.filter((institute) => institute.code !== updated.code), updated].sort(
        (left, right) => left.code.localeCompare(right.code),
      ),
    );
    return updated;
  }

  const activeLabel =
    [
      ...SCREENS,
      ...SITE_SCREENS,
      USERS_NAV,
      OPS_HEALTH_NAV,
      SETTINGS_NAV,
      ACCOUNT_SCREEN,
      ASSEMBLY_SCREEN,
    ].find(
      (item) => item.id === screen,
    )?.label ?? "";
  // A signed-in user's home institute wins for branding; fall back to the first
  // synced institute (e.g. in demo mode there is no user).
  const brandCode = user?.institute_code ?? institutes[0]?.code;
  const brandInstitute = institutes.find((i) => i.code === brandCode) ?? institutes[0];
  const adminInstitutes =
    user?.institute_code === null || user?.institute_code === undefined
      ? institutes
      : institutes.filter((institute) => institute.code === user.institute_code);
  // Institute branding is profile data (hard rule #4: never hardcode an
  // institute) — the logo comes from the selected institute's settings.
  const rawLogo = brandInstitute?.settings?.logo_url;
  const logoUrl = typeof rawLogo === "string" && rawLogo !== "" ? rawLogo : null;
  const syncJobs = [componentSync.job, evidenceSync.job].filter(
    (job) => job !== null,
  );
  const activeSyncJobs = syncJobs.filter(
    (job) => job.status === "queued" || job.status === "running",
  );
  const visibleSyncJob = [...(activeSyncJobs.length > 0 ? activeSyncJobs : syncJobs)].sort(
    (left, right) =>
      new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
  )[0] ?? null;

  return (
    <div className="frame">
      <aside className="rail">
        <div className="brand">
          itk<span>Flow</span>
          {brandCode && <span className="inst">{brandCode}</span>}
        </div>
        <div className="grp">{t.nav.groupProduction}</div>
        <nav aria-label="Main navigation">
          {SCREENS.map((s) => (
            <button
              key={s.id}
              type="button"
              className="nav-btn"
              aria-current={screen === s.id ? "page" : undefined}
              onClick={() => goToScreen(s.id)}
            >
              <span className="ic" aria-hidden="true">
                {s.icon}
              </span>{" "}
              {s.label}
            </button>
          ))}
        </nav>
        <div className="grp">{t.nav.groupSite}</div>
        {SITE_SCREENS.map((s) => (
          <button
            key={s.id}
            type="button"
            className="nav-btn"
            aria-current={screen === s.id ? "page" : undefined}
            onClick={() => goToScreen(s.id)}
          >
            <span className="ic" aria-hidden="true">
              {s.icon}
            </span>{" "}
            {s.label}
          </button>
        ))}
        {isAdmin && (
          <>
            <div className="grp">{t.nav.groupAdmin}</div>
            <button
              type="button"
              className="nav-btn"
              aria-current={screen === "users" ? "page" : undefined}
              onClick={() => goToScreen("users")}
            >
              <span className="ic" aria-hidden="true">
                {USERS_NAV.icon}
              </span>{" "}
              {USERS_NAV.label}
            </button>
            <button
              type="button"
              className="nav-btn"
              aria-current={screen === "opsHealth" ? "page" : undefined}
              onClick={() => goToScreen("opsHealth")}
            >
              <span className="ic" aria-hidden="true">
                {OPS_HEALTH_NAV.icon}
              </span>{" "}
              {OPS_HEALTH_NAV.label}
            </button>
            <button
              type="button"
              className="nav-btn"
              aria-current={screen === "adminSettings" ? "page" : undefined}
              onClick={() => goToScreen("adminSettings")}
            >
              <span className="ic" aria-hidden="true">
                {SETTINGS_NAV.icon}
              </span>{" "}
              {SETTINGS_NAV.label}
            </button>
          </>
        )}
        <div className="rail-bottom">
          {logoUrl !== null && (
            <div className="rail-logo">
              <img src={logoUrl} alt={brandCode ? `${brandCode} logo` : "Institute logo"} />
            </div>
          )}
          {user !== null ? (
            <div className="me" title={t.auth.signedInAs}>
              <button
                type="button"
                className="me-account"
                aria-current={screen === "account" ? "page" : undefined}
                aria-label={`${t.nav.account}: ${user.display_name}`}
                title={t.account.openSettings}
                onClick={() => goToScreen("account")}
              >
                <span className="ava">{initials(user.display_name)}</span>
                <span className="me-id">
                  <span className="me-name">{user.display_name}</span>
                  <span className="role">
                    {roleName(user.role)}
                    {user.institute_code ? ` · ${user.institute_code}` : ""}
                  </span>
                </span>
              </button>
              <button
                type="button"
                className="logout-btn"
                onClick={() => void logout()}
                title={t.auth.signOut}
                aria-label={t.auth.signOut}
              >
                ⏻
              </button>
            </div>
          ) : (
            <div className="me" title={demo ? t.auth.demoHint : undefined}>
              <span className="ava">D</span>
              <span className="me-id">
                <span className="me-name">{t.auth.demoUser}</span>
                <span className="role">{t.auth.demoRole}</span>
              </span>
            </div>
          )}
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
          {visibleSyncJob !== null && (
            <CompactSyncStatus
              job={visibleSyncJob}
              onOpen={() => goToScreen("components")}
            />
          )}
          <span className="sync">
            <span
              className={
                healthError
                  ? "dot off"
                  : health?.pdb_instance === "production"
                    ? "dot prod"
                    : "dot"
              }
            />
            {healthError
              ? t.nav.backendOffline
              : health
                ? health.pdb_instance === "production"
                  ? `${t.nav.pdb} production (${t.nav.dummyWritesOnly}) · API v${health.version}`
                  : `${t.nav.pdb} ${health.pdb_instance} · API v${health.version}`
                : t.common.loading}
          </span>
        </header>

        <div className="content">
          {screen === "board" ? (
            <BoardScreen
              onOpen={(sn) => navigateTo({ sn, returnTo: "board" })}
              onAssemble={() => setScreen("assembly")}
            />
          ) : screen === "assembly" ? (
            <AssemblyWizardScreen
              onBack={() => setScreen("board")}
              onStaged={() => setScreen("staged")}
            />
          ) : screen === "components" ? (
            <ComponentsScreen
              nav={nav}
              onNavigate={(target) => setScreen(target)}
              componentSync={componentSync}
              evidenceSync={evidenceSync}
            />
          ) : screen === "triage" ? (
            <TriageScreen
              onOpenComponent={(sn: string) => navigateTo({ sn, returnTo: "triage" })}
            />
          ) : screen === "staged" ? (
            <StagedScreen
              onOpenComponent={(sn: string) => navigateTo({ sn, returnTo: "staged" })}
            />
          ) : screen === "tools" ? (
            <ToolsScreen />
          ) : screen === "glue" ? (
            <GlueBatchesScreen />
          ) : screen === "shipments" ? (
            <ShipmentsScreen
              onOpenComponent={(sn: string) => navigateTo({ sn, returnTo: "shipments" })}
              onAddTest={(sn: string, testType: string) =>
                navigateTo({ sn, testType, returnTo: "shipments" })
              }
            />
          ) : screen === "reminders" ? (
            <RemindersScreen />
          ) : screen === "account" ? (
            <AccountScreen />
          ) : screen === "users" ? (
            <UsersScreen />
          ) : screen === "opsHealth" ? (
            <OpsHealthScreen
              institutes={adminInstitutes}
              selectedCode={adminInstituteCode}
              allowAllInstitutes={user?.institute_code == null}
              onSelectedCodeChange={setAdminInstituteCode}
              onNavigate={setScreen}
            />
          ) : screen === "adminSettings" ? (
            <AdminSettingsScreen
              institutes={adminInstitutes}
              selectedCode={adminInstituteCode}
              onSelectedCodeChange={setAdminInstituteCode}
              onSave={handleSaveAdminSettings}
              onTestChannel={(code, channel) => postNotificationTest(channel, code).then(() => {})}
              labels={t.adminSettings}
            />
          ) : screen === "statistics" ? (
            <StatisticsScreen />
          ) : (
            <DashboardScreen />
          )}
        </div>
      </div>
    </div>
  );
}
