// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-3a8639333c34
import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError, getUsers, patchUser, postUser } from "../api";
import type { Role, UserOut, UserUpdateBody } from "../api";
import { useAuth } from "../auth";
import { formatTimestamp, roleName, t } from "../i18n";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

const ROLES: Role[] = ["viewer", "operator", "admin"];

/**
 * Admin-only user management (docs/06): list the accounts in your institute,
 * add people, change a role, deactivate (never delete — the audit trail stays
 * referenceable) and reset a password. Backed by the admin-gated /api/users
 * endpoints; the nav entry is only shown to admins, and this component guards
 * again defensively.
 */
export default function UsersScreen() {
  const { isAdmin, user, showToast } = useAuth();
  const [users, setUsers] = useState<UserOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  // Add-person form.
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [password, setPassword] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  // Per-row edit state.
  const [busyId, setBusyId] = useState<number | null>(null);
  const [resetId, setResetId] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    getUsers(ctrl.signal)
      .then((data) => {
        setUsers(data);
        setOffline(false);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (ctrl.signal.aborted) return;
        // No demo dataset for accounts — offline just means "needs a backend".
        if (err instanceof ApiError && err.isNetwork) setOffline(true);
        else setError(errorMessage(err));
        setLoading(false);
      });
    return () => ctrl.abort();
  }, [isAdmin, reloadKey]);

  if (!isAdmin) {
    return (
      <div className="screen">
        <div className="sc-head">
          <h1>{t.nav.users}</h1>
        </div>
        <p className="state-note">{t.auth.needAdmin}</p>
      </div>
    );
  }

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError(null);
    const cleanEmail = email.trim().toLowerCase();
    if (cleanEmail === "" || name.trim() === "") {
      setFormError(t.users.formIncomplete);
      return;
    }
    if (password.length < 8) {
      setFormError(t.users.passwordTooShort);
      return;
    }
    setCreating(true);
    try {
      const created = await postUser({
        email: cleanEmail,
        display_name: name.trim(),
        role,
        password,
      });
      showToast(t.users.created(created.email));
      setEmail("");
      setName("");
      setRole("operator");
      setPassword("");
      setReloadKey((k) => k + 1);
    } catch (err) {
      setFormError(`${t.users.createFailed}: ${errorMessage(err)}`);
    } finally {
      setCreating(false);
    }
  }

  async function updateUser(id: number, body: UserUpdateBody, done?: () => void) {
    setBusyId(id);
    try {
      await patchUser(id, body);
      setReloadKey((k) => k + 1);
      done?.();
    } catch (err) {
      showToast(`${t.users.updateFailed}: ${errorMessage(err)}`);
    } finally {
      setBusyId(null);
    }
  }

  async function handleResetPassword(id: number) {
    if (resetPassword.length < 8) {
      showToast(t.users.passwordTooShort);
      return;
    }
    await updateUser(id, { password: resetPassword }, () => {
      setResetId(null);
      setResetPassword("");
      showToast(t.users.passwordReset);
    });
  }

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.users}</h1>
        <span className="sub">
          {user?.institute_code
            ? t.users.subtitleInstitute(user.institute_code)
            : t.users.subtitle}
        </span>
      </div>

      {offline ? (
        <p className="state-note">{t.users.needsBackend}</p>
      ) : (
        <>
          <form className="panel compact-panel" onSubmit={(e) => void handleCreate(e)}>
            <h2 className="section-title">{t.users.addTitle}</h2>
            <div className="toolbar">
              <input
                className="search-input"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder={t.users.emailPlaceholder}
                aria-label={t.users.emailLabel}
                autoComplete="off"
              />
              <input
                className="search-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder={t.users.namePlaceholder}
                aria-label={t.users.nameLabel}
              />
              <select
                className="select-input"
                value={role}
                onChange={(e) => setRole(e.target.value as Role)}
                aria-label={t.users.roleLabel}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {roleName(r)}
                  </option>
                ))}
              </select>
              <input
                className="search-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t.users.passwordPlaceholder}
                aria-label={t.users.passwordLabel}
                autoComplete="new-password"
              />
              <button type="submit" className="btn primary" disabled={creating}>
                {creating ? t.common.loading : t.users.addBtn}
              </button>
            </div>
            {formError !== null && (
              <div className="error-banner" role="alert">
                <span>{formError}</span>
              </div>
            )}
          </form>

          {error !== null ? (
            <div className="error-banner" role="alert">
              <span>
                {t.users.loadError}: {error}
              </span>
            </div>
          ) : loading ? (
            <p className="state-note">{t.common.loading}</p>
          ) : users.length === 0 ? (
            <p className="state-note">{t.users.empty}</p>
          ) : (
            <div className="panel">
              <table className="data-table">
                <thead>
                  <tr>
                    <th scope="col">{t.users.colName}</th>
                    <th scope="col">{t.users.colEmail}</th>
                    <th scope="col">{t.users.colRole}</th>
                    <th scope="col">{t.users.colStatus}</th>
                    <th scope="col">{t.users.colCreated}</th>
                    <th scope="col">{t.users.colActions}</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map((u) => {
                    const self = u.id === user?.id;
                    const busy = busyId === u.id;
                    return (
                      <tr key={u.id}>
                        <td>
                          <div className="row-actions">
                            <span>{u.display_name}</span>
                            {self && <span className="chip neutral">{t.users.you}</span>}
                          </div>
                        </td>
                        <td className="mono">{u.email}</td>
                        <td>
                          <select
                            className="select-input"
                            value={u.role}
                            disabled={busy || self}
                            onChange={(e) => void updateUser(u.id, { role: e.target.value as Role })}
                            aria-label={t.users.roleLabel}
                          >
                            {ROLES.map((r) => (
                              <option key={r} value={r}>
                                {roleName(r)}
                              </option>
                            ))}
                          </select>
                        </td>
                        <td>
                          <span className={u.is_active ? "chip green" : "chip neutral"}>
                            {u.is_active ? t.users.active : t.users.inactive}
                          </span>
                        </td>
                        <td className="mono muted">{formatTimestamp(u.created_at)}</td>
                        <td>
                          <div className="row-actions">
                            {!self && (
                              <button
                                type="button"
                                className="btn"
                                disabled={busy}
                                onClick={() => void updateUser(u.id, { is_active: !u.is_active })}
                              >
                                {u.is_active ? t.users.deactivate : t.users.activate}
                              </button>
                            )}
                            {resetId === u.id ? (
                              <>
                                <input
                                  className="search-input"
                                  type="password"
                                  value={resetPassword}
                                  onChange={(e) => setResetPassword(e.target.value)}
                                  placeholder={t.users.newPasswordPlaceholder}
                                  aria-label={t.users.newPasswordPlaceholder}
                                  autoComplete="new-password"
                                />
                                <button
                                  type="button"
                                  className="btn primary"
                                  disabled={busy}
                                  onClick={() => void handleResetPassword(u.id)}
                                >
                                  {t.users.setPassword}
                                </button>
                                <button
                                  type="button"
                                  className="btn"
                                  onClick={() => {
                                    setResetId(null);
                                    setResetPassword("");
                                  }}
                                >
                                  {t.common.cancel}
                                </button>
                              </>
                            ) : (
                              <button
                                type="button"
                                className="btn"
                                onClick={() => {
                                  setResetId(u.id);
                                  setResetPassword("");
                                }}
                              >
                                {t.users.resetPassword}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}
