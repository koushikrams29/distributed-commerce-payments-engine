import { describe, expect, it } from "vitest";

import { isAdmin, readAccessClaims, sessionFromTokens } from "./auth";

function base64Url(value: object): string {
  return Buffer.from(JSON.stringify(value))
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

function fakeJwt(claims: object): string {
  return `${base64Url({ alg: "HS256", typ: "JWT" })}.${base64Url(claims)}.signature`;
}

describe("readAccessClaims", () => {
  it("reads the subject, role and expiry", () => {
    const token = fakeJwt({ sub: "user-1", role: "admin", exp: 1_900_000_000, typ: "access" });
    expect(readAccessClaims(token)).toMatchObject({
      sub: "user-1",
      role: "admin",
      exp: 1_900_000_000,
    });
  });

  it("handles base64url characters that plain atob would reject", () => {
    // This payload's base64 contains '+' and '/', which base64url turns into '-' and '_'.
    const token = fakeJwt({ sub: "??>>??>>", role: "admin", exp: 1 });
    expect(readAccessClaims(token)?.sub).toBe("??>>??>>");
  });

  it.each(["", "not-a-jwt", "a.%%%.c", `x.${base64Url({ sub: 1 })}.y`])(
    "rejects %s",
    (token) => {
      expect(readAccessClaims(token)).toBeNull();
    },
  );
});

describe("sessionFromTokens", () => {
  it("builds a session with the expiry in milliseconds", () => {
    const session = sessionFromTokens({
      access_token: fakeJwt({ sub: "user-1", role: "shopper", exp: 100 }),
      refresh_token: "refresh",
      token_type: "bearer",
    });

    expect(session).toMatchObject({ userId: "user-1", role: "shopper", expiresAt: 100_000 });
    expect(session && isAdmin(session)).toBe(false);
  });
});
