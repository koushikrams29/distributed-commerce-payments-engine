import type { ReactNode } from "react";

interface Props {
  title: ReactNode;
  /** Short context under or beside the title: scope, freshness, counts. */
  meta?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}

export function Panel({ title, meta, actions, children, className, id }: Props) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section
      className={className ? `panel ${className}` : "panel"}
      aria-labelledby={headingId}
      id={id}
    >
      <header className="panel__header">
        <div className="panel__titles">
          <h2 id={headingId}>{title}</h2>
          {meta && <span className="panel__meta">{meta}</span>}
        </div>
        {actions && <div className="panel__actions">{actions}</div>}
      </header>
      {children}
    </section>
  );
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h1 className="page-header__title">{title}</h1>
        {description && <p className="page-header__description">{description}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </div>
  );
}

export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "success" | "warning" | "danger";
}) {
  return (
    <div className={tone ? `stat stat--${tone}` : "stat"}>
      <div className="stat__label">{label}</div>
      <div className="stat__value">{value}</div>
      {hint && <div className="stat__hint">{hint}</div>}
    </div>
  );
}

export function KeyValues({ items }: { items: [ReactNode, ReactNode][] }) {
  return (
    <dl className="kv">
      {items.map(([key, value], index) => (
        <div className="kv__row" key={index}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
