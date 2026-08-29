// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-2a7c97d7e0e8
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
 * Unauthenticated entry point: email + password, shown only when the backend is
 * reachable but no session exists. If the backend drops mid-attempt we surface a
 * "continue offline" escape hatch rather than trapping the user here.
 */
export default function LoginScreen() {
  const { login, enterDemo } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [offline, setOffline] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setOffline(false);
    setSubmitting(true);
    try {
      await login(email.trim(), password);
      // On success the provider swaps the tree to the app shell — nothing to do.
    } catch (err) {
      if (err instanceof ApiError && err.isNetwork) {
        setOffline(true);
        setError(t.auth.loginNetwork);
      } else if (err instanceof ApiError && err.status === 401) {
        setError(t.auth.invalidCredentials);
      } else {
        setError(`${t.auth.loginFailed}: ${errorMessage(err)}`);
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
        <h1 className="login-title">{t.auth.signInTitle}</h1>
        <p className="login-sub">{t.auth.signInSubtitle}</p>

        <label className="login-field">
          <span>{t.auth.emailLabel}</span>
          <input
            type="email"
            autoComplete="username"
            autoFocus
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
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder={t.auth.passwordPlaceholder}
            required
          />
        </label>

        {error !== null && (
          <div className="login-error" role="alert">
            {error}
          </div>
        )}

        <button className="btn primary login-submit" type="submit" disabled={submitting}>
          {submitting ? t.auth.signingIn : t.auth.signIn}
        </button>

        {offline && (
          <button type="button" className="btn login-demo" onClick={enterDemo}>
            {t.auth.continueDemo}
          </button>
        )}
      </form>
    </div>
  );
}
