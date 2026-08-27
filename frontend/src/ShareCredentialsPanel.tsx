import { useEffect, useState } from "react";
import type { FormEvent } from "react";

import {
  ApiError,
  deleteShareCredential,
  getShareCredentials,
  putShareCredential,
} from "./api";
import type { ShareCredentialOut } from "./api";
import { useAuth } from "./auth";
import { formatTimestamp, t } from "./i18n";

function shareError(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.detail) return error.detail;
    if (error.isNetwork) return `${fallback}: backend not reachable.`;
  }
  return `${fallback}: ${error instanceof Error ? error.message : String(error)}`;
}

function byProvider(left: ShareCredentialOut, right: ShareCredentialOut): number {
  return (
    left.provider_host.localeCompare(right.provider_host) ||
    left.token_hint.localeCompare(right.token_hint) ||
    left.id - right.id
  );
}

/** Account-owned passwords for public shares; secrets are write-only. */
export default function ShareCredentialsPanel() {
  const { showToast } = useAuth();
  const [credentials, setCredentials] = useState<ShareCredentialOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [url, setUrl] = useState("");
  const [password, setPassword] = useState("");
  const [saving, setSaving] = useState(false);
  const [removingId, setRemovingId] = useState<number | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setLoadError(null);
    getShareCredentials(controller.signal)
      .then((rows) => {
        setCredentials([...rows].sort(byProvider));
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setLoadError(shareError(error, t.account.sharesLoadFailed));
        setLoading(false);
      });
    return () => controller.abort();
  }, [reloadKey]);

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedUrl = url.trim();
    if (!trimmedUrl || !password) {
      setOperationError(t.account.shareFieldsRequired);
      return;
    }
    setSaving(true);
    setOperationError(null);
    try {
      const saved = await putShareCredential({ url: trimmedUrl, password });
      setCredentials((current) =>
        [...current.filter((row) => row.id !== saved.id), saved].sort(byProvider),
      );
      setUrl("");
      setPassword("");
      showToast(t.account.shareSavedToast);
    } catch (error) {
      setOperationError(shareError(error, t.account.shareSaveFailed));
    } finally {
      setSaving(false);
    }
  }

  async function handleRemove(id: number) {
    setRemovingId(id);
    setOperationError(null);
    try {
      await deleteShareCredential(id);
      setCredentials((current) => current.filter((row) => row.id !== id));
      showToast(t.account.shareRemovedToast);
    } catch (error) {
      setOperationError(shareError(error, t.account.shareRemoveFailed));
    } finally {
      setRemovingId(null);
    }
  }

  const busy = saving || removingId !== null;
  return (
    <section
      className="panel account-panel account-share-panel"
      aria-labelledby="share-credentials-title"
      aria-busy={busy}
    >
      <div className="account-panel-head">
        <div>
          <h2 className="section-title" id="share-credentials-title">
            {t.account.sharesTitle}
          </h2>
          <p className="account-panel-copy">{t.account.sharesDescription}</p>
        </div>
      </div>

      <p className="account-share-safety">{t.account.sharesPublicOnly}</p>

      {loading ? (
        <p className="state-note">{t.common.loading}</p>
      ) : loadError ? (
        <div className="error-banner" role="alert">
          <span>{loadError}</span>
          <button
            type="button"
            className="btn"
            onClick={() => setReloadKey((key) => key + 1)}
          >
            {t.common.retry}
          </button>
        </div>
      ) : (
        <div className="account-share-list-wrap">
          <h3>{t.account.savedSharesTitle}</h3>
          {credentials.length === 0 ? (
            <p className="state-note">{t.account.noSavedShares}</p>
          ) : (
            <ul className="account-share-list">
              {credentials.map((credential) => (
                <li key={credential.id}>
                  <div>
                    <strong>{credential.provider_host}</strong>
                    <span className="mono">{credential.token_hint}</span>
                    <small>
                      {t.account.shareUpdatedLabel}: {formatTimestamp(credential.updated_at)}
                    </small>
                  </div>
                  <button
                    type="button"
                    className="btn danger"
                    disabled={busy}
                    onClick={() => void handleRemove(credential.id)}
                  >
                    {removingId === credential.id
                      ? t.account.removingShare
                      : t.account.removeShare}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <form
        className="account-credential-form account-share-form"
        onSubmit={(event) => void handleSave(event)}
        autoComplete="off"
      >
        <label className="login-field">
          <span>{t.account.shareUrlLabel}</span>
          <input
            type="url"
            inputMode="url"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            placeholder={t.account.shareUrlPlaceholder}
            value={url}
            onChange={(event) => setUrl(event.target.value)}
            disabled={busy}
            aria-describedby="share-secret-note"
            required
          />
        </label>
        <label className="login-field">
          <span>{t.account.sharePasswordLabel}</span>
          <input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={busy}
            aria-describedby="share-secret-note"
            required
          />
        </label>
        <p className="account-secret-note" id="share-secret-note">
          {t.account.shareSecretNote}
        </p>
        <div className="account-actions">
          <button type="submit" className="btn primary" disabled={busy}>
            {saving ? t.account.savingShare : t.account.saveShare}
          </button>
        </div>
      </form>

      {operationError && (
        <div className="error-banner account-operation-error" role="alert">
          <span>{operationError}</span>
        </div>
      )}
    </section>
  );
}
