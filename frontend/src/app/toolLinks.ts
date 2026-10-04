import { useEffect, useState } from "react";

/**
 * Where the observability tools are, as the operator's browser reaches them.
 * Read at runtime from /config.json (written by nginx from the container's
 * environment) so one image works locally and behind an SSH tunnel. A tool
 * whose URL is empty has no links.
 */
export interface ToolLinks {
  jaegerUrl: string | null;
  grafanaUrl: string | null;
  rabbitmqUrl: string | null;
}

const NONE: ToolLinks = { jaegerUrl: null, grafanaUrl: null, rabbitmqUrl: null };

let loaded: ToolLinks | null = null;
let pending: Promise<ToolLinks> | null = null;

function clean(value: unknown): string | null {
  return typeof value === "string" && /^https?:\/\//.test(value) ? value.replace(/\/+$/, "") : null;
}

function loadToolLinks(): Promise<ToolLinks> {
  pending ??= fetch("/config.json", { cache: "no-cache" })
    .then((response): Promise<Record<string, unknown>> | Record<string, unknown> =>
      response.ok ? (response.json() as Promise<Record<string, unknown>>) : {},
    )
    .then((body) => ({
      jaegerUrl: clean(body.jaegerUrl),
      grafanaUrl: clean(body.grafanaUrl),
      rabbitmqUrl: clean(body.rabbitmqUrl),
    }))
    .catch(() => NONE)
    .then((links) => {
      loaded = links;
      return links;
    });
  return pending;
}

export function useToolLinks(): ToolLinks {
  const [links, setLinks] = useState<ToolLinks>(loaded ?? NONE);
  useEffect(() => {
    if (loaded) return;
    let active = true;
    void loadToolLinks().then((value) => {
      if (active) setLinks(value);
    });
    return () => {
      active = false;
    };
  }, []);
  return links;
}

export function traceUrl(links: ToolLinks, traceId: string): string | null {
  return links.jaegerUrl ? `${links.jaegerUrl}/trace/${traceId}` : null;
}

export function queueUrl(links: ToolLinks, queue: string): string | null {
  return links.rabbitmqUrl ? `${links.rabbitmqUrl}/#/queues/%2F/${encodeURIComponent(queue)}` : null;
}

export function serviceTracesUrl(links: ToolLinks, service: string): string | null {
  return links.jaegerUrl
    ? `${links.jaegerUrl}/search?service=${encodeURIComponent(service)}&lookback=1h`
    : null;
}
