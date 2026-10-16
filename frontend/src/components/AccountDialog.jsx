import { useState } from "react";
import { ExternalLink, KeyRound, LogOut, TriangleAlert, X } from "lucide-react";

import { cx } from "../lib/cx.js";
import { IconButton, Notice } from "./ui.jsx";

const MIN_PASSWORD = 8;

function Meter({ label, used, limit }) {
  const pct = limit ? Math.min(100, Math.round((used / limit) * 100)) : 0;
  const full = limit != null && used >= limit;
  return (
    <div className="quota">
      <div className="quota__row">
        <span>{label}</span>
        <span className={cx("quota__value", full && "is-full")}>
          {limit == null ? "Unlimited" : `${used} / ${limit}`}
        </span>
      </div>
      {limit == null ? null : (
        <div className="quota__track" aria-hidden="true">
          <span className={cx("quota__fill", full && "is-full")} style={{ width: `${pct}%` }} />
        </div>
      )}
    </div>
  );
}

/**
 * Account settings: display name, bring-your-own-key, password and logout.
 *
 * The Gemini key field starts empty on purpose - the server never sends the key
 * back, so an empty field means "leave it as it is".
 */
export default function AccountDialog({
  user,
  busy,
  error,
  onSave,
  onLogout,
  onClose,
}) {
  const [username, setUsername] = useState(user?.username ?? "");
  const [apiKey, setApiKey] = useState("");
  const [clearKey, setClearKey] = useState(false);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");

  const quota = user?.quota ?? {};
  const hasKey = Boolean(user?.has_gemini_key) && !clearKey;

  const passwordTouched = newPassword.length > 0;
  const passwordOk = !passwordTouched || newPassword.length >= MIN_PASSWORD;
  const canSubmit = !busy && passwordOk && username.trim().length >= 3;

  const submit = (event) => {
    event.preventDefault();
    if (!canSubmit) return;

    const payload = {};
    if (username.trim() !== user?.username) payload.username = username.trim();
    if (clearKey) payload.gemini_api_key = "";
    else if (apiKey.trim()) payload.gemini_api_key = apiKey.trim();
    if (passwordTouched) {
      payload.current_password = currentPassword;
      payload.new_password = newPassword;
    }
    onSave(payload);
  };

  return (
    <div
      className="dialog-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="account-title"
        onSubmit={submit}
      >
        <div className="dialog__head">
          <div>
            <h2 className="dialog__title" id="account-title">
              Your account
            </h2>
            <p className="dialog__sub">{user?.email}</p>
          </div>
          <IconButton label="Close" onClick={onClose} disabled={busy}>
            <X size={17} aria-hidden="true" />
          </IconButton>
        </div>

        <div className="dialog__body">
          {error ? (
            <div style={{ marginBottom: 16 }}>
              <Notice tone="error" icon={TriangleAlert} title="Could not save">
                {error}
              </Notice>
            </div>
          ) : null}

          <div className="dialog__section">
            <span className="field-label">Usage</span>
            <div className="quota-panel">
              <Meter
                label="Messages today"
                used={quota.messages_used_today ?? 0}
                limit={quota.messages_limit ?? null}
              />
              <Meter
                label="Companions"
                used={quota.agents_used ?? 0}
                limit={quota.agents_limit ?? null}
              />
            </div>
          </div>

          <div className="dialog__section">
            <label className="field-label" htmlFor="account-username">
              Username
            </label>
            <input
              id="account-username"
              className="text-input"
              value={username}
              maxLength={40}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>

          <div className="dialog__section">
            <span className="field-label">
              <KeyRound size={13} aria-hidden="true" style={{ verticalAlign: "-2px", marginRight: 6 }} />
              Your Gemini API key
            </span>

            <p className="field-hint" style={{ marginTop: 0 }}>
              {hasKey ? (
                "Your own key is active - unlimited companions and messages."
              ) : (
                "On the shared key. Add your own for unlimited companions and messages."
              )}
            </p>

            <input
              id="account-key"
              className="text-input"
              type="password"
              autoComplete="off"
              value={apiKey}
              placeholder={user?.has_gemini_key ? "Replace your saved key" : "AIza\u2026"}
              disabled={clearKey}
              onChange={(event) => setApiKey(event.target.value)}
            />

            <div className="field-row">
              <a
                className="field-link"
                href="https://aistudio.google.com/apikey"
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={12} aria-hidden="true" />
                Get a key from Google AI Studio
              </a>

              {user?.has_gemini_key ? (
                <button
                  type="button"
                  className="link-button"
                  onClick={() => {
                    setClearKey((value) => !value);
                    setApiKey("");
                  }}
                >
                  {clearKey ? "Keep my key" : "Remove key"}
                </button>
              ) : null}
            </div>

            {clearKey ? (
              <p className="field-hint is-warn">
                Saving now removes your key and returns you to the shared limits.
              </p>
            ) : null}
          </div>

          <div className="dialog__section">
            <span className="field-label">Change password</span>
            <div className="field-stack">
              <input
                className="text-input"
                type="password"
                autoComplete="current-password"
                value={currentPassword}
                placeholder="Current password"
                onChange={(event) => setCurrentPassword(event.target.value)}
              />
              <input
                className="text-input"
                type="password"
                autoComplete="new-password"
                value={newPassword}
                placeholder={`New password (at least ${MIN_PASSWORD} characters)`}
                onChange={(event) => setNewPassword(event.target.value)}
              />
            </div>
            <p className="field-hint">
              {passwordTouched && !passwordOk
                ? `New password must be at least ${MIN_PASSWORD} characters.`
                : "Fill this in only if you want to change your password."}
            </p>
          </div>
        </div>

        <div className="dialog__foot">
          <button
            type="button"
            className="button button--ghost"
            onClick={onLogout}
            disabled={busy}
          >
            <LogOut size={14} aria-hidden="true" />
            Sign out
          </button>
          <div className="dialog__foot-spacer" />
          <button type="button" className="button" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button type="submit" className="button button--primary" disabled={!canSubmit}>
            {busy ? "Saving\u2026" : "Save changes"}
          </button>
        </div>
      </form>
    </div>
  );
}
