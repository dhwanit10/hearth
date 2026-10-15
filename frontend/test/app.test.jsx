/**
 * Frontend tests: pure helpers plus a full render of the app shell.
 *
 * The render test runs the real React tree through react-dom/server under
 * jsdom, which catches broken imports, bad hook usage and JSX mistakes that a
 * production build alone would not surface.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import App from "../src/App.jsx";
import Markdown from "../src/components/Markdown.jsx";
import { StartPane, WelcomePane } from "../src/components/EmptyStates.jsx";
import { initialsFor } from "../src/lib/accents.js";
import { dayLabel, isSameDay, previewText, relativeTime } from "../src/lib/time.js";

describe("App shell", () => {
  it("renders the brand mark and never leaks a raw escape sequence", () => {
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("Hearth");
    expect(html).not.toContain("\\u");
  });
});

describe("initialsFor", () => {
  it("builds initials from a full name", () => {
    expect(initialsFor("Ms. Verma")).toBe("MV");
    expect(initialsFor("Aria")).toBe("AR");
    expect(initialsFor("Mary Jane Watson")).toBe("MW");
    expect(initialsFor("")).toBe("?");
  });
});

describe("Markdown", () => {
  const render = (text) => renderToStaticMarkup(<Markdown text={text} />);

  it("renders bold, italic and inline code", () => {
    const html = render("This is **bold**, *soft* and `code`.");
    expect(html).toContain("<strong>bold</strong>");
    expect(html).toContain("<em>soft</em>");
    expect(html).toContain("<code>code</code>");
  });

  it("renders fenced code blocks with a language label", () => {
    const html = render("Try this:\n```python\nprint('hi')\n```\nDone.");
    expect(html).toContain("code-block");
    expect(html).toContain("python");
    expect(html).toContain("print(&#x27;hi&#x27;)");
  });

  it("renders lists, quotes and links", () => {
    expect(render("- one\n- two")).toContain("<ul>");
    expect(render("1. one\n2. two")).toContain("<ol>");
    expect(render("> quoted")).toContain("<blockquote>");
    expect(render("[docs](https://example.com)")).toContain('href="https://example.com"');
  });

  it("escapes raw HTML instead of injecting it", () => {
    const html = render('<img src=x onerror="alert(1)">');
    expect(html).not.toContain("<img");
    expect(html).toContain("&lt;img");
  });

  it("keeps nested emphasis intact (recursive inline scan)", () => {
    const html = render("**bold with *nested* text** and more **bold** after");
    expect(html.match(/<strong>/g)).toHaveLength(2);
    expect(html).toContain("<em>nested</em>");
    expect(html).toContain("after");
  });
});

describe("scroll containers", () => {
  it("wraps the welcome state in the class pair the layout relies on", () => {
    const html = renderToStaticMarkup(
      <WelcomePane personas={[]} onNew={() => {}} onQuickStart={() => {}} />,
    );
    // styles.css centres and scrolls `.welcome` via a `margin: auto` child, so
    // this pairing is what keeps the empty state reachable on a short screen.
    expect(html).toContain('class="welcome"');
    expect(html).toContain("welcome__inner");
  });

  it("wraps the empty conversation in the same pattern", () => {
    const html = renderToStaticMarkup(
      <StartPane
        agent={{ id: "a1", name: "Aria", accent: "clay", persona: "girlfriend" }}
        persona={{ description: "Warm and playful", traits: ["warm"], starters: ["hi"] }}
        onStarter={() => {}}
      />,
    );
    expect(html).toContain("start scroll-area");
    expect(html).toContain("start__inner");
  });
});

describe("time helpers", () => {
  it("formats relative times", () => {
    expect(relativeTime(new Date())).toBe("now");
    expect(relativeTime(new Date(Date.now() - 5 * 60_000))).toBe("5m");
    expect(relativeTime(new Date(Date.now() - 3 * 3_600_000))).toBe("3h");
    expect(relativeTime(new Date(Date.now() - 2 * 86_400_000))).toBe("2d");
    expect(relativeTime(null)).toBe("");
  });

  it("labels days", () => {
    expect(dayLabel(new Date())).toBe("Today");
    expect(dayLabel(new Date(Date.now() - 86_400_000))).toBe("Yesterday");
  });

  it("detects same-day timestamps", () => {
    expect(isSameDay(new Date(), new Date())).toBe(true);
    expect(isSameDay(new Date(), new Date(Date.now() - 86_400_000))).toBe(false);
  });

  it("flattens previews", () => {
    expect(previewText("hello\n\n  world")).toBe("hello world");
    expect(previewText("x".repeat(200)).length).toBeLessThanOrEqual(90);
  });
});
