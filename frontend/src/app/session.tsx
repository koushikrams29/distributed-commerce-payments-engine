import { createContext, useContext, type ReactNode } from "react";

import type { SessionApi } from "../dashboard/useSession";
import type { Session } from "../lib/auth";

interface SessionContextValue {
  session: Session;
  api: SessionApi;
}

const SessionContext = createContext<SessionContextValue | null>(null);

export function SessionProvider({
  session,
  api,
  children,
}: SessionContextValue & { children: ReactNode }) {
  return <SessionContext.Provider value={{ session, api }}>{children}</SessionContext.Provider>;
}

export function useSessionContext(): SessionContextValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSessionContext must be used inside <SessionProvider>");
  return value;
}
