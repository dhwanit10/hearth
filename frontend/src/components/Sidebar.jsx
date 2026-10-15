import { useMemo, useState } from "react";
import { Flame, MessageSquare, Moon, Plus, Search, Sun, Trash2, X } from "lucide-react";

import { accentStyle } from "../lib/accents.js";
import { cx } from "../lib/cx.js";
import { previewText, relativeTime } from "../lib/time.js";
import Avatar from "./Avatar.jsx";
import { IconButton, StatusDot } from "./ui.jsx";

function AgentRow({ agent, personaLabel, active, onSelect, onDelete }) {
  const [confirming, setConfirming] = useState(false);

  const handleKeyDown = (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect(agent.id);
    }
  };

  return (
    <div
      className={cx("agent-row", active && "is-active")}
      style={accentStyle(agent.accent)}
      role="button"
      tabIndex={0}
      aria-current={active ? "true" : undefined}
      onClick={() => onSelect(agent.id)}
      onKeyDown={handleKeyDown}
      title={agent.name}
    >
      <Avatar name={agent.name} accent={agent.accent} size="sm" />

      <div className="agent-row__body">
        <div className="agent-row__top">
          <span className="agent-row__name">{agent.name}</span>
          <span className="agent-row__time">
            {relativeTime(agent.last_message_at || agent.created_at)}
          </span>
        </div>
        <div className="agent-row__meta">
          <span className="agent-row__persona">{personaLabel}</span>
        </div>
        <div className="agent-row__preview">
          {agent.last_message ? previewText(agent.last_message, 70) : "No messages yet"}
        </div>
      </div>

      <div className="agent-row__actions" onClick={(event) => event.stopPropagation()}>
        {confirming ? (
          <>
            <IconButton
              label={`Delete ${agent.name} and its history`}
              size="sm"
              tone="danger"
              onClick={() => onDelete(agent.id)}
            >
              <Trash2 size={14} aria-hidden="true" />
            </IconButton>
            <IconButton label="Cancel" size="sm" onClick={() => setConfirming(false)}>
              <X size={14} aria-hidden="true" />
            </IconButton>
          </>
        ) : (
          <IconButton
            label={`Delete ${agent.name}`}
            size="sm"
            onClick={() => setConfirming(true)}
          >
            <Trash2 size={14} aria-hidden="true" />
          </IconButton>
        )}
      </div>
    </div>
  );
}

export default function Sidebar({
  agents,
  personaMap,
  activeId,
  onSelect,
  onNew,
  onDelete,
  query,
  onQueryChange,
  theme,
  onThemeChange,
  socketState,
  llm,
  onCloseDrawer,
}) {
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return agents;
    return agents.filter((agent) => {
      const label = personaMap[agent.persona]?.label ?? agent.persona;
      return `${agent.name} ${label}`.toLowerCase().includes(needle);
    });
  }, [agents, query, personaMap]);

  const connectionLabel =
    socketState === "online"
      ? "Live"
      : socketState === "connecting"
        ? "Connecting"
        : socketState === "offline"
          ? "Disconnected"
          : "Ready";

  return (
    <aside className="sidebar" aria-label="Companions">
      <div className="sidebar__head">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            <Flame size={18} strokeWidth={2} />
          </span>
          <div className="brand__text">
            <div className="brand__name">Hearth</div>
            <div className="brand__tag">Companions, not assistants</div>
          </div>
          <IconButton
            label="Close menu"
            className="mobile-only"
            onClick={onCloseDrawer}
          >
            <X size={17} aria-hidden="true" />
          </IconButton>
        </div>

        <button type="button" className="button new-button" onClick={onNew}>
          <Plus size={16} aria-hidden="true" />
          New companion
          <kbd className="new-button__kbd">N</kbd>
        </button>

        <div className="search">
          <Search className="search__icon" size={15} aria-hidden="true" />
          <input
            className="search__input"
            type="search"
            value={query}
            placeholder="Search companions"
            aria-label="Search companions"
            onChange={(event) => onQueryChange(event.target.value)}
          />
          {query ? (
            <IconButton
              label="Clear search"
              size="sm"
              className="search__clear"
              onClick={() => onQueryChange("")}
            >
              <X size={13} aria-hidden="true" />
            </IconButton>
          ) : null}
        </div>
      </div>

      <div className="sidebar__section">
        <span className="sidebar__section-title">Companions</span>
        <span className="status-text">
          {filtered.length}/{agents.length}
        </span>
      </div>

      <div className="sidebar__list scroll-area" role="list">
        {filtered.map((agent) => (
          <div role="listitem" key={agent.id}>
            <AgentRow
              agent={agent}
              personaLabel={personaMap[agent.persona]?.label ?? agent.persona}
              active={agent.id === activeId}
              onSelect={onSelect}
              onDelete={onDelete}
            />
          </div>
        ))}

        {agents.length === 0 ? (
          <p className="sidebar__empty">
            No companions yet. Create one and give it a personality - a friend,
            a partner, a teacher, or something entirely your own.
          </p>
        ) : null}

        {agents.length > 0 && filtered.length === 0 ? (
          <p className="sidebar__empty">Nothing matches “{query}”.</p>
        ) : null}
      </div>

      <div className="sidebar__foot">
        <div className="theme-toggle" role="group" aria-label="Colour theme">
          <button
            type="button"
            className={cx("theme-toggle__option", theme === "light" && "is-active")}
            aria-label="Light theme"
            aria-pressed={theme === "light"}
            title="Light theme"
            onClick={() => onThemeChange("light")}
          >
            <Sun size={15} aria-hidden="true" />
          </button>
          <button
            type="button"
            className={cx("theme-toggle__option", theme === "dark" && "is-active")}
            aria-label="Dark theme"
            aria-pressed={theme === "dark"}
            title="Dark theme"
            onClick={() => onThemeChange("dark")}
          >
            <Moon size={15} aria-hidden="true" />
          </button>
        </div>

        <div className="sidebar__foot-meta">
          <StatusDot status={socketState} label={connectionLabel} />
          {llm?.mode === "demo" ? (
            <span className="pill" title="No GEMINI_API_KEY set - replies come from the offline engine.">
              Demo
            </span>
          ) : (
            <span className="pill" title={llm?.model ? `Model: ${llm.model}` : undefined}>
              <MessageSquare size={11} aria-hidden="true" />
              {llm?.model ? llm.model.replace(/^gemini-/, "") : "Gemini"}
            </span>
          )}
        </div>
      </div>
    </aside>
  );
}
