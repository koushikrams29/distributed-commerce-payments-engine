import type { TokenPair } from "../types";

export interface Session {
  accessToken: string;
  refreshToken: string;
  userId: string;
  role: string;
  /** Login email when the token carries it; used only for display. */
  email: string | null;
  /** Access-token expiry, epoch milliseconds. */
  expiresAt: number;
}

interface AccessClaims {
  sub: string;
  role: string;
  exp: number;
  email?: string;
}

const STORAGE_KEY = "commerce.dashboard.session";

/**
 * Reads the claims without verifying the signature. Only used to drive the UI
 * (show the right screen, know when the token expires) — every request is
 * still verified by the gateway.
 */
export function readAccessClaims(token: string): AccessClaims | null {
  const segment = token.split(".")[1];
  if (!segment) return null;
  try {
    const base64 = segment.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
    const claims: unknown = JSON.parse(atob(padded));
    if (
      claims &&
      typeof claims === "object" &&
      typeof (claims as AccessClaims).sub === "string" &&
      typeof (claims as AccessClaims).role === "string" &&
      typeof (claims as AccessClaims).exp === "number"
    ) {
      const email = (claims as AccessClaims).email;
      return {
        sub: (claims as AccessClaims).sub,
        role: (claims as AccessClaims).role,
        exp: (claims as AccessClaims).exp,
        email: typeof email === "string" && email.trim() ? email.trim() : undefined,
      };
    }
  } catch {
    // Malformed base64 or JSON.
  }
  return null;
}

export function sessionFromTokens(
  pair: TokenPair,
  options?: { emailFallback?: string | null },
): Session | null {
  const claims = readAccessClaims(pair.access_token);
  if (!claims) return null;
  const fallback = options?.emailFallback?.trim() || null;
  return {
    accessToken: pair.access_token,
    refreshToken: pair.refresh_token,
    userId: claims.sub,
    role: claims.role,
    email: claims.email ?? fallback,
    expiresAt: claims.exp * 1000,
  };
}

export function isAdmin(session: Session): boolean {
  return session.role === "admin";
}

/** Label shown in the top bar — email when known, otherwise the role. */
export function sessionDisplayName(session: Session): string {
  if (session.email) return session.email;
  return session.role === "admin" ? "Administrator" : session.role;
}

// sessionStorage, not localStorage: the session ends with the tab, which keeps
// the long-lived refresh token from lingering on shared machines.
export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (
      !parsed ||
      typeof parsed !== "object" ||
      typeof (parsed as Session).accessToken !== "string" ||
      typeof (parsed as Session).refreshToken !== "string" ||
      typeof (parsed as Session).userId !== "string" ||
      typeof (parsed as Session).role !== "string" ||
      typeof (parsed as Session).expiresAt !== "number"
    ) {
      return null;
    }
    const email = (parsed as Session).email;
    return {
      ...(parsed as Session),
      email: typeof email === "string" && email.trim() ? email.trim() : null,
    };
  } catch {
    return null;
  }
}

export function saveSession(session: Session | null): void {
  if (session) {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  } else {
    sessionStorage.removeItem(STORAGE_KEY);
  }
}
