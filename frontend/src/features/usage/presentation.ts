export function dollars(value: string | number | null): string {
  if (value === null) return "Not available";
  const amount = Number(value);
  if (amount > 0 && amount < 0.000001) return "< $0.000001";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 6,
  }).format(amount);
}

export function duration(milliseconds: number): string {
  return `${(milliseconds / 1000).toLocaleString("en-US", { maximumFractionDigits: 1 })} s`;
}
