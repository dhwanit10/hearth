import { useState } from "react";
import { Flame, TriangleAlert } from "lucide-react";

import { Notice } from "./ui.jsx";

const MIN_PASSWORD = 8;
const MIN_USERNAME = 3;

/**
 * Full-screen gate shown until the visitor has a session.
 *
 * One form, two modes: sign in for returning users, create account for new
 * ones. Copy makes the BYOK deal explicit up front.
 */
export default function AuthScreen({ onSubmit, busy, error }) {
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const isSignup = mode === "signup";
  const trimmedEmail = email.trim();
  const trimmedUsername = username.trim();
  const canSubmit =
    !busy &&
    trimmedEmail.includes("@") &&
    password.length >= 1 &&
    (!isSignup || trimmedUsername.length >= MIN_USERNAME);

  const submit = (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit(mode, {
      email: trimmedEmail,
      password,
      ...(isSignup ? { username: trimmedUsername } : {}),
    });
  };

  return (
    <div className="auth">
      <div className="auth__inner">
        <div className="auth__brand">
          <span className="welcome__mark" aria-hidden="true">
            <Flame size={24} strokeWidth={1.9} />
          </span>
          <div>
            <div className="auth__brand-name">Hearth</div>
            <div className="auth__brand-tag">Companions, not assistants</div>
          </div>
        </div>

        <h1 className="auth__title">
          {isSignup ? "Create your account" : "Welcome back"}
        </h1>
        <p className="auth__lede">
          Your companions and conversations are private to your account.
        </p>

        {error ? (
          <div className="auth__notice">
            <Notice tone="error" icon={TriangleAlert} title="That did not work">
              {error}
            </Notice>
          </div>
        ) : null}

        <form className="auth__form" onSubmit={submit}>
          <div className="auth__field">
            <label className="field-label" htmlFor="auth-email">
              Email
            </label>
            <input
              id="auth-email"
              className="text-input"
              type="email"
              autoComplete="email"
              value={email}
              placeholder="you@example.com"
              onChange={(event) => setEmail(event.target.value)}
            />
          </div>

          {isSignup ? (
            <div className="auth__field">
              <label className="field-label" htmlFor="auth-username">
                Username
              </label>
              <input
                id="auth-username"
                className="text-input"
                type="text"
                autoComplete="nickname"
                value={username}
                maxLength={40}
                placeholder="What should we call you?"
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
          ) : null}

          <div className="auth__field">
            <label className="field-label" htmlFor="auth-password">
              Password
            </label>
            <input
              id="auth-password"
              className="text-input"
              type="password"
              autoComplete={isSignup ? "new-password" : "current-password"}
              value={password}
              placeholder={isSignup ? `At least ${MIN_PASSWORD} characters` : "Your password"}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>

          <button type="submit" className="button button--primary auth__submit" disabled={!canSubmit}>
            {busy
              ? "One moment\u2026"
              : isSignup
                ? "Create account"
                : "Sign in"}
          </button>
        </form>

        <p className="auth__switch">
          {isSignup ? "Already have an account?" : "New to Hearth?"}{" "}
          <button
            type="button"
            className="link-button"
            onClick={() => setMode(isSignup ? "login" : "signup")}
          >
            {isSignup ? "Sign in" : "Create one"}
          </button>
        </p>

        <p className="auth__fineprint">
          You can chat on the shared key, or add your own Gemini API key in
          Settings for unlimited companions and messages.
        </p>
      </div>
    </div>
  );
}
