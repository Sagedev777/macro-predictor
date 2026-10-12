// frontend/src/utils/formatters.ts
import { format, parseISO } from 'date-fns';

export function formatTimestamp(
  isoString: string | null | undefined,
  useUtc: boolean = true,
  includeSeconds: boolean = false
): string {
  if (!isoString) return '—';
  try {
    const d = parseISO(isoString);
    if (isNaN(d.getTime())) return isoString;

    if (useUtc) {
      const year = d.getUTCFullYear();
      const month = String(d.getUTCMonth() + 1).padStart(2, '0');
      const day = String(d.getUTCDate()).padStart(2, '0');
      const hours = String(d.getUTCHours()).padStart(2, '0');
      const mins = String(d.getUTCMinutes()).padStart(2, '0');
      const secs = String(d.getUTCSeconds()).padStart(2, '0');
      return includeSeconds
        ? `${year}-${month}-${day} ${hours}:${mins}:${secs} UTC`
        : `${year}-${month}-${day} ${hours}:${mins} UTC`;
    } else {
      const fmt = includeSeconds ? 'yyyy-MM-dd HH:mm:ss' : 'yyyy-MM-dd HH:mm';
      return `${format(d, fmt)} Local`;
    }
  } catch {
    return isoString;
  }
}

export function formatPct(val: number | null | undefined, decimals = 2, prefixSign = false): string {
  if (val === null || val === undefined || isNaN(val)) return '—';
  const sign = prefixSign && val > 0 ? '+' : '';
  return `${sign}${val.toFixed(decimals)}%`;
}

export function formatNumber(val: number | null | undefined, decimals = 2): string {
  if (val === null || val === undefined || isNaN(val)) return '—';
  return val.toFixed(decimals);
}

export function getDirectionBadge(dir: string | null | undefined) {
  if (!dir) return { label: 'PENDING', className: 'badge-neutral' };
  const d = dir.toUpperCase();
  if (d === 'BULLISH' || d === 'BEAT') {
    return { label: d, className: 'badge-bullish' };
  }
  if (d === 'BEARISH' || d === 'MISS') {
    return { label: d, className: 'badge-bearish' };
  }
  return { label: 'NEUTRAL', className: 'badge-neutral' };
}
