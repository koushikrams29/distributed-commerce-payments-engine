import type { ReactNode } from "react";

import { Icon } from "./Icon";

/** A link to an external tool; renders nothing when that tool isn't configured. */
export function ToolLink({
  href,
  children,
  title,
  className = "tool-link",
}: {
  href: string | null;
  children: ReactNode;
  title?: string;
  className?: string;
}) {
  if (!href) return null;
  return (
    <a className={className} href={href} target="_blank" rel="noreferrer" title={title}>
      {children}
      <Icon name="external" size={12} />
    </a>
  );
}
