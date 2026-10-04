const PATHS = {
  overview: "M3 3h7v9H3zM14 3h7v5h-7zM14 12h7v9h-7zM3 16h7v5H3z",
  orders: "M6 2h12l2 4v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6zM4 6h16M9 10h6",
  events: "M3 12h4l3-8 4 16 3-8h4",
  payments: "M2 6h20v12H2zM2 10h20M6 15h4",
  inventory: "M21 8 12 3 3 8v8l9 5 9-5zM3 8l9 5 9-5M12 13v8",
  failures: "M12 3 2 20h20zM12 10v4M12 17h.01",
  services: "M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01",
  menu: "M3 6h18M3 12h18M3 18h18",
  close: "M6 6l12 12M18 6 6 18",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  check: "M5 12l5 5L20 7",
  external: "M14 4h6v6M20 4l-9 9M18 14v6H4V6h6",
  refresh: "M20 11a8 8 0 0 0-14.9-4M4 4v4h4M4 13a8 8 0 0 0 14.9 4M20 20v-4h-4",
  search: "M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM21 21l-5-5",
  pause: "M8 5v14M16 5v14",
  play: "M7 4l13 8-13 8z",
  chevron: "M9 6l6 6-6 6",
  plus: "M12 5v14M5 12h14",
  replay: "M3 12a9 9 0 1 0 3-6.7M3 4v5h5",
  trace: "M4 6h10M8 12h12M4 18h8",
  signout: "M15 4h4v16h-4M10 8l-4 4 4 4M6 12h11",
} as const;

export type IconName = keyof typeof PATHS;

interface Props {
  name: IconName;
  size?: number;
  className?: string;
  /** Leave unset for decorative icons next to visible text. */
  label?: string;
}

export function Icon({ name, size = 16, className, label }: Props) {
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      focusable="false"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
