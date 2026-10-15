import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowUp, Square } from "lucide-react";

import { cx } from "../lib/cx.js";

export const MAX_MESSAGE_LENGTH = 8000;
const COUNTER_THRESHOLD = 7000;
const MAX_TEXTAREA_HEIGHT = 168;

/**
 * Message composer.
 *
 * Enter sends, Shift+Enter makes a new line, and the textarea grows with the
 * content up to a cap. While a reply is streaming the send button becomes a
 * stop button, and the input stays usable so the next thought can be typed.
 */
export default function Composer({
  agentName,
  onSend,
  onStop,
  streaming,
  connectionState,
  notices,
  disabledReason,
}) {
  const [draft, setDraft] = useState("");
  const textareaRef = useRef(null);

  const online = connectionState === "online";
  const trimmed = draft.trim();
  const tooLong = draft.length > MAX_MESSAGE_LENGTH;
  const canSend = online && !streaming && trimmed.length > 0 && !tooLong;

  const resize = useCallback(() => {
    const element = textareaRef.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, MAX_TEXTAREA_HEIGHT)}px`;
  }, []);

  useEffect(() => {
    resize();
  }, [draft, resize]);

  // Keep focus on the composer when the reader switches companion, but never
  // pop the on-screen keyboard on a phone.
  useEffect(() => {
    if (!window.matchMedia("(min-width: 861px)").matches) return;
    textareaRef.current?.focus();
  }, [agentName]);

  const submit = useCallback(() => {
    if (!canSend) return;
    onSend(trimmed);
    setDraft("");
    window.requestAnimationFrame(() => {
      const element = textareaRef.current;
      if (element) {
        element.style.height = "auto";
        element.focus();
      }
    });
  }, [canSend, onSend, trimmed]);

  const handleKeyDown = useCallback(
    (event) => {
      if (event.key !== "Enter" || event.shiftKey) return;
      // Do not hijack Enter while an IME candidate list is open.
      if (event.nativeEvent?.isComposing) return;
      event.preventDefault();
      submit();
    },
    [submit],
  );

  const placeholder = online
    ? `Message ${agentName}`
    : connectionState === "connecting"
      ? "Connecting\u2026"
      : "Reconnecting\u2026";

  return (
    <div className="composer">
      <div className="composer__inner">
        {notices ? <div className="composer__notices stack">{notices}</div> : null}

        <div className={cx("composer__box", !online && "is-offline")}>
          <textarea
            ref={textareaRef}
            className="composer__input"
            rows={1}
            value={draft}
            placeholder={placeholder}
            aria-label={`Message ${agentName}`}
            disabled={Boolean(disabledReason)}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={handleKeyDown}
          />

          {streaming ? (
            <button
              type="button"
              className="composer__send composer__send--stop"
              onClick={onStop}
              aria-label="Stop generating"
              title="Stop generating"
            >
              <Square size={14} aria-hidden="true" fill="currentColor" />
            </button>
          ) : (
            <button
              type="button"
              className="composer__send"
              onClick={submit}
              disabled={!canSend}
              aria-label="Send message"
              title="Send message"
            >
              <ArrowUp size={17} strokeWidth={2.6} aria-hidden="true" />
            </button>
          )}
        </div>

        <div className="composer__foot">
          <span className="composer__hint">
            <kbd>Enter</kbd> to send, <kbd>Shift</kbd> + <kbd>Enter</kbd> for a new line
          </span>
          {draft.length > COUNTER_THRESHOLD ? (
            <span className={cx("composer__count", tooLong && "is-over")}>
              {draft.length}/{MAX_MESSAGE_LENGTH}
            </span>
          ) : null}
        </div>
      </div>
    </div>
  );
}
