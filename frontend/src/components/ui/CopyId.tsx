import { useEffect, useState } from "react";

import { Link } from "../../lib/router";
import { shortId } from "../../lib/format";
import { Icon } from "./Icon";

interface Props {
  id: string;
  /** Link the short ID here; the copy button still copies the full ID. */
  to?: string;
  /** Show the whole ID instead of its first eight characters. */
  full?: boolean;
  label?: string;
}

/** An ID shown short, with the full value one click away. */
export function CopyId({ id, to, full = false, label = "ID" }: Props) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 1500);
    return () => clearTimeout(timer);
  }, [copied]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(id);
      setCopied(true);
    } catch {
      // Clipboard access denied (e.g. an insecure origin); the full ID is in the tooltip.
    }
  };

  const text = full ? id : shortId(id);
  return (
    <span className="copy-id">
      {to ? (
        <Link className="mono copy-id__text" to={to} title={id}>
          {text}
        </Link>
      ) : (
        <span className="mono copy-id__text" title={id}>
          {text}
        </span>
      )}
      <button
        type="button"
        className="icon-button icon-button--small"
        onClick={copy}
        aria-label={copied ? `${label} copied` : `Copy ${label} ${id}`}
        title={copied ? "Copied" : `Copy full ${label}`}
      >
        <Icon name={copied ? "check" : "copy"} size={13} />
      </button>
    </span>
  );
}
