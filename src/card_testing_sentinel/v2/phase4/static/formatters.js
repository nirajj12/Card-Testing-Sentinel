export function percent(value, digits = 1) {
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
}

export function riskScore(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(3) : "—";
}

export function latency(value) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(3)} ms` : "—";
}

export function currency(value, code = "USD") {
  try {
    return new Intl.NumberFormat("en-US", { style: "currency", currency: code }).format(value);
  } catch {
    return `${code} ${value}`;
  }
}

export function timestamp(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleString();
}

export function titleCase(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
