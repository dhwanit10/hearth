import { useCallback, useEffect, useMemo, useState } from "react";
import { Flame, Info, KeyRound, TriangleAlert } from "lucide-react";

import AccountDialog from "./components/AccountDialog.jsx";
import AuthScreen from "./components/AuthScreen.jsx";
import ChatHeader from "./components/ChatHeader.jsx";
import Composer from "./components/Composer.jsx";
import ConfirmDialog from "./components/ConfirmDialog.jsx";
import { StartPane, WelcomePane } from "./components/EmptyStates.jsx";
import MessageList from "./components/MessageList.jsx";
import NewAgentDialog from "./components/NewAgentDialog.jsx";
import Sidebar from "./components/Sidebar.jsx";
import { Notice } from "./components/ui.jsx";
import { api, getToken, setToken as persistToken } from "./lib/api.js";
import { cx } from "./lib/cx.js";
import { usePersistentState, useStreamBuffer } from "./lib/hooks.js";
import { useChatSocket } from "./lib/useChatSocket.js";

const THEME_KEY = "hearth.theme";
const ACTIVE_KEY = "hearth.activeAgent";
const DEMO_KEY = "hearth.demoNoticeDismissed";
const BYOK_KEY = "hearth.byokNoticeDismissed";

function initialTheme() {
  return document.documentElement.getAttribute("data-theme") === "dark" ? "dark" : "light";
}

export default function App() {
  const [theme, setTheme] = usePersistentState(THEME_KEY, initialTheme());
  const [activeId, setActiveId] = usePersistentState(ACTIVE_KEY, null);
  const [demoDismissed, setDemoDismissed] = usePersistentState(DEMO_KEY, false);
  const [byokDismissed, setByokDismissed] = usePersistentState(BYOK_KEY, false);

  const [token, setToken] = useState(() => getToken());
  const [user, setUser] = useState(null);
  const [booting, setBooting] = useState(false);
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState(null);

  const [personas, setPersonas] = useState([]);
  const [agents, setAgents] = useState([]);
  const [messages, setMessages] = useState([]);
  const [llm, setLlm] = useState(null);

  const [bootError, setBootError] = useState(null);

  const [query, setQuery] = useState("");
  const [drawerOpen, setDrawerOpen] = useState(false);

  const [dialogOpen, setDialogOpen] = useState(false);
  const [dialogPersona, setDialogPersona] = useState(null);
  const [dialogError, setDialogError] = useState(null);
  const [creating, setCreating] = useState(false);

  const [accountOpen, setAccountOpen] = useState(false);
  const [accountBusy, setAccountBusy] = useState(false);
  const [accountError, setAccountError] = useState(null);

  const [confirm, setConfirm] = useState(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  // Destructured so the callbacks stay referentially stable: they come from
  // useCallback with no dependencies, unlike the object literal around them.
  const { text: streamText, push: pushDelta, reset: resetStream } = useStreamBuffer();
  const [streamingActive, setStreamingActive] = useState(false);

  const personaMap = useMemo(
    () => Object.fromEntries(personas.map((persona) => [persona.id, persona])),
    [personas],
  );

  const activeAgent = useMemo(
    () => agents.find((agent) => agent.id === activeId) ?? null,
    [agents, activeId],
  );

  const quota = user?.quota ?? {};
  const onSharedKey = Boolean(user) && !user.has_gemini_key;
  const messagesLeft =
    quota.messages_limit == null
      ? Infinity
      : Math.max(0, quota.messages_limit - (quota.messages_used_today ?? 0));
  const outOfMessages = onSharedKey && messagesLeft <= 0;
  const atAgentLimit = onSharedKey && quota.agents_limit != null
    && (quota.agents_used ?? 0) >= quota.agents_limit;

  /* ---------------------------------------------------------------------- */
  /* Theme                                                                  */
  /* ---------------------------------------------------------------------- */

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  /* ---------------------------------------------------------------------- */
  /* Boot: session, health, personas, companions                            */
  /* ---------------------------------------------------------------------- */

  const loadAll = useCallback(async (signal) => {
    const [health, personaPayload, agentPayload] = await Promise.all([
      api.health(signal),
      api.personas(signal),
      api.listAgents(signal),
    ]);
    setLlm(health.llm);
    setPersonas(personaPayload.personas);
    setAgents(agentPayload.agents);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    if (!token) {
      setUser(null);
      setBooting(false);
      return () => controller.abort();
    }

    setBooting(true);
    (async () => {
      try {
        const me = await api.me(controller.signal);
        setUser(me.user);
        await loadAll(controller.signal);
        setBootError(null);
      } catch (error) {
        if (error?.name === "AbortError") return;
        if (error?.status === 401) {
          // The stored token is stale; drop it and fall back to the gate.
          signOutLocally();
          return;
        }
        setBootError(error.message);
      } finally {
        if (!controller.signal.aborted) setBooting(false);
      }
    })();
    return () => controller.abort();
  }, [token, loadAll]);

  const signOutLocally = useCallback(() => {
    persistToken(null);
    setToken(null);
    setUser(null);
    setAgents([]);
    setMessages([]);
    setActiveId(null);
    setAccountOpen(false);
    setBootError(null);
  }, [setActiveId]);

  // Keep a valid selection: fall back to the most recent companion.
  useEffect(() => {
    if (!user) return;
    if (activeId && agents.some((agent) => agent.id === activeId)) return;
    setActiveId(agents[0]?.id ?? null);
  }, [user, agents, activeId, setActiveId]);

  /* ---------------------------------------------------------------------- */
  /* Load the selected conversation                                         */
  /* ---------------------------------------------------------------------- */

  useEffect(() => {
    if (!activeAgent?.id) {
      setMessages([]);
      return undefined;
    }
    const controller = new AbortController();
    (async () => {
      try {
        const payload = await api.messages(activeAgent.id, { limit: 200 }, controller.signal);
        setMessages(payload.messages);
      } catch (error) {
        if (error?.name !== "AbortError") {
          setNotice({ tone: "error", title: "Could not load this conversation", body: error.message });
        }
      }
    })();
    return () => controller.abort();
  }, [activeAgent?.id]);

  /* ---------------------------------------------------------------------- */
  /* Live channel                                                           */
  /* ---------------------------------------------------------------------- */

  const handleSocketEvent = useCallback(
    (event) => {
      const agentId = event.agentId ?? activeId;

      switch (event.type) {
        case "assistant_start":
          resetStream();
          setStreamingActive(true);
          break;

        case "delta":
          pushDelta(event.content);
          break;

        case "user_message":
          setMessages((list) =>
            list.some((item) => item.id === event.message.id) ? list : [...list, event.message],
          );
          break;

        case "quota":
          setUser((current) => (current ? { ...current, quota: event.quota } : current));
          break;

        case "assistant_end": {
          setStreamingActive(false);
          resetStream();
          const message = event.message;
          if (message) {
            setMessages((list) =>
              list.some((item) => item.id === message.id) ? list : [...list, message],
            );
            setAgents((list) =>
              list.map((agent) =>
                agent.id === agentId
                  ? {
                      ...agent,
                      last_message: message.content,
                      last_message_at: message.created_at,
                      message_count: (agent.message_count ?? 0) + 1,
                    }
                  : agent,
              ),
            );
          }
          if (event.error) {
            setNotice({ tone: "error", title: "Reply interrupted", body: event.error });
          }
          break;
        }

        case "cancelled":
          setStreamingActive(false);
          resetStream();
          break;

        case "error":
          if (event.code === "not_found") {
            setAgents((list) => list.filter((agent) => agent.id !== agentId));
            setActiveId((current) => (current === agentId ? null : current));
            setNotice({ tone: "error", title: "Companion unavailable", body: event.message });
          } else if (event.code === "unauthorized") {
            signOutLocally();
          } else if (event.code === "quota_messages") {
            if (event.quota) {
              setUser((current) => (current ? { ...current, quota: event.quota } : current));
            }
            setNotice({
              tone: "warn",
              title: "Daily limit reached",
              body: event.message,
            });
          } else if (event.code === "busy") {
            setNotice({ tone: "warn", title: "One message at a time", body: event.message });
          } else {
            setNotice({ tone: "error", title: "Something went wrong", body: event.message });
          }
          break;

        default:
          break;
      }
    },
    [activeId, setActiveId, pushDelta, resetStream, signOutLocally],
  );

  const socket = useChatSocket(user ? activeAgent?.id ?? null : null, token, handleSocketEvent);

  // A fresh channel means a fresh stream. `resetStream` is stable, so this only
  // fires when the selected companion actually changes.
  useEffect(() => {
    setStreamingActive(false);
    resetStream();
  }, [activeAgent?.id, resetStream]);

  /* ---------------------------------------------------------------------- */
  /* Actions                                                                */
  /* ---------------------------------------------------------------------- */

  const handleAuth = useCallback(async (mode, payload) => {
    setAuthBusy(true);
    setAuthError(null);
    try {
      const result = mode === "signup"
        ? await api.signup(payload)
        : await api.login(payload);
      persistToken(result.token);
      setBooting(true);
      setToken(result.token);
      setUser(result.user);
    } catch (error) {
      setAuthError(error.message);
    } finally {
      setAuthBusy(false);
    }
  }, []);

  const handleLogout = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      /* the token may already be gone - signing out locally is enough */
    }
    signOutLocally();
  }, [signOutLocally]);

  const handleAccountSave = useCallback(async (payload) => {
    if (!payload || Object.keys(payload).length === 0) {
      setAccountOpen(false);
      return;
    }
    setAccountBusy(true);
    setAccountError(null);
    try {
      const result = await api.updateMe(payload);
      setUser(result.user);
      setAccountOpen(false);
    } catch (error) {
      setAccountError(error.message);
    } finally {
      setAccountBusy(false);
    }
  }, []);

  const sendMessage = useCallback(
    (content) => {
      if (outOfMessages) {
        setNotice({
          tone: "warn",
          title: "Daily limit reached",
          body: "Add your own Gemini API key in Settings to keep chatting today.",
        });
        setAccountOpen(true);
        return;
      }
      const delivered = socket.sendMessage(content);
      if (!delivered) {
        setNotice({
          tone: "warn",
          title: "Not connected",
          body: "The live channel is reconnecting. Your message was not sent - try again in a moment.",
        });
      }
    },
    [socket, outOfMessages],
  );

  const createAgent = useCallback(
    async (payload) => {
      setCreating(true);
      setDialogError(null);
      try {
        const { agent } = await api.createAgent(payload);
        setAgents((list) => [agent, ...list]);
        setActiveId(agent.id);
        setDialogOpen(false);
        setDialogPersona(null);
        setDrawerOpen(false);
        setUser((current) =>
          current
            ? { ...current, quota: { ...current.quota, agents_used: (current.quota.agents_used ?? 0) + 1 } }
            : current,
        );
      } catch (error) {
        if (error?.status === 401) {
          signOutLocally();
          return;
        }
        setDialogError(error.message);
        if (error?.code === "quota_agents") {
          setNotice({
            tone: "warn",
            title: "Companion limit reached",
            body: error.message,
          });
        }
      } finally {
        setCreating(false);
      }
    },
    [setActiveId, signOutLocally],
  );

  const runConfirm = useCallback(async () => {
    if (!confirm) return;
    setConfirmBusy(true);
    try {
      if (confirm.kind === "delete") {
        await api.deleteAgent(confirm.agent.id);
        setAgents((list) => list.filter((agent) => agent.id !== confirm.agent.id));
        setActiveId((current) => (current === confirm.agent.id ? null : current));
        setUser((current) =>
          current
            ? { ...current, quota: { ...current.quota, agents_used: Math.max(0, (current.quota.agents_used ?? 1) - 1) } }
            : current,
        );
      } else {
        await api.clearMessages(confirm.agent.id);
        setMessages([]);
        setAgents((list) =>
          list.map((agent) =>
            agent.id === confirm.agent.id
              ? { ...agent, last_message: null, last_message_at: null, message_count: 0 }
              : agent,
          ),
        );
      }
      setConfirm(null);
    } catch (error) {
      if (error?.status === 401) {
        signOutLocally();
        return;
      }
      setNotice({ tone: "error", title: "That did not work", body: error.message });
    } finally {
      setConfirmBusy(false);
    }
  }, [confirm, setActiveId, signOutLocally]);

  const openDialog = useCallback((personaId = null) => {
    if (atAgentLimit) {
      setNotice({
        tone: "warn",
        title: "Companion limit reached",
        body: `You have reached the ${quota.agents_limit}-companion limit on the shared key. Add your own Gemini API key for unlimited companions.`,
      });
      setAccountError(null);
      setAccountOpen(true);
      return;
    }
    setDialogPersona(personaId);
    setDialogError(null);
    setDialogOpen(true);
  }, [atAgentLimit, quota.agents_limit]);

  const openAccount = useCallback(() => {
    setAccountError(null);
    setAccountOpen(true);
  }, []);

  /* ---------------------------------------------------------------------- */
  /* Keyboard                                                               */
  /* ---------------------------------------------------------------------- */

  useEffect(() => {
    if (!user) return undefined;
    const onKeyDown = (event) => {
      if (event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target;
      const typing =
        target instanceof HTMLElement &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable);
      if (typing) return;

      if (event.key === "n" || event.key === "N") {
        event.preventDefault();
        openDialog(null);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [openDialog, user]);

  /* ---------------------------------------------------------------------- */
  /* Render                                                                 */
  /* ---------------------------------------------------------------------- */

  if (!token) {
    return <AuthScreen onSubmit={handleAuth} busy={authBusy} error={authError} />;
  }

  if (booting) {
    return (
      <div className="pane">
        <div className="welcome__inner">
          <span className="welcome__mark" aria-hidden="true">
            <Flame size={26} strokeWidth={1.9} />
          </span>
          <h1 className="welcome__title">Hearth</h1>
          <p className="welcome__lede">Loading your companions{"\u2026"}</p>
        </div>
      </div>
    );
  }

  if (bootError) {
    return (
      <div className="pane">
        <div className="welcome__inner" style={{ maxWidth: 460 }}>
          <h1 className="welcome__title">Backend not reachable</h1>
          <p className="welcome__lede">{bootError}</p>
          <div className="welcome__actions">
            <button
              type="button"
              className="button button--primary"
              onClick={() => {
                setBootError(null);
                setBooting(true);
                loadAll()
                  .then(() => setBooting(false))
                  .catch((error) => {
                    setBootError(error.message);
                    setBooting(false);
                  });
              }}
            >
              Try again
            </button>
            <button type="button" className="button" onClick={handleLogout}>
              Sign out
            </button>
          </div>
          <p className="field-hint" style={{ marginTop: 18 }}>
            Start it with <code>uvicorn app.main:app --reload</code> inside the
            backend folder.
          </p>
        </div>
      </div>
    );
  }

  const notices = [];

  if (notice) {
    notices.push(
      <Notice
        key="notice"
        tone={notice.tone}
        icon={TriangleAlert}
        title={notice.title}
        onDismiss={() => setNotice(null)}
      >
        {notice.body}
      </Notice>,
    );
  }

  if (onSharedKey && !byokDismissed) {
    notices.push(
      <Notice
        key="byok"
        tone="info"
        icon={KeyRound}
        title="You're on the shared key"
        onDismiss={() => setByokDismissed(true)}
      >
        <p style={{ margin: "0 0 8px" }}>
          Up to {quota.agents_limit} companions and {quota.messages_limit} messages a
          day. Add your own Gemini API key for unlimited use.
        </p>
        <button type="button" className="link-button" onClick={openAccount}>
          Add your API key
        </button>
      </Notice>,
    );
  }

  if (llm?.mode === "demo" && !demoDismissed) {
    notices.push(
      <Notice
        key="demo"
        tone="info"
        icon={Info}
        title="Demo mode"
        onDismiss={() => setDemoDismissed(true)}
      >
        {llm.notice}
      </Notice>,
    );
  }

  return (
    <div className={cx("app", drawerOpen && "is-drawer-open")}>
      <Sidebar
        agents={agents}
        personaMap={personaMap}
        activeId={activeAgent?.id ?? null}
        onSelect={(id) => {
          setActiveId(id);
          setDrawerOpen(false);
          setNotice(null);
        }}
        onNew={() => openDialog(null)}
        onDelete={(id) => {
          const agent = agents.find((item) => item.id === id);
          if (agent) setConfirm({ kind: "delete", agent });
        }}
        query={query}
        onQueryChange={setQuery}
        theme={theme}
        onThemeChange={setTheme}
        socketState={socket.state}
        llm={llm}
        user={user}
        onOpenAccount={openAccount}
        onCloseDrawer={() => setDrawerOpen(false)}
      />

      {drawerOpen ? (
        <div
          className="sidebar-scrim"
          role="presentation"
          onClick={() => setDrawerOpen(false)}
        />
      ) : null}

      <main className="app__body">
        {activeAgent ? (
          <>
            <ChatHeader
              agent={activeAgent}
              persona={personaMap[activeAgent.persona]}
              socketState={socket.state}
              messageCount={messages.length}
              onClearConversation={() =>
                setConfirm({ kind: "clear", agent: activeAgent })
              }
              onDeleteAgent={() => setConfirm({ kind: "delete", agent: activeAgent })}
              onOpenDrawer={() => setDrawerOpen(true)}
            />

            {messages.length === 0 && !streamingActive ? (
              <StartPane
                agent={activeAgent}
                persona={personaMap[activeAgent.persona]}
                starters={personaMap[activeAgent.persona]?.starters}
                onStarter={sendMessage}
              />
            ) : (
              <MessageList
                key={activeAgent.id}
                messages={messages}
                agent={activeAgent}
                streaming={{ active: streamingActive, text: streamText }}
              />
            )}

            <Composer
              agentName={activeAgent.name}
              onSend={sendMessage}
              onStop={socket.stop}
              streaming={streamingActive}
              connectionState={socket.state}
              notices={notices}
            />
          </>
        ) : (
          <WelcomePane
            personas={personas}
            onNew={() => openDialog(null)}
            onQuickStart={(personaId) => openDialog(personaId)}
          />
        )}
      </main>

      {dialogOpen ? (
        <NewAgentDialog
          personas={personas}
          initialPersona={dialogPersona ?? undefined}
          creating={creating}
          error={dialogError}
          onSubmit={createAgent}
          onClose={() => {
            setDialogOpen(false);
            setDialogPersona(null);
            setDialogError(null);
          }}
        />
      ) : null}

      {accountOpen ? (
        <AccountDialog
          user={user}
          busy={accountBusy}
          error={accountError}
          onSave={handleAccountSave}
          onLogout={handleLogout}
          onClose={() => {
            setAccountOpen(false);
            setAccountError(null);
          }}
        />
      ) : null}

      {confirm ? (
        <ConfirmDialog
          title={confirm.kind === "delete" ? "Delete this companion?" : "Clear the conversation?"}
          body={
            confirm.kind === "delete"
              ? `${confirm.agent.name} and the entire conversation history will be permanently removed from the database. This cannot be undone.`
              : `Every message with ${confirm.agent.name} will be deleted. The companion itself stays, with an empty history.`
          }
          confirmLabel={confirm.kind === "delete" ? "Delete companion" : "Clear conversation"}
          tone={confirm.kind === "delete" ? "danger" : "primary"}
          busy={confirmBusy}
          onConfirm={runConfirm}
          onCancel={() => setConfirm(null)}
        />
      ) : null}
    </div>
  );
}
