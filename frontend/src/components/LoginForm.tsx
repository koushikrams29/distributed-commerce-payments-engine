import { useState, type FormEvent } from "react";

import { login } from "../lib/api";
import type { TokenPair } from "../types";

interface Props {
  onSignedIn: (pair: TokenPair, email: string) => void;
}

const CAPABILITIES = [
  {
    title: "System health",
    detail: "Service uptime, queue depth, and outbox lag in one place.",
  },
  {
    title: "Order sagas",
    detail: "Follow each order from reservation through charge to fulfilment.",
  },
  {
    title: "Failure recovery",
    detail: "Inspect dead letters and replay them after you fix the cause.",
  },
] as const;

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
      const trimmed = email.trim();
      onSignedIn(await login(trimmed, password), trimmed);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Sign-in failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="login">
      <div className="login__shell">
        <aside className="login__aside" aria-label="About this console">
          <div className="brand">
            <span className="brand__mark" aria-hidden="true" />
            <span>Commerce Ops</span>
          </div>
          <h1 className="login__aside-title">Operate the commerce saga end to end</h1>
          <p className="login__aside-copy">
            Watch live events, inspect payments and stock, and act on failures
            across the Distributed Commerce &amp; Payments Engine.
          </p>
          <ul className="login__capabilities">
            {CAPABILITIES.map((item) => (
              <li key={item.title}>
                <span className="login__capability-title">{item.title}</span>
                <span className="login__capability-detail">{item.detail}</span>
              </li>
            ))}
          </ul>
          <p className="login__aside-foot">Administrator access only</p>
        </aside>

        <form className="login__card" onSubmit={handleSubmit}>
          <div className="brand brand--center login__card-brand">
            <span className="brand__mark" aria-hidden="true" />
            <span>Commerce Ops</span>
          </div>
          <h2 className="login__title">Sign in</h2>
          <p className="login__subtitle">Use your admin account to open the console.</p>

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
      </div>
    </main>
  );
}
