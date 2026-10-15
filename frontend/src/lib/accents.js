/**
 * Companion avatar tints.
 *
 * Every key maps to the CSS custom properties `--accent-<key>` and
 * `--accent-<key>-soft` defined for both themes in styles.css. The palette is
 * intentionally warm (clay, amber, rust, ember, gold, cocoa, chestnut,
 * graphite): no blue, violet, purple, green or pink anywhere in the app.
 */
export const ACCENTS = [
  { key: "clay", label: "Clay" },
  { key: "amber", label: "Amber" },
  { key: "rust", label: "Rust" },
  { key: "ember", label: "Ember" },
  { key: "gold", label: "Gold" },
  { key: "cocoa", label: "Cocoa" },
  { key: "chestnut", label: "Chestnut" },
  { key: "graphite", label: "Graphite" },
];

export const DEFAULT_ACCENT = "clay";

const KEYS = new Set(ACCENTS.map((accent) => accent.key));

/** Inline style that points the .avatar tint variables at one accent. */
export function accentStyle(accent) {
  const key = KEYS.has(accent) ? accent : DEFAULT_ACCENT;
  return {
    "--agent": `var(--accent-${key})`,
    "--agent-soft": `var(--accent-${key}-soft)`,
  };
}

export function accentLabel(accent) {
  return ACCENTS.find((item) => item.key === accent)?.label ?? "Clay";
}

/** Deterministic initials: "Ms. Verma" -> "MV", "Aria" -> "AR". */
export function initialsFor(name) {
  const words = String(name ?? "")
    .replace(/[^\p{L}\p{N}\s.'-]/gu, " ")
    .split(/\s+/)
    .filter(Boolean);

  if (words.length === 0) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return `${words[0][0]}${words[words.length - 1][0]}`.toUpperCase();
}
