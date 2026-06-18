export function formatCurrency(value: number | null | undefined, decimals = 0): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

export function formatPct(value: number | null | undefined, decimals = 2): string {
  if (value == null) return "—";
  return `${(value * 100).toFixed(decimals)}%`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export function statusColor(status: string): string {
  switch (status) {
    case "completed": return "text-emerald-400";
    case "running":   return "text-blue-400";
    case "failed":    return "text-red-400";
    case "pending":   return "text-slate-400";
    default:          return "text-slate-400";
  }
}

export function statusBg(status: string): string {
  switch (status) {
    case "completed": return "bg-emerald-500/15 text-emerald-300 ring-emerald-500/30";
    case "running":   return "bg-blue-500/15 text-blue-300 ring-blue-500/30";
    case "failed":    return "bg-red-500/15 text-red-300 ring-red-500/30";
    case "pending":   return "bg-slate-500/15 text-slate-300 ring-slate-500/30";
    default:          return "bg-slate-500/15 text-slate-300 ring-slate-500/30";
  }
}
