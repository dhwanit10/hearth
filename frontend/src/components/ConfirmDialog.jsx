import { useEffect, useRef } from "react";
import { TriangleAlert } from "lucide-react";

import { cx } from "../lib/cx.js";

/** Small, on-brand confirmation dialog (never a native window.confirm). */
export default function ConfirmDialog({
  title,
  body,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  tone = "danger",
  busy = false,
  onConfirm,
  onCancel,
}) {
  const confirmRef = useRef(null);

  useEffect(() => {
    confirmRef.current?.focus();
    const onKeyDown = (event) => {
      if (event.key === "Escape") onCancel();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div
      className="dialog-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        className="dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-body"
        style={{ maxWidth: 420 }}
      >
        <div className="dialog__head">
          <div>
            <h2 className="dialog__title" id="confirm-title">
              {title}
            </h2>
          </div>
        </div>

        <div className="dialog__body">
          <div className={cx("notice", tone === "danger" ? "notice--error" : "notice--warn")}>
            <TriangleAlert className="notice__icon" size={16} aria-hidden="true" />
            <div className="notice__body" id="confirm-body">
              {body}
            </div>
          </div>
        </div>

        <div className="dialog__foot">
          <div className="dialog__foot-spacer" />
          <button type="button" className="button" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </button>
          <button
            type="button"
            ref={confirmRef}
            className={cx("button", tone === "danger" ? "button--danger" : "button--primary")}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? "Working\u2026" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
