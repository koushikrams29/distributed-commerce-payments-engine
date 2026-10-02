import { useState, type FormEvent } from "react";

import { login } from "../lib/api";
import type { TokenPair } from "../types";

interface Props {
  onSignedIn: (pair: TokenPair) => void;
}

export function LoginForm({ onSignedIn }: Props) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onSignedIn(await login(email.trim(), password));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-in failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login">
      <form className="login__card" onSubmit={handleSubmit} noValidate>
        <div className="brand brand--center">
          <span className="brand__mark" aria-hidden="true" />
          <span>Commerce Ops</span>
        </div>
        <h1 className="login__title">Sign in to the live dashboard</h1>
        <p className="login__subtitle">Administrator accounts only.</p>

        <label className="field">
          <span>Email</span>
          <input
            type="email"
            autoComplete="username"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            required
            autoFocus
          />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            required
          />
        </label>

        {error && (
          <p className="login__error" role="alert">
            {error}
          </p>
        )}

        <button className="button" type="submit" disabled={submitting || !email || !password}>
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}
