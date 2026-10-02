const currency = new Intl.NumberFormat(undefined, {
  style: "currency",
  currency: "USD",
});

const time = new Intl.DateTimeFormat(undefined, {
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export function formatMoney(amount: number): string {
  return currency.format(amount);
}

export function formatTime(iso: string | null): string {
  if (!iso) return "—";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "—" : time.format(date);
}

export function shortId(id: string): string {
  return id.slice(0, 8);
}
