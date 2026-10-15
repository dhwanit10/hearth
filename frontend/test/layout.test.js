// @vitest-environment node
/**
 * Layout guard.
 *
 * A short viewport once made the app look completely unscrollable: the empty
 * states had no `overflow` at all, centring with `place-items` pushed content
 * above the scroll origin, and the flex column could outgrow its grid row and
 * get clipped by `body { overflow: hidden }`.
 *
 * These tests parse the stylesheet into rules and assert the invariants that
 * fix that, so the same class of bug cannot quietly return.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const CSS_PATH = fileURLToPath(new URL("../src/styles.css", import.meta.url));

const css = readFileSync(CSS_PATH, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

/** Every `selector { declarations }` pair, with @media contents flattened. */
function parseRules(source) {
  const rules = [];
  const pattern = /([^{}]+)\{([^{}]*)\}/g;
  let match;

  while ((match = pattern.exec(source)) !== null) {
    const selectorList = match[1]
      .replace(/\s+/g, " ")
      .trim()
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);
    if (selectorList.length === 0) continue;
    if (selectorList.every((item) => item.startsWith("@") || item.endsWith("%"))) continue;

    const declarations = Object.fromEntries(
      match[2]
        .split(";")
        .map((line) => line.trim())
        .filter(Boolean)
        .map((line) => {
          const index = line.indexOf(":");
          if (index === -1) return [line.toLowerCase(), ""];
          return [
            line.slice(0, index).trim().toLowerCase(),
            line.slice(index + 1).trim(),
          ];
        }),
    );

    rules.push({ selectorList, declarations });
  }

  return rules;
}

const rules = parseRules(css);

const matching = (selector) =>
  rules.filter((rule) => rule.selectorList.includes(selector));

/** Merged declarations for every rule naming `selector`. */
function declarationsFor(selector) {
  return Object.assign({}, ...matching(selector).map((rule) => rule.declarations));
}

const hasRule = (selector) => matching(selector).length > 0;

const SCROLL_REGIONS = [
  ".messages",
  ".sidebar__list",
  ".dialog__body",
  ".welcome",
  ".start",
  ".pane",
];

const CENTERED_PANES = [".welcome", ".start", ".pane"];

const FIXED_CHROME = [
  ".chat-header",
  ".composer",
  ".sidebar__head",
  ".sidebar__section",
  ".sidebar__foot",
  ".dialog__head",
  ".dialog__foot",
];

describe("layout can always scroll", () => {
  it("parses the stylesheet", () => {
    expect(rules.length).toBeGreaterThan(100);
  });

  it.each(SCROLL_REGIONS)("%s declares its own scrolling", (selector) => {
    // Each region must be self-contained: relying on a utility class being
    // remembered in JSX is how a region silently stops scrolling.
    expect(declarationsFor(selector)["overflow-y"]).toBe("auto");
  });

  it.each(CENTERED_PANES)("%s never centres with place-items", (selector) => {
    const declarations = declarationsFor(selector);
    // `place-items: center` on an overflowing container pushes its top edge
    // above the scroll origin, where it can never be reached.
    expect(declarations["place-items"]).toBeUndefined();
    expect(declarations["align-items"]).toBeUndefined();
  });

  it.each(CENTERED_PANES)("%s centres its child with auto margins", (selector) => {
    expect(hasRule(`${selector} > *`)).toBe(true);
    expect(declarationsFor(`${selector} > *`).margin).toBe("auto");
  });

  it("lets the columns shrink so the transcript scrolls instead of clipping", () => {
    // Without min-height: 0 the flex column outgrows the grid row and is
    // clipped by body { overflow: hidden }, so nothing scrolls.
    expect(declarationsFor(".app__body")["min-height"]).toBe("0");
    expect(declarationsFor(".app__body")["min-width"]).toBe("0");
    expect(declarationsFor(".sidebar")["min-height"]).toBe("0");
    expect(declarationsFor(".messages")["min-height"]).toBe("0");
    expect(declarationsFor(".dialog__body")["min-height"]).toBe("0");
  });

  it("pins the fixed chrome so only the content regions move", () => {
    for (const selector of FIXED_CHROME) {
      expect(declarationsFor(selector).flex, `${selector} must not shrink`).toBe("none");
    }
  });

  it("falls back to vh where dynamic viewport units are unavailable", () => {
    expect(/height:\s*100vh/.test(css)).toBe(true);
    expect(/height:\s*100dvh/.test(css)).toBe(true);
    expect(/min-height:\s*100vh/.test(css)).toBe(true);
    expect(/min-height:\s*100dvh/.test(css)).toBe(true);
    // Declaration order matters: the fallback must come first so the dynamic
    // unit wins where it is understood.
    expect(/height:\s*100vh;[^}]*height:\s*100dvh/.test(css)).toBe(true);
  });

  it("compacts the chrome on short viewports", () => {
    const breakpoints = [...css.matchAll(/@media\s*\(max-height:\s*(\d+)px\)/g)].map((match) =>
      Number(match[1]),
    );
    // Must trigger on a short laptop screen, and get progressively tighter.
    expect(breakpoints).toContain(740);
    expect(breakpoints).toContain(620);
  });

  it("lets the dialog and its scrim survive a very short window", () => {
    expect(declarationsFor(".dialog-scrim")["overflow-y"]).toBe("auto");
    expect(declarationsFor(".dialog")["margin"]).toBe("auto");
    expect(declarationsFor(".dialog")["max-height"]).toContain("dvh");
  });

  it("still keeps the app free of shadows", () => {
    expect(/box-shadow/.test(css)).toBe(false);
  });
});
