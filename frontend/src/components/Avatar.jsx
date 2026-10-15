import { accentStyle, initialsFor } from "../lib/accents.js";
import { cx } from "../lib/cx.js";

/**
 * Initials avatar tinted with the companion's warm accent.
 * No images, no emoji, no shadows - just a tinted disc and a hairline border.
 */
export default function Avatar({ name, accent, size = "sm", className }) {
  return (
    <span
      className={cx("avatar", `avatar--${size}`, className)}
      style={accentStyle(accent)}
      role="img"
      aria-label={name || "Companion"}
      title={name || undefined}
    >
      {initialsFor(name)}
    </span>
  );
}
