// Shared formatting. The console renders observation time and ingestion time separately
// everywhere, because collapsing them hides latency and out-of-order arrival.
const IST = 'Asia/Kolkata';

const parts = new Intl.DateTimeFormat('en-GB', {
  timeZone: IST, hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false
});
const dayMonth = new Intl.DateTimeFormat('en-GB', { timeZone: IST, day: '2-digit', month: 'short' });

export const TZ_LABEL = 'IST';

export function clock(value) {
  if (!value) return '--:--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return parts.format(date);
}

export function dayLabel(value) {
  if (!value) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return dayMonth.format(date);
}

export function bothTimes(item) {
  return `${clock(item.event_time)} → ${clock(item.ingest_time)}`;
}

// Ingest latency, or a marker that arrival order disagreed with observation order.
export function latency(item) {
  if (!item?.event_time || !item?.ingest_time) return null;
  const observed = new Date(item.event_time).getTime();
  const ingested = new Date(item.ingest_time).getTime();
  if (Number.isNaN(observed) || Number.isNaN(ingested)) return null;
  const seconds = Math.round((ingested - observed) / 1000);
  return { seconds, late: seconds > 120 };
}

export function relativeLag(seconds) {
  if (seconds === null || seconds === undefined) return 'n/a';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

export function age(iso, now = '2026-10-12T14:06:50+05:30') {
  const then = new Date(iso).getTime();
  const reference = new Date(now).getTime();
  if (Number.isNaN(then) || Number.isNaN(reference)) return '—';
  const minutes = Math.max(0, Math.round((reference - then) / 60000));
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes} min ago`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min ago`;
}

// Compact relative time for table cells. Accepts a bare HH:MM:SS in scenario local time
// (IST, +05:30) as well as a full timestamp.
export function ago(value, now = '2026-10-12T14:05:00+05:30') {
  if (!value) return 'never';
  const iso = /^\d{2}:\d{2}:\d{2}$/.test(value) ? `2026-10-12T${value}+05:30` : value;
  const then = new Date(iso).getTime();
  const reference = new Date(now).getTime();
  if (Number.isNaN(then) || Number.isNaN(reference)) return String(value);
  const seconds = Math.max(0, Math.round((reference - then) / 1000));
  if (seconds < 45) return 'just now';
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function pct(value) {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

export function titleCase(value) {
  return String(value || '')
    .toLowerCase()
    .split(/[\s_]+/)
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function compact(value) {
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  if (Number.isNaN(number)) return String(value);
  if (Math.abs(number) >= 1000) return `${(number / 1000).toFixed(1)}k`;
  return String(Math.round(number * 100) / 100);
}

export function titleFromEventType(type) {
  return titleCase(String(type || '').replace(/_/g, ' '));
}