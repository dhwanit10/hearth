import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Check, Copy } from "lucide-react";

import { cx } from "../lib/cx.js";
import { clockTime, dayLabel, isSameDay } from "../lib/time.js";
import Avatar from "./Avatar.jsx";
import Markdown from "./Markdown.jsx";

const CONTINUE_WINDOW_MS = 4 * 60 * 1000;

function isContinuation(previous, current) {
  if (!previous || previous.role !== current.role) return false;
  const gap = new Date(current.created_at) - new Date(previous.created_at);
  return gap >= 0 && gap < CONTINUE_WINDOW_MS;
}

const MessageRow = memo(function MessageRow({ message, agent, continued }) {
  const [copied, setCopied] = useState(false);
  const outgoing = message.role === "user";

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      /* clipboard unavailable */
    }
  }, [message.content]);

  return (
    <div
      className={cx(
        "message",
        outgoing ? "message--out" : "message--in",
        continued && "message--continued",
      )}
    >
      <div className="message__gutter">
        {!outgoing && !continued ? (
          <Avatar name={agent.name} accent={agent.accent} size="sm" />
        ) : null}
      </div>

      <div className="message__body">
        <div className={cx("bubble", outgoing ? "bubble--out" : "bubble--in")}>
          <Markdown text={message.content} />
        </div>

        <div className="message__foot">
          <span className="message__time">{clockTime(message.created_at)}</span>
          <div className="message__tools">
            <button
              type="button"
              className={cx("tool-link", copied && "is-ok")}
              onClick={copy}
              aria-label="Copy message"
            >
              {copied ? <Check size={11} aria-hidden="true" /> : <Copy size={11} aria-hidden="true" />}
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
});

function StreamingRow({ agent, text }) {
  return (
    <div className="message message--in">
      <div className="message__gutter">
        <Avatar name={agent.name} accent={agent.accent} size="sm" />
      </div>
      <div className="message__body">
        <div className={cx("bubble", "bubble--in", text && "bubble--partial")}>
          {text ? (
            <>
              <Markdown text={text} />
              <span className="caret" aria-hidden="true" />
            </>
          ) : (
            <span className="typing" aria-label={`${agent.name} is typing`}>
              <span />
              <span />
              <span />
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/**
 * Scrollable transcript.
 *
 * Auto-scrolls only while the reader is already at the bottom, so scrolling up
 * to read history is never yanked away by an incoming message. A bottom
 * sentinel is used instead of assigning `scrollTop` so this keeps working
 * whichever element ends up being the scroller on a short window.
 */
export default function MessageList({ messages, agent, streaming }) {
  const scrollRef = useRef(null);
  const bottomRef = useRef(null);
  const pinnedRef = useRef(true);

  const streamingText = streaming?.text ?? "";
  const rowCount = messages.length + (streaming?.active ? 1 : 0);

  useLayoutEffect(() => {
    if (!pinnedRef.current) return;
    bottomRef.current?.scrollIntoView({ block: "end", inline: "nearest" });
  }, [rowCount, streamingText]);

  const syncPinned = useCallback(() => {
    const element = scrollRef.current;
    if (!element) return;
    if (element.scrollHeight > element.clientHeight + 1) {
      pinnedRef.current =
        element.scrollHeight - element.scrollTop - element.clientHeight < 80;
      return;
    }
    // The transcript is not the scroller here, so measure the document instead.
    pinnedRef.current =
      document.documentElement.scrollHeight - window.innerHeight - window.scrollY < 120;
  }, []);

  useEffect(() => {
    window.addEventListener("scroll", syncPinned, { passive: true });
    return () => window.removeEventListener("scroll", syncPinned);
  }, [syncPinned]);

  return (
    <div
      className="messages scroll-area"
      ref={scrollRef}
      onScroll={syncPinned}
      role="log"
      aria-label={`Conversation with ${agent.name}`}
    >
      <div className="messages__inner">
        {messages.map((message, index) => {
          const previous = messages[index - 1];
          const showDay = !previous || !isSameDay(previous.created_at, message.created_at);
          return (
            <div key={message.id}>
              {showDay ? <div className="day-sep">{dayLabel(message.created_at)}</div> : null}
              <MessageRow
                message={message}
                agent={agent}
                continued={!showDay && isContinuation(previous, message)}
              />
            </div>
          );
        })}

        {streaming?.active ? <StreamingRow agent={agent} text={streamingText} /> : null}

        <div ref={bottomRef} aria-hidden="true" />
      </div>
    </div>
  );
}
