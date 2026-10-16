/**
 * Auth surface tests: the sign-in gate, the account dialog and the token
 * plumbing that carries the session over REST and WebSocket.
 */

import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";

import App from "../src/App.jsx";
import AccountDialog from "../src/components/AccountDialog.jsx";
import AuthScreen from "../src/components/AuthScreen.jsx";
import { chatSocketUrl, getToken, setToken } from "../src/lib/api.js";

describe("sign-in gate", () => {
  it("greets a returning visitor and offers account creation", () => {
    const html = renderToStaticMarkup(
      <AuthScreen onSubmit={() => {}} busy={false} error={null} />,
    );
    expect(html).toContain("Welcome back");
    expect(html).toContain("you@example.com");
    expect(html).toContain("Create one");
    expect(html).toContain("shared key");
  });

  it("is what an unauthenticated app renders", () => {
    window.localStorage.clear();
    const html = renderToStaticMarkup(<App />);
    expect(html).toContain("Welcome back");
    expect(html).not.toContain("New companion");
  });
});

describe("account dialog", () => {
  const user = {
    email: "nova@example.com",
    username: "Nova",
    has_gemini_key: false,
    quota: {
      unlimited: false,
      agents_used: 1,
      agents_limit: 3,
      messages_used_today: 4,
      messages_limit: 10,
    },
  };

  it("shows usage and nudges toward a personal key", () => {
    const html = renderToStaticMarkup(
      <AccountDialog
        user={user}
        busy={false}
        error={null}
        onSave={() => {}}
        onLogout={() => {}}
        onClose={() => {}}
      />,
    );
    expect(html).toContain("4 / 10");
    expect(html).toContain("1 / 3");
    expect(html).toContain("Add your own for unlimited");
    expect(html).toContain("Sign out");
  });

  it("reports an active personal key as unlimited", () => {
    const html = renderToStaticMarkup(
      <AccountDialog
        user={{
          ...user,
          has_gemini_key: true,
          quota: { ...user.quota, unlimited: true, agents_limit: null, messages_limit: null },
        }}
        busy={false}
        error={null}
        onSave={() => {}}
        onLogout={() => {}}
        onClose={() => {}}
      />,
    );
    expect(html).toContain("unlimited companions and messages");
    expect(html).toContain("Unlimited");
  });
});

describe("session token plumbing", () => {
  it("round-trips the token and puts it on the websocket URL", () => {
    setToken("abc123");
    expect(getToken()).toBe("abc123");

    const url = chatSocketUrl("agent-1", "abc123");
    expect(url).toContain("/ws/chat/agent-1");
    expect(url).toContain("token=abc123");

    setToken(null);
    expect(getToken()).toBeNull();
    expect(chatSocketUrl("agent-1", null)).not.toContain("token=");
  });
});
