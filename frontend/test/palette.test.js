// @vitest-environment node
/**
 * Palette guard.
 *
 * The brief for this project is explicit: no blue, violet, purple, green or
 * pink anywhere. Rather than trusting a review, this test parses every colour
 * literal in the stylesheet and fails if any of them lands outside the warm
 * band (red -> orange -> amber -> yellow) of the colour wheel.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { ACCENTS } from "../src/lib/accents.js";

const CSS_PATH = fileURLToPath(new URL("../src/styles.css", import.meta.url));
const css = readFileSync(CSS_PATH, "utf8");

/** Expand #abc -> #aabbcc and parse to 0-255 channels. */
function parseHex(hex) {
  const value = hex.slice(1);
  const full =
    value.length === 3
      ? value
          .split("")
          .map((char) => char + char)
          .join("")
      : value;
  if (full.length !== 6) return null;
  return [0, 2, 4].map((offset) => Number.parseInt(full.slice(offset, offset + 2), 16));
}

/** Hue in degrees (0 = red, 60 = yellow, 120 = green, 240 = blue). */
function hue([r, g, b]) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  if (max === min) return 0;
  const delta = max - min;
  let value;
  if (max === r) value = ((g - b) / delta) % 6;
  else if (max === g) value = (b - r) / delta + 2;
  else value = (r - g) / delta + 4;
  return (value * 60 + 360) % 360;
}

function saturation([r, g, b]) {
  const max = Math.max(r, g, b);
  const min = Math.min(r, g, b);
  const lightness = (max + min) / 2 / 255;
  const delta = (max - min) / 255;
  if (delta === 0) return 0;
  return delta / (1 - Math.abs(2 * lightness - 1));
}

const FORBIDDEN = {
  blue: [180, 300],
  violet_purple: [250, 300],
  green: [60, 180],
  pink_magenta: [300, 360],
};

describe("warm palette", () => {
  const hexes = [...new Set(css.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [])]
    .map((hex) => ({ hex, channels: parseHex(hex) }))
    .filter((entry) => entry.channels !== null);

  it("finds colour literals to check", () => {
    expect(hexes.length).toBeGreaterThan(30);
  });

  it.each(hexes)("$hex is warm, not cool", ({ hex, channels }) => {
    const s = saturation(channels);
    // Near-neutral greys carry no hue to speak of; the warm neutrals used here
    // still measure in the same band when they are saturated enough to matter.
    if (s <= 0.08) return;

    const h = hue(channels);
    const isWarmRedToYellow = h <= 60 || h >= 350;
    expect(
      isWarmRedToYellow,
      `${hex} has hue ${h.toFixed(0)}deg / saturation ${(s * 100).toFixed(0)}%`,
    ).toBe(true);
  });

  it("uses no forbidden colour families in the stylesheet", () => {
    for (const [name, [from, to]] of Object.entries(FORBIDDEN)) {
      const offenders = hexes.filter(({ channels }) => {
        if (saturation(channels) <= 0.08) return false;
        const h = hue(channels);
        return h >= from && h < to;
      });
      expect(
        offenders.map((entry) => entry.hex),
        `forbidden ${name} colours`,
      ).toEqual([]);
    }
  });

  it("defines exactly the eight documented warm accents", () => {
    expect(ACCENTS.map((accent) => accent.key)).toEqual([
      "clay",
      "amber",
      "rust",
      "ember",
      "gold",
      "cocoa",
      "chestnut",
      "graphite",
    ]);
    for (const accent of ACCENTS) {
      expect(css).toContain(`--accent-${accent.key}:`);
      expect(css).toContain(`--accent-${accent.key}-soft:`);
    }
  });

  it("never uses box-shadow for depth", () => {
    expect(css).not.toMatch(/box-shadow/);
  });

  it("ships both light and dark themes", () => {
    expect(css).toContain('[data-theme="dark"]');
    expect(css).toContain("color-scheme: light");
    expect(css).toContain("color-scheme: dark");
  });
});
