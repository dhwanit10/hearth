import { useCallback, useEffect, useRef, useState } from "react";

/** useState that survives reloads, guarded against private-mode failures. */
export function usePersistentState(key, initialValue) {
  const [value, setValue] = useState(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? initialValue : JSON.parse(stored);
    } catch {
      return initialValue;
    }
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
    } catch {
      /* storage unavailable - state still works for this session */
    }
  }, [key, value]);

  return [value, setValue];
}

/**
 * Coalesces a high frequency stream of text chunks into one state update per
 * animation frame. Token streams can arrive dozens of times per second; this
 * keeps typing smooth without dropping any characters.
 */
export function useStreamBuffer() {
  const pendingRef = useRef("");
  const frameRef = useRef(0);
  const [text, setText] = useState("");

  const flush = useCallback(() => {
    frameRef.current = 0;
    if (!pendingRef.current) return;
    const next = pendingRef.current;
    pendingRef.current = "";
    setText((current) => current + next);
  }, []);

  const push = useCallback(
    (chunk) => {
      if (!chunk) return;
      pendingRef.current += chunk;
      if (frameRef.current) return;
      frameRef.current = window.requestAnimationFrame(flush);
    },
    [flush],
  );

  const reset = useCallback(() => {
    pendingRef.current = "";
    if (frameRef.current) {
      window.cancelAnimationFrame(frameRef.current);
      frameRef.current = 0;
    }
    setText("");
  }, []);

  useEffect(
    () => () => {
      if (frameRef.current) window.cancelAnimationFrame(frameRef.current);
    },
    [],
  );

  return { text, push, reset };
}
