import { useCallback, useEffect, useRef, useState, type DependencyList } from "react";

import { ApiError } from "../lib/api";
import { useSessionContext } from "./session";

export type Loader<T> = (token: string, signal: AbortSignal) => Promise<T>;

export interface Resource<T> {
  data: T | undefined;
  /** Message of the last failed load; cleared by the next success. */
  error: string | null;
  /** HTTP status of the last failure, when the gateway answered. */
  errorStatus: number | null;
  /** First load for the current inputs, nothing to show yet. */
  loading: boolean;
  /** A reload with data already on screen. */
  refreshing: boolean;
  /** When `data` was fetched, epoch ms. */
  updatedAt: number | null;
  reload: () => void;
}

interface Options {
  /** Refetch on this interval while the tab is visible. */
  pollMs?: number;
}

type State<T> = Omit<Resource<T>, "reload">;

function initial<T>(): State<T> {
  return {
    data: undefined,
    error: null,
    errorStatus: null,
    loading: true,
    refreshing: false,
    updatedAt: null,
  };
}

/**
 * Loads data through the signed-in session (refreshing the token on a 401).
 * Data from previous inputs is dropped so a page never shows one entity's
 * data under another's heading; a failed reload keeps the last good data and
 * reports the error alongside it.
 */
export function useResource<T>(load: Loader<T>, deps: DependencyList, options: Options = {}): Resource<T> {
  const { api } = useSessionContext();
  const { withToken } = api;
  const [state, setState] = useState<State<T>>(initial);
  const loadRef = useRef(load);
  loadRef.current = load;
  const runRef = useRef<() => void>(() => undefined);

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | null = null;
    setState(initial());

    const run = () => {
      if (controller) return; // one request at a time; a poll during a slow load is skipped
      const current = new AbortController();
      controller = current;
      setState((previous) => ({ ...previous, refreshing: previous.data !== undefined }));
      withToken((token) => loadRef.current(token, current.signal))
        .then((data) => {
          if (disposed) return;
          setState({
            data,
            error: null,
            errorStatus: null,
            loading: false,
            refreshing: false,
            updatedAt: Date.now(),
          });
        })
        .catch((error: unknown) => {
          if (disposed || current.signal.aborted) return;
          setState((previous) => ({
            ...previous,
            error: error instanceof Error ? error.message : "Request failed",
            errorStatus: error instanceof ApiError ? error.status : null,
            loading: false,
            refreshing: false,
          }));
        })
        .finally(() => {
          if (controller === current) controller = null;
        });
    };
    runRef.current = run;
    run();

    const onVisible = () => {
      if (document.visibilityState === "visible" && options.pollMs) run();
    };
    document.addEventListener("visibilitychange", onVisible);
    const timer = options.pollMs
      ? setInterval(() => {
          if (document.visibilityState === "visible") run();
        }, options.pollMs)
      : undefined;

    return () => {
      disposed = true;
      controller?.abort();
      clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
    // `load` is read through a ref; callers list what it depends on in `deps`.
  }, [withToken, options.pollMs, ...deps]);

  const reload = useCallback(() => runRef.current(), []);
  return { ...state, reload };
}
