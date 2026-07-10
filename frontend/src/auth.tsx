import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import type { ReactNode } from "react";
import {
  ApiError,
  getMe,
  postLogin,
  postLogout,
  setCsrfToken,
  setForbiddenHandler,
  setUnauthorizedHandler,
} from "./api";
import type { MeOut, Role } from "./api";
import { t } from "./i18n";

/**
 * Session state machine:
 *  - `loading`         — the initial `/api/auth/me` probe is in flight.
 *  - `authenticated`   — a real user is signed in (live backend).
 *  - `unauthenticated` — backend reachable, no session → show the login screen.
 *  - `demo`            — backend unreachable → stay usable on built-in demo data
 *                        instead of trapping the user on a dead login screen.
 */
export type AuthStatus = "loading" | "authenticated" | "unauthenticated" | "demo";

type AuthContextValue = {
  status: AuthStatus;
  user: MeOut | null;
  csrfToken: string | null;
  role: Role | null;
  /** operator or admin (writes allowed). Demo mode keeps the app explorable. */
  canWrite: boolean;
  /** admin (institute / user management). Demo mode keeps the app explorable. */
  isAdmin: boolean;
  demo: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  /** Escape hatch from a login screen when the backend is unreachable. */
  enterDemo: () => void;
  showToast: (message: string) => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (ctx === null) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<MeOut | null>(null);
  const [csrf, setCsrf] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | null>(null);

  // Mirror `status` into a ref so the API-layer callbacks (registered once) can
  // read the current value without being torn down and re-registered.
  const statusRef = useRef<AuthStatus>(status);
  useEffect(() => {
    statusRef.current = status;
  }, [status]);

  const showToast = useCallback((message: string) => {
    setToast(message);
    if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 4000);
  }, []);

  const applyUser = useCallback((me: MeOut) => {
    setUser(me);
    setCsrf(me.csrf_token);
    setCsrfToken(me.csrf_token);
    setStatus("authenticated");
  }, []);

  const clearSession = useCallback((next: AuthStatus) => {
    setUser(null);
    setCsrf(null);
    setCsrfToken(null);
    setStatus(next);
  }, []);

  // Initial session probe. A network error means "backend down" → demo mode;
  // anything else (typically 401) means "not signed in" → login screen.
  useEffect(() => {
    const ctrl = new AbortController();
    getMe(ctrl.signal)
      .then((me) => applyUser(me))
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        if (err instanceof ApiError && err.isNetwork) clearSession("demo");
        else clearSession("unauthenticated");
      });
    return () => ctrl.abort();
  }, [applyUser, clearSession]);

  // Cross-cutting auth signals dispatched by the fetch layer.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      // Only act on a genuine session drop; ignore stray 401s while already on
      // the login screen or exploring offline.
      if (statusRef.current === "authenticated") {
        clearSession("unauthenticated");
        showToast(t.auth.sessionExpired);
      }
    });
    setForbiddenHandler(() => showToast(t.auth.forbidden));
    return () => {
      setUnauthorizedHandler(null);
      setForbiddenHandler(null);
    };
  }, [clearSession, showToast]);

  useEffect(
    () => () => {
      if (toastTimer.current !== null) window.clearTimeout(toastTimer.current);
    },
    [],
  );

  const login = useCallback(
    async (email: string, password: string) => {
      const me = await postLogin({ email, password });
      applyUser(me);
    },
    [applyUser],
  );

  const logout = useCallback(async () => {
    try {
      await postLogout();
    } catch {
      // Even if the network call fails, drop the local session — a stale local
      // session is worse than an unconfirmed server logout.
    }
    clearSession("unauthenticated");
  }, [clearSession]);

  const enterDemo = useCallback(() => clearSession("demo"), [clearSession]);

  const value = useMemo<AuthContextValue>(() => {
    const demo = status === "demo";
    const role = user?.role ?? null;
    return {
      status,
      user,
      csrfToken: csrf,
      role,
      // Demo mode grants full access so the offline experience is unchanged from
      // before auth existed; live access follows the signed-in role.
      canWrite: demo || role === "operator" || role === "admin",
      isAdmin: demo || role === "admin",
      demo,
      login,
      logout,
      enterDemo,
      showToast,
    };
  }, [status, user, csrf, login, logout, enterDemo, showToast]);

  return (
    <AuthContext.Provider value={value}>
      {children}
      {toast !== null && (
        <div className="toast show" role="status" aria-live="polite">
          {toast}
        </div>
      )}
    </AuthContext.Provider>
  );
}
