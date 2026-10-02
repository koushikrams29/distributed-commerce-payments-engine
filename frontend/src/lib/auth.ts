import type { TokenPair } from "../types";

export interface Session {
  accessToken: string;
  refreshToken: string;
  userId: string;
  role: string;
  /** Access-token expiry, epoch milliseconds. */
  expiresAt: number;
}

interface AccessClaims {
  sub: string;
  role: string;
  exp: number;
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
      return claims as AccessClaims;
    }
  } catch {
    // Malformed base64 or JSON.
  }
  return null;
}

export function sessionFromTokens(pair: TokenPair): Session | null {
  const claims = readAccessClaims(pair.access_token);
  if (!claims) return null;
  return {
    accessToken: pair.access_token,
    refreshToken: pair.refresh_token,
    userId: claims.sub,
    role: claims.role,
    expiresAt: claims.exp * 1000,
  };
}

export function isAdmin(session: Session): boolean {
  return session.role === "admin";
}

// sessionStorage, not localStorage: the session ends with the tab, which keeps
// the long-lived refresh token from lingering on shared machines.
export function loadSession(): Session | null {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Session) : null;
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
