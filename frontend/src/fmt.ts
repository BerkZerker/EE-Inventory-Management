/** Format a datetime string (e.g. "2026-02-14 18:29:55") to 12-hour time. */
export function fmtDateTime(raw: string): string {
  const d = new Date(raw.replace(" ", "T"));
  if (isNaN(d.getTime())) return raw;
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });
}

/** Format a date-only string (e.g. "2026-02-14") nicely. */
export function fmtDate(raw: string): string {
  const d = new Date(raw + "T00:00:00");
  if (isNaN(d.getTime())) return raw;
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
