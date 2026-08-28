import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../api";
import { useAuth } from "../auth";
import { t } from "../i18n";
import { product } from "../product";

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * First-run setup, shown only while no account exists (auth status `setup`):
 * create the initial admin from the UI so a fresh deployment never needs a
 * shell. On success the provider signs the new admin in and swaps to the app.
 */
export default function SetupScreen() {
  const { bootstrapAdmin } = useAuth();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [alreadyDone, setAlreadyDone] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError(t.auth.setupPasswordTooShort);
      return;
    }
    if (password !== confirm) {
      setError(t.auth.setupPasswordMismatch);
      return;
    }
    setSubmitting(true);
    try {
      await bootstrapAdmin({
        email: email.trim(),
        display_name: displayName.trim(),
        password,
      });
      // On success the provider swaps the tree to the app shell — nothing to do.
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        // Someone else completed setup in the meantime; reloading lands on the
        // regular login screen.
        setError(t.auth.setupAlreadyDone);
        setAlreadyDone(true);
      } else {
        setError(`${t.auth.setupFailed}: ${errorMessage(err)}`);
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="login-view">
      <form className="login-card" onSubmit={(e) => void handleSubmit(e)}>
        <div className="login-brand">
          {product.brandPrefix}<span>{product.brandAccent}</span>
        </div>
        <h1 className="login-title">{t.auth.setupTitle}</h1>
        <p className="login-sub">{t.auth.setupSubtitle}</p>

        <label className="login-field">
          <span>{t.auth.setupNameLabel}</span>
          <input
            type="text"
            autoComplete="name"
            autoFocus
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder={t.auth.setupNamePlaceholder}
            required
          />
        </label>
        <label className="login-field">
          <span>{t.auth.emailLabel}</span>
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder={t.auth.emailPlaceholder}
            required
          />
        </label>
        <label className="login-field">
          <span>{t.auth.passwordLabel}</span>
          <input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t.auth.setupPasswordPlaceholder}
            required
          />
        </label>
        <label className="login-field">
          <span>{t.auth.setupConfirmLabel}</span>
          <input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder={t.auth.setupPasswordPlaceholder}
            required
          />
        </label>

        {error !== null && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}

        <button className="btn primary login-submit" type="submit" disabled={submitting}>
          {submitting ? t.auth.setupCreating : t.auth.setupCreate}
        </button>

        {alreadyDone && (
          <button
            type="button"
            className="btn login-demo"
            onClick={() => window.location.reload()}
          >
            {t.auth.setupGoToSignIn}
          </button>
        )}
      </form>
    </div>
  );
}
