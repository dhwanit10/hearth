import { memo, useState } from "react";
import { Check, Copy } from "lucide-react";

/**
 * Small markdown renderer for assistant replies.
 *
 * Supports fenced code blocks, inline code, bold, italic, links, lists and
 * quotes - enough for real answers without shipping a parser dependency.
 * Everything is rendered as React elements (never `dangerouslySetInnerHTML`),
 * so message content can never inject markup into the page.
 */

const FENCE = /^\s*```([^\s`]*)\s*$/;
const LIST_ITEM = /^\s*(?:[-*+]|\d+\.)\s+/;
const QUOTE = /^\s*>\s?/;

function parseBlocks(source) {
  const lines = String(source ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    const fence = line.match(FENCE);
    if (fence) {
      const lang = fence[1] || "";
      const body = [];
      index += 1;
      while (index < lines.length && !FENCE.test(lines[index])) {
        body.push(lines[index]);
        index += 1;
      }
      index += 1; // consume the closing fence
      blocks.push({ type: "code", lang, text: body.join("\n") });
      continue;
    }

    if (!line.trim()) {
      index += 1;
      continue;
    }

    if (LIST_ITEM.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line);
      const items = [];
      while (index < lines.length && LIST_ITEM.test(lines[index])) {
        items.push(lines[index].replace(LIST_ITEM, ""));
        index += 1;
      }
      blocks.push({ type: "list", ordered, items });
      continue;
    }

    if (QUOTE.test(line)) {
      const body = [];
      while (index < lines.length && QUOTE.test(lines[index])) {
        body.push(lines[index].replace(QUOTE, ""));
        index += 1;
      }
      blocks.push({ type: "quote", text: body.join("\n") });
      continue;
    }

    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !FENCE.test(lines[index]) &&
      !LIST_ITEM.test(lines[index]) &&
      !QUOTE.test(lines[index])
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ type: "p", text: paragraph.join("\n") });
  }

  return blocks;
}

const INLINE_SOURCE = [
  // Order matters: the first alternative that matches at a given position wins,
  // and code spans must be consumed before emphasis so `my_var` stays intact.
  "`(?<code>[^`\\n]+)`",
  "\\*\\*\\*(?<strongem>[\\s\\S]+?)\\*\\*\\*",
  "\\*\\*(?<strong>[\\s\\S]+?)\\*\\*",
  "__(?<strongAlt>[\\s\\S]+?)__",
  "\\*(?<em>[^*\\n]+)\\*",
  // Underscore emphasis only at word boundaries, so snake_case survives.
  "(?<![\\w])_(?<emAlt>[^_\\n]+)_(?![\\w])",
  "\\[(?<label>[^\\]\\n]+)\\]\\((?<href>[^)\\s]+)\\)",
].join("|");

function renderInline(text, keyPrefix) {
  const nodes = [];
  let cursor = 0;
  let match;
  // A fresh, stateful RegExp per call: this function recurses for nested
  // emphasis, so a shared instance would corrupt the outer scan position.
  const pattern = new RegExp(INLINE_SOURCE, "g");

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > cursor) nodes.push(text.slice(cursor, match.index));

    const groups = match.groups ?? {};
    const key = `${keyPrefix}:${match.index}`;
    const inner = (value) => renderInline(value, key);

    if (groups.code !== undefined) {
      nodes.push(<code key={key}>{groups.code}</code>);
    } else if (groups.strongem !== undefined) {
      nodes.push(
        <strong key={key}>
          <em>{inner(groups.strongem)}</em>
        </strong>,
      );
    } else if (groups.strong !== undefined || groups.strongAlt !== undefined) {
      nodes.push(<strong key={key}>{inner(groups.strong ?? groups.strongAlt)}</strong>);
    } else if (groups.em !== undefined || groups.emAlt !== undefined) {
      nodes.push(<em key={key}>{inner(groups.em ?? groups.emAlt)}</em>);
    } else if (groups.href !== undefined) {
      nodes.push(
        <a key={key} href={groups.href} target="_blank" rel="noopener noreferrer">
          {inner(groups.label)}
        </a>,
      );
    } else {
      nodes.push(match[0]);
    }

    cursor = match.index + match[0].length;
  }

  if (cursor < text.length) nodes.push(text.slice(cursor));
  return nodes;
}

/** Paragraph text with hard line breaks preserved. */
function TextBlock({ text, prefix }) {
  const lines = text.split("\n");
  return lines.map((line, index) => (
    <span key={`${prefix}:line:${index}`}>
      {index > 0 ? <br /> : null}
      {renderInline(line, `${prefix}:${index}`)}
    </span>
  ));
}

const CodeBlock = memo(function CodeBlock({ lang, text }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard blocked - the code is selectable anyway */
    }
  };

  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{lang || "code"}</span>
        <button type="button" className="code-copy" onClick={copy} aria-label="Copy code">
          {copied ? <Check size={12} aria-hidden="true" /> : <Copy size={12} aria-hidden="true" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre>
        <code>{text}</code>
      </pre>
    </div>
  );
});

export function Markdown({ text }) {
  const blocks = parseBlocks(text);
  return (
    <div className="md">
      {blocks.map((block, index) => {
        const key = `block:${index}`;

        if (block.type === "code") {
          return <CodeBlock key={key} lang={block.lang} text={block.text} />;
        }

        if (block.type === "list") {
          const List = block.ordered ? "ol" : "ul";
          return (
            <List key={key}>
              {block.items.map((item, itemIndex) => (
                <li key={`${key}:${itemIndex}`}>
                  {renderInline(item, `${key}:${itemIndex}`)}
                </li>
              ))}
            </List>
          );
        }

        if (block.type === "quote") {
          return (
            <blockquote key={key}>
              <TextBlock text={block.text} prefix={key} />
            </blockquote>
          );
        }

        return (
          <p key={key}>
            <TextBlock text={block.text} prefix={key} />
          </p>
        );
      })}
    </div>
  );
}

export default Markdown;
