import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError,
  deletePdbConnection,
  getPdbConnection,
  putPdbConnection,
  testPdbConnection,
} from "../api";
import type { PdbConnectionOut, PdbConnectionState } from "../api";
import { useAuth } from "../auth";
import { formatTimestamp, roleName, t } from "../i18n";
import { product } from "../product";
import {
  readStagedPreviewPreference,
  writeStagedPreviewPreference,
} from "../stagedPreview";
import type { StagedPreviewMode } from "../stagedPreview";
import ShareCredentialsPanel from "../ShareCredentialsPanel";

type BusyAction = "connect" | "test" | "disconnect" | null;

const STATE_CLASS: Record<PdbConnectionState, string> = {
  not_configured: "neutral",
  verified: "green",
  invalid: "red",
  unreachable: "serious",
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function connectionError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.status === 422) return t.account.invalidCredentials;
    if (error.status === 500) return t.account.pdbClientUnavailable;
    // A 503 carries an honest server-side reason (e.g. "no PDB configured on
    // this deployment") — prefer it over the generic network hint.
    if (error.status === 503) return error.detail ?? t.account.pdbUnavailable;
    if (error.isNetwork) return t.account.pdbUnavailable;
    if (error.status === 409) return error.detail ?? t.account.notConfigured;
  }
  return `${fallback}: ${errorMessage(error)}`;
}

function inferredFailureState(error: unknown): PdbConnectionState | null {
  if (!(error instanceof ApiError)) return null;
  if (error.status === 422) return "invalid";
  if (error.status === 503 || error.isNetwork) return "unreachable";
  if (error.status === 409) return "not_configured";
  return null;
}

function emptyConnection(instance: string): PdbConnectionOut {
  return {
    configured: false,
    state: "not_configured",
    instance,
    identity: null,
    institutions: [],
    last_checked_at: null,
    verified_at: null,
  };
}

/**
 * Self-service account settings. PDB access codes only ever live in the two
 * controlled password fields while the user is entering them; saved values
 * are represented by non-secret status metadata and are never read back.
 */
export default function AccountScreen() {
  const { user, demo, showToast } = useAuth();
  const [connection, setConnection] = useState<PdbConnectionOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [accessCode1, setAccessCode1] = useState("");
  const [accessCode2, setAccessCode2] = useState("");
  const [busy, setBusy] = useState<BusyAction>(null);
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [stagedPreviewMode, setStagedPreviewMode] = useState<StagedPreviewMode>(() =>
    readStagedPreviewPreference(),
  );

  function changeStagedPreviewMode(mode: StagedPreviewMode) {
    setStagedPreviewMode(mode);
    writeStagedPreviewPreference(mode);
  }

  useEffect(() => {
    if (demo || user === null) return;
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    getPdbConnection(controller.signal)
      .then((result) => {
        setConnection(result);
        setEditing(false);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(`${t.account.loadFailed}: ${errorMessage(error)}`);
        setLoading(false);
      });
    return () => controller.abort();
  }, [demo, reloadKey, user]);

  if (demo || user === null) {
    return (
      <div className="screen">
        <div className="sc-head">
          <h1>{t.nav.account}</h1>
        </div>
        <p className="state-note">{t.account.requiresSignIn}</p>
        {product.workflowWrites && (
          <StagedPreviewPreferences
            mode={stagedPreviewMode}
            onChange={changeStagedPreviewMode}
          />
        )}
      </div>
    );
  }

  const showCredentialForm = connection?.configured === false || editing;
  const isBusy = busy !== null;

  function clearCredentialFields() {
    setAccessCode1("");
    setAccessCode2("");
  }

  function applyFailureState(error: unknown) {
    const state = inferredFailureState(error);
    if (state === null) return;
    setConnection((current) => {
      if (current === null) return current;
      if (state === "not_configured") return emptyConnection(current.instance);
      return {
        ...current,
        state,
        last_checked_at: new Date().toISOString(),
      };
    });
  }

  async function handleConnect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const code1 = accessCode1.trim();
    const code2 = accessCode2.trim();
    if (code1 === "" || code2 === "") {
      setOperationError(t.account.bothCodesRequired);
      return;
    }

    setBusy("connect");
    setOperationError(null);
    setConfirmDisconnect(false);
    try {
      const result = await putPdbConnection({
        access_code1: code1,
        access_code2: code2,
      });
      setConnection(result);
      setEditing(false);
      clearCredentialFields();
      showToast(
        result.state === "verified" ? t.account.connectedToast : t.account.savedToast,
      );
    } catch (error) {
      // PUT verifies before replacing. A failed pair must not visually
      // invalidate or hide the still-active saved connection.
      setOperationError(connectionError(error, t.account.connectFailed));
    } finally {
      setBusy(null);
    }
  }

  async function handleTest() {
    setBusy("test");
    setOperationError(null);
    setConfirmDisconnect(false);
    try {
      const result = await testPdbConnection();
      setConnection(result);
      showToast(t.account.testPassedToast);
    } catch (error) {
      applyFailureState(error);
      setOperationError(connectionError(error, t.account.testFailed));
    } finally {
      setBusy(null);
    }
  }

  async function handleDisconnect() {
    setBusy("disconnect");
    setOperationError(null);
    try {
      await deletePdbConnection();
      setConnection(emptyConnection(connection?.instance ?? "production"));
      setEditing(false);
      setConfirmDisconnect(false);
      clearCredentialFields();
      showToast(t.account.disconnectedToast);
    } catch (error) {
      setOperationError(connectionError(error, t.account.disconnectFailed));
    } finally {
      setBusy(null);
    }
  }

  const connectionHint =
    connection === null ? null : connection.state === "verified" ? (
      t.account.verifiedHint
    ) : connection.state === "invalid" ? (
      t.account.invalidHint
    ) : connection.state === "unreachable" ? (
      t.account.unreachableHint
    ) : (
      t.account.notConfiguredHint
    );

  return (
    <div className="screen">
      <div className="sc-head">
        <h1>{t.nav.account}</h1>
        <span className="sub">{t.account.subtitle}</span>
      </div>

      <div className="account-layout">
        <section className="panel account-panel" aria-labelledby="account-identity-title">
          <h2 className="section-title" id="account-identity-title">
            {t.account.identityTitle}
          </h2>
          <dl className="account-kv">
            <dt>{t.account.nameLabel}</dt>
            <dd>{user.display_name}</dd>
            <dt>{t.account.emailLabel}</dt>
            <dd className="mono">{user.email}</dd>
            <dt>{t.account.roleLabel}</dt>
            <dd>{roleName(user.role)}</dd>
            <dt>{t.account.instituteLabel}</dt>
            <dd className="mono">{user.institute_code ?? t.common.none}</dd>
          </dl>
        </section>

        <section
          className="panel account-panel account-connection-panel"
          aria-labelledby="pdb-connection-title"
          aria-busy={isBusy}
        >
          <div className="account-panel-head">
            <div>
              <h2 className="section-title" id="pdb-connection-title">
                {t.account.pdbTitle}
              </h2>
              <p className="account-panel-copy">{t.account.pdbDescription}</p>
            </div>
            {connection !== null && (
              <span
                className={`chip connection-chip ${STATE_CLASS[connection.state]}`}
                role="status"
                aria-live="polite"
              >
                <span className="connection-dot" aria-hidden="true" />
                {t.account.states[connection.state]}
              </span>
            )}
          </div>

          {loading ? (
            <p className="state-note">{t.common.loading}</p>
          ) : loadError !== null ? (
            <div className="error-banner" role="alert">
              <span>{loadError}</span>
              <button type="button" className="btn" onClick={() => setReloadKey((key) => key + 1)}>
                {t.common.retry}
              </button>
            </div>
          ) : connection !== null ? (
            <>
              <p className="account-connection-hint">{connectionHint}</p>

              {connection.configured && (
                <dl className="account-connection-meta">
                  <div>
                    <dt>{t.account.instanceLabel}</dt>
                    <dd className="mono">{connection.instance}</dd>
                  </div>
                  <div>
                    <dt>{t.account.identityLabel}</dt>
                    <dd className="mono">{connection.identity ?? t.common.none}</dd>
                  </div>
                  <div>
                    <dt>{t.account.institutionsLabel}</dt>
                    <dd>
                      {connection.institutions.length > 0 ? (
                        <span className="account-institutions">
                          {connection.institutions.map((institution) => (
                            <span className="chip neutral" key={institution}>
                              {institution}
                            </span>
                          ))}
                        </span>
                      ) : (
                        t.common.none
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>{t.account.lastCheckedLabel}</dt>
                    <dd>
                      {connection.last_checked_at
                        ? formatTimestamp(connection.last_checked_at)
                        : t.common.none}
                    </dd>
                  </div>
                  <div>
                    <dt>{t.account.lastVerifiedLabel}</dt>
                    <dd>
                      {connection.verified_at
                        ? formatTimestamp(connection.verified_at)
                        : t.common.none}
                    </dd>
                  </div>
                </dl>
              )}

              {showCredentialForm && (
                <form
                  className="account-credential-form"
                  onSubmit={(event) => void handleConnect(event)}
                  autoComplete="off"
                >
                  <div className="account-secret-grid">
                    <label className="login-field">
                      <span>{t.account.accessCode1Label}</span>
                      <input
                        type="password"
                        autoComplete="new-password"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                        aria-describedby="pdb-secret-note"
                        value={accessCode1}
                        onChange={(event) => setAccessCode1(event.target.value)}
                        disabled={isBusy}
                        autoFocus
                        required
                      />
                    </label>
                    <label className="login-field">
                      <span>{t.account.accessCode2Label}</span>
                      <input
                        type="password"
                        autoComplete="new-password"
                        autoCapitalize="none"
                        autoCorrect="off"
                        spellCheck={false}
                        aria-describedby="pdb-secret-note"
                        value={accessCode2}
                        onChange={(event) => setAccessCode2(event.target.value)}
                        disabled={isBusy}
                        required
                      />
                    </label>
                  </div>
                  <p className="account-secret-note" id="pdb-secret-note">
                    {t.account.secretNote}
                  </p>
                  <div className="account-actions">
                    {editing && connection.configured && (
                      <button
                        type="button"
                        className="btn"
                        disabled={isBusy}
                        onClick={() => {
                          setEditing(false);
                          setOperationError(null);
                          clearCredentialFields();
                        }}
                      >
                        {t.common.cancel}
                      </button>
                    )}
                    <button type="submit" className="btn primary" disabled={isBusy}>
                      {busy === "connect" ? t.account.connecting : t.account.connectAndTest}
                    </button>
                  </div>
                </form>
              )}

              {!showCredentialForm && connection.configured && (
                <div className="account-actions">
                  <button
                    type="button"
                    className="btn"
                    disabled={isBusy}
                    onClick={() => void handleTest()}
                  >
                    {busy === "test" ? t.account.testing : t.account.testConnection}
                  </button>
                  <button
                    type="button"
                    className="btn"
                    disabled={isBusy}
                    onClick={() => {
                      clearCredentialFields();
                      setOperationError(null);
                      setConfirmDisconnect(false);
                      setEditing(true);
                    }}
                  >
                    {t.account.replaceCodes}
                  </button>
                  <button
                    type="button"
                    className="btn danger"
                    disabled={isBusy}
                    onClick={() => setConfirmDisconnect(true)}
                  >
                    {t.account.disconnect}
                  </button>
                </div>
              )}

              {confirmDisconnect && connection.configured && (
                <div
                  className="account-disconnect-confirm"
                  role="group"
                  aria-labelledby="disconnect-confirm-title"
                >
                  <div>
                    <strong id="disconnect-confirm-title">{t.account.disconnectQuestion}</strong>
                    <p>{t.account.disconnectHint}</p>
                  </div>
                  <div className="account-actions">
                    <button
                      type="button"
                      className="btn"
                      disabled={isBusy}
                      onClick={() => setConfirmDisconnect(false)}
                    >
                      {t.common.cancel}
                    </button>
                    <button
                      type="button"
                      className="btn danger"
                      disabled={isBusy}
                      onClick={() => void handleDisconnect()}
                    >
                      {busy === "disconnect"
                        ? t.account.disconnecting
                        : t.account.confirmDisconnect}
                    </button>
                  </div>
                </div>
              )}

              {operationError !== null && (
                <div className="error-banner account-operation-error" role="alert">
                  <span>{operationError}</span>
                </div>
              )}
            </>
          ) : null}
        </section>
        <ShareCredentialsPanel />
        {product.workflowWrites && (
          <StagedPreviewPreferences
            mode={stagedPreviewMode}
            onChange={changeStagedPreviewMode}
          />
        )}
      </div>
    </div>
  );
}

function StagedPreviewPreferences({
  mode,
  onChange,
}: {
  mode: StagedPreviewMode;
  onChange: (mode: StagedPreviewMode) => void;
}) {
  const options: Array<{
    mode: StagedPreviewMode;
    label: string;
    hint: string;
  }> = [
    { mode: "tabs", label: t.account.previewTabs, hint: t.account.previewTabsHint },
    { mode: "inline", label: t.account.previewInline, hint: t.account.previewInlineHint },
    { mode: "off", label: t.account.previewOff, hint: t.account.previewOffHint },
  ];

  return (
    <section
      className="panel account-panel account-preferences"
      aria-labelledby="account-preferences-title"
    >
      <h2 className="section-title" id="account-preferences-title">
        {t.account.preferencesTitle}
      </h2>
      <p className="account-panel-copy">{t.account.previewDescription}</p>
      <fieldset className="preference-options">
        <legend>{t.account.previewTitle}</legend>
        {options.map((option) => (
          <label className="preference-option" key={option.mode}>
            <input
              type="radio"
              name="staged-preview-mode"
              value={option.mode}
              checked={mode === option.mode}
              onChange={() => onChange(option.mode)}
            />
            <span>
              <strong>{option.label}</strong>
              <small>{option.hint}</small>
            </span>
          </label>
        ))}
      </fieldset>
    </section>
  );
}
