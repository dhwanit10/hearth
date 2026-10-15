import { useEffect, useRef, useState } from "react";
import { Eraser, Menu, MoreHorizontal, Trash2 } from "lucide-react";

import Avatar from "./Avatar.jsx";
import { IconButton, StatusDot } from "./ui.jsx";

function useDismissable(onDismiss) {
  const ref = useRef(null);

  useEffect(() => {
    const onPointerDown = (event) => {
      if (ref.current && !ref.current.contains(event.target)) onDismiss();
    };
    const onKeyDown = (event) => {
      if (event.key === "Escape") onDismiss();
    };
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onDismiss]);

  return ref;
}

export default function ChatHeader({
  agent,
  persona,
  socketState,
  messageCount,
  onClearConversation,
  onDeleteAgent,
  onOpenDrawer,
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useDismissable(() => setMenuOpen(false));

  const statusLabel =
    socketState === "online"
      ? "Live"
      : socketState === "connecting"
        ? "Connecting"
        : "Offline";

  return (
    <header className="chat-header">
      <IconButton label="Open companions" className="mobile-only" onClick={onOpenDrawer}>
        <Menu size={18} aria-hidden="true" />
      </IconButton>

      <Avatar name={agent.name} accent={agent.accent} size="md" />

      <div className="chat-header__body">
        <div className="chat-header__name">
          {agent.name}
          <StatusDot status={socketState} />
        </div>
        <div className="chat-header__sub">
          {persona?.tagline ?? agent.tagline}
          {messageCount > 0 ? ` \u00b7 ${messageCount} messages` : ""}
          {` \u00b7 ${statusLabel}`}
        </div>
      </div>

      <div className="chat-header__actions">
        <div className="menu" ref={menuRef}>
          <IconButton
            label="More options"
            aria-expanded={menuOpen}
            aria-haspopup="menu"
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MoreHorizontal size={18} aria-hidden="true" />
          </IconButton>

          {menuOpen ? (
            <div className="menu__panel" role="menu">
              <button
                type="button"
                role="menuitem"
                className="menu__item"
                onClick={() => {
                  setMenuOpen(false);
                  onClearConversation();
                }}
              >
                <Eraser size={15} aria-hidden="true" />
                Clear conversation
              </button>
              <div className="menu__sep" />
              <button
                type="button"
                role="menuitem"
                className="menu__item menu__item--danger"
                onClick={() => {
                  setMenuOpen(false);
                  onDeleteAgent();
                }}
              >
                <Trash2 size={15} aria-hidden="true" />
                Delete companion
              </button>
              <p className="menu__hint">
                Deleting removes {agent.name} and the entire conversation from
                the database.
              </p>
            </div>
          ) : null}
        </div>
      </div>
    </header>
  );
}
