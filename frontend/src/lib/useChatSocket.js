import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { chatSocketUrl } from "./api.js";

export const SocketState = {
  IDLE: "idle",
  CONNECTING: "connecting",
  ONLINE: "online",
  OFFLINE: "offline",
};

const MAX_BACKOFF = 8000;
// Server side close code for "this agent does not exist".
const CLOSE_NOT_FOUND = 4404;
// Server side close code for "your token is missing or expired".
const CLOSE_UNAUTHORIZED = 4401;

/**
 * Keeps one websocket open for the selected companion.
 *
 * - events are handed to the latest `onEvent` without re-opening the socket,
 * - drops are retried with exponential backoff (unless the agent is gone or the
 *   session expired),
 * - `send` reports whether the frame actually went out, so the UI can tell the
 *   user "reconnecting" instead of silently swallowing a message.
 */
export function useChatSocket(agentId, token, onEvent) {
  const handlerRef = useRef(onEvent);
  const socketRef = useRef(null);
  const attemptsRef = useRef(0);
  const timerRef = useRef(null);
  const [state, setState] = useState(SocketState.IDLE);

  useLayoutEffect(() => {
    handlerRef.current = onEvent;
  }, [onEvent]);

  useEffect(() => {
    if (!agentId) {
      setState(SocketState.IDLE);
      return undefined;
    }

    let disposed = false;
    attemptsRef.current = 0;

    const connect = () => {
      if (disposed) return;
      setState(SocketState.CONNECTING);

      let socket;
      try {
        socket = new WebSocket(chatSocketUrl(agentId, token));
      } catch {
        setState(SocketState.OFFLINE);
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposed) return;
        attemptsRef.current = 0;
        setState(SocketState.ONLINE);
      };

      socket.onmessage = (event) => {
        if (disposed) return;
        let payload;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        handlerRef.current?.(payload);
      };

      socket.onclose = (event) => {
        if (disposed) return;
        socketRef.current = null;

        if (event.code === CLOSE_NOT_FOUND) {
          setState(SocketState.OFFLINE);
          handlerRef.current?.({
            type: "error",
            code: "not_found",
            message: "This companion no longer exists.",
          });
          return;
        }

        if (event.code === CLOSE_UNAUTHORIZED) {
          setState(SocketState.OFFLINE);
          handlerRef.current?.({
            type: "error",
            code: "unauthorized",
            message: "Your session has expired. Please sign in again.",
          });
          return;
        }

        setState(SocketState.OFFLINE);
        const attempt = attemptsRef.current++;
        const delay = Math.min(400 * 2 ** attempt, MAX_BACKOFF);
        timerRef.current = window.setTimeout(connect, delay);
      };

      // Errors surface through onclose, so nothing to do here.
      socket.onerror = () => {};
    };

    connect();

    return () => {
      disposed = true;
      window.clearTimeout(timerRef.current);
      const socket = socketRef.current;
      socketRef.current = null;
      if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        socket.close(1000, "switching companions");
      }
    };
  }, [agentId, token]);

  const send = useCallback((payload) => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(payload));
    return true;
  }, []);

  const sendMessage = useCallback((content) => send({ type: "message", content }), [send]);
  const stop = useCallback(() => send({ type: "stop" }), [send]);

  return { state, send, sendMessage, stop };
}
