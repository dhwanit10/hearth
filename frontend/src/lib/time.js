/** Date/time helpers. The backend stores UTC ISO-8601 strings. */

function toDate(value) {
  if (!value) return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function startOfDay(date) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

const DAY = 86_400_000;

/** "now", "4m", "2h", "3d", then a short date. */
export function relativeTime(value) {
  const date = toDate(value);
  if (!date) return "";

  const diff = Date.now() - date.getTime();
  if (diff < 45_000) return "now";
  if (diff < 3_600_000) return `${Math.round(diff / 60_000)}m`;
  if (diff < 86_400_000) return `${Math.round(diff / 3_600_000)}h`;
  if (diff < 7 * DAY) return `${Math.round(diff / DAY)}d`;

  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** "14:05" in the viewer's locale. */
export function clockTime(value) {
  const date = toDate(value);
  if (!date) return "";
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

/** "Today" / "Yesterday" / "12 March 2026". */
export function dayLabel(value) {
  const date = toDate(value);
  if (!date) return "";

  const today = startOfDay(new Date());
  const target = startOfDay(date);
  if (target === today) return "Today";
  if (target === today - DAY) return "Yesterday";

  const options = { day: "numeric", month: "long" };
  if (date.getFullYear() !== new Date().getFullYear()) {
    options.year = "numeric";
  }
  return date.toLocaleDateString(undefined, options);
}

/** True when two timestamps fall on the same calendar day. */
export function isSameDay(a, b) {
  const first = toDate(a);
  const second = toDate(b);
  if (!first || !second) return false;
  return startOfDay(first) === startOfDay(second);
}

/** Single line summary of a message, for sidebar previews. */
export function previewText(content, limit = 90) {
  const flat = String(content ?? "").replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}\u2026` : flat;
}
