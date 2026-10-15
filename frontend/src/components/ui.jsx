import { X } from "lucide-react";

import { cx } from "../lib/cx.js";

/**
 * Square icon-only button. The label doubles as the accessible name and the
 * native tooltip, so every control in the app is keyboard and screen-reader
 * navigable without any custom tooltip plumbing.
 */
export function IconButton({
  label,
  children,
  size = "md",
  tone = "default",
  className,
  ...rest
}) {
  return (
    <button
      type="button"
      className={cx(
        "icon-button",
        size === "sm" && "icon-button--sm",
        tone === "danger" && "is-danger",
        className,
      )}
      aria-label={label}
      title={label}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Inline banner used for errors, warnings and demo-mode notices. */
export function Notice({ tone = "info", icon: Icon, title, children, onDismiss }) {
  return (
    <div
      className={cx("notice", tone === "warn" && "notice--warn", tone === "error" && "notice--error")}
      role={tone === "error" ? "alert" : "status"}
    >
      {Icon ? <Icon className="notice__icon" size={16} strokeWidth={2} aria-hidden="true" /> : null}
      <div className="notice__body">
        {title ? <div className="notice__title">{title}</div> : null}
        {children ? <div>{children}</div> : null}
      </div>
      {onDismiss ? (
        <IconButton label="Dismiss" size="sm" onClick={onDismiss} className="notice__close">
          <X size={14} aria-hidden="true" />
        </IconButton>
      ) : null}
    </div>
  );
}

/** Small dot + text used for websocket and LLM status. */
export function StatusDot({ status = "idle", label }) {
  const cls =
    status === "online" ? "is-live" : status === "connecting" ? "is-busy" : status === "offline" ? "is-down" : "";
  return (
    <span className="status-dot-wrap" style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
      <span className={cx("status-dot", cls)} aria-hidden="true" />
      {label ? <span className="status-text">{label}</span> : null}
    </span>
  );
}
