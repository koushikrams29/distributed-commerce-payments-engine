import { useEffect, useRef, useState } from "react";

import { reconnectDelay } from "../lib/backoff";
import type { DashboardEvent } from "../types";

// Must match services/gateway/app/api/routers/dashboard.py.
const CLOSE_UNAUTHENTICATED = 4401;
const CLOSE_FORBIDDEN = 4403;

export type ConnectionState = "connecting" | "live" | "reconnecting" | "forbidden";

interface Options {
  accessToken: string;
  onEvent: (event: DashboardEvent) => void;
  /** Fired on every (re)connect: events sent while disconnected are gone, so resync. */
  onReady: () => void;
  /** The gateway rejected or expired the token; the caller should refresh it. */
  onUnauthorized: () => void;
}

function socketUrl(): string {
  const configured = import.meta.env.VITE_WS_URL;
  if (configured) return configured;
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/dashboard`;
}

interface RawMessage {
  type?: unknown;
  data?: unknown;
  received_at?: unknown;
}

export function useDashboardSocket({
  accessToken,
  onEvent,
  onReady,
  onUnauthorized,
}: Options): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  // Callbacks change identity on every render; reading them through a ref keeps
  // the socket from being torn down and reopened each time.
  const handlers = useRef({ onEvent, onReady, onUnauthorized });
  handlers.current = { onEvent, onReady, onUnauthorized };

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let disposed = false;

    const connect = () => {
      setState(attempt === 0 ? "connecting" : "reconnecting");
      socket = new WebSocket(socketUrl());

      socket.onopen = () => {
        // The token goes in the first frame, not the URL, so it never lands in
        // proxy or access logs.
        socket?.send(JSON.stringify({ type: "auth", token: accessToken }));
      };

      socket.onmessage = (message: MessageEvent<string>) => {
        let parsed: RawMessage;
        try {
          parsed = JSON.parse(message.data) as RawMessage;
        } catch {
          return;
        }
        if (parsed.type === "ready") {
          attempt = 0;
          setState("live");
          handlers.current.onReady();
          return;
        }
        if (typeof parsed.type !== "string") return;
        handlers.current.onEvent({
          type: parsed.type,
          data:
            parsed.data && typeof parsed.data === "object"
              ? (parsed.data as Record<string, unknown>)
              : {},
          receivedAt:
            typeof parsed.received_at === "string"
              ? parsed.received_at
              : new Date().toISOString(),
        });
      };

      socket.onclose = (close: CloseEvent) => {
        socket = null;
        if (disposed) return;
        if (close.code === CLOSE_UNAUTHENTICATED) {
          setState("reconnecting");
          handlers.current.onUnauthorized();
          return;
        }
        if (close.code === CLOSE_FORBIDDEN) {
          setState("forbidden");
          return;
        }
        // Network drop, gateway restart, or 1013 (we fell too far behind).
        setState("reconnecting");
        retryTimer = setTimeout(connect, reconnectDelay(attempt));
        attempt += 1;
      };
    };

    connect();

    return () => {
      disposed = true;
      clearTimeout(retryTimer);
      socket?.close(1000, "dashboard closed");
    };
  }, [accessToken]);

  return state;
}
