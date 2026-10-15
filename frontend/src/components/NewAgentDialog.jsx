import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Check, Shuffle, TriangleAlert, X } from "lucide-react";

import { ACCENTS } from "../lib/accents.js";
import { api } from "../lib/api.js";
import { cx } from "../lib/cx.js";
import { personaIcon } from "./personaIcons.js";
import { IconButton, Notice } from "./ui.jsx";

const MIN_BRIEF = 12;

/**
 * "New companion" dialog: pick an archetype, name it (or shuffle until one
 * fits), and for the custom archetype write the character brief.
 */
export default function NewAgentDialog({
  personas,
  initialPersona,
  creating,
  error,
  onSubmit,
  onClose,
}) {
  const [personaId, setPersonaId] = useState(initialPersona ?? personas[0]?.id ?? "best_friend");
  const [name, setName] = useState("");
  const [brief, setBrief] = useState("");
  const [accent, setAccent] = useState(null);
  const [suggestions, setSuggestions] = useState([]);
  const [loadingNames, setLoadingNames] = useState(false);
  const nameRef = useRef(null);

  const persona = useMemo(
    () => personas.find((item) => item.id === personaId),
    [personas, personaId],
  );

  const loadNames = useCallback(
    async (targetPersona, { apply = false } = {}) => {
      setLoadingNames(true);
      try {
        const payload = await api.nameSuggestions(targetPersona, 4);
        const names = payload.names ?? [];
        setSuggestions(names);
        if (apply && names.length) setName(names[0]);
      } catch {
        setSuggestions([]);
      } finally {
        setLoadingNames(false);
      }
    },
    [],
  );

  // Load a fresh batch of names whenever the archetype changes.
  useEffect(() => {
    loadNames(personaId, { apply: true });
  }, [personaId, loadNames]);

  useEffect(() => {
    nameRef.current?.focus();
    nameRef.current?.select();
  }, [personaId]);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape" && !creating) onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [creating, onClose]);

  const needsBrief = Boolean(persona?.custom);
  const briefTooShort = needsBrief && brief.trim().length < MIN_BRIEF;
  const canSubmit = !creating && !briefTooShort;

  const submit = (event) => {
    event.preventDefault();
    if (!canSubmit) return;
    onSubmit({
      persona: personaId,
      name: name.trim() || undefined,
      custom_prompt: needsBrief ? brief.trim() : "",
      accent: accent ?? undefined,
    });
  };

  return (
    <div
      className="dialog-scrim"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !creating) onClose();
      }}
    >
      <form
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-agent-title"
        onSubmit={submit}
      >
        <div className="dialog__head">
          <div>
            <h2 className="dialog__title" id="new-agent-title">
              New companion
            </h2>
            <p className="dialog__sub">
              Choose who they are. You can rename or rewrite them later.
            </p>
          </div>
          <IconButton label="Close" onClick={onClose} className="mobile-only" disabled={creating}>
            <X size={17} aria-hidden="true" />
          </IconButton>
        </div>

        <div className="dialog__body">
          {error ? (
            <div style={{ marginBottom: 16 }}>
              <Notice tone="error" icon={TriangleAlert} title="Could not create that companion">
                {error}
              </Notice>
            </div>
          ) : null}

          <div className="dialog__section">
            <span className="field-label">Personality</span>
            <div className="persona-grid">
              {personas.map((item) => {
                const Icon = personaIcon(item.id);
                const selected = item.id === personaId;
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={cx("persona-card", selected && "is-selected")}
                    aria-pressed={selected}
                    onClick={() => setPersonaId(item.id)}
                  >
                    <span className="persona-card__label">
                      <Icon size={15} aria-hidden="true" />
                      {item.label}
                      {selected ? <Check className="persona-card__check" size={14} aria-hidden="true" /> : null}
                    </span>
                    <span className="persona-card__tag">{item.tagline}</span>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="dialog__section">
            <label className="field-label" htmlFor="companion-name">
              Name
            </label>
            <div className="name-row">
              <input
                id="companion-name"
                ref={nameRef}
                className="text-input"
                value={name}
                maxLength={40}
                placeholder={suggestions[0] ?? "Give them a name"}
                onChange={(event) => setName(event.target.value)}
              />
              <IconButton
                label="Shuffle name"
                onClick={() => {
                  if (suggestions.length > 1) {
                    const next = suggestions.find((item) => item !== name) ?? suggestions[0];
                    setName(next);
                  } else {
                    loadNames(personaId, { apply: true });
                  }
                }}
                disabled={loadingNames}
              >
                <Shuffle size={16} aria-hidden="true" />
              </IconButton>
            </div>

            {suggestions.length > 1 ? (
              <div className="name-suggestions">
                {suggestions
                  .filter((item) => item !== name)
                  .slice(0, 3)
                  .map((item) => (
                    <button
                      type="button"
                      key={item}
                      className="name-suggestion"
                      onClick={() => setName(item)}
                    >
                      {item}
                    </button>
                  ))}
              </div>
            ) : null}

            <p className="field-hint">
              Leave it blank and Hearth will pick one at random.
            </p>
          </div>

          {needsBrief ? (
            <div className="dialog__section">
              <label className="field-label" htmlFor="companion-brief">
                Character brief
              </label>
              <textarea
                id="companion-brief"
                className="text-area"
                value={brief}
                maxLength={4000}
                placeholder="A retired ship's navigator who answers everything with a sea metaphor, is endlessly patient, and calls me captain."
                onChange={(event) => setBrief(event.target.value)}
              />
              <p className="field-hint">
                {briefTooShort
                  ? `Describe who they are and how they talk (at least ${MIN_BRIEF} characters).`
                  : `${brief.trim().length}/4000 characters. This becomes their whole personality.`}
              </p>
            </div>
          ) : null}

          <div className="dialog__section">
            <span className="field-label">Accent</span>
            <div className="swatches">
              <button
                type="button"
                className={cx("swatch", accent === null && "is-selected")}
                style={{ "--swatch": "var(--text-3)", "--swatch-soft": "var(--surface-2)" }}
                aria-label="Automatic accent"
                aria-pressed={accent === null}
                title="Automatic"
                onClick={() => setAccent(null)}
              >
                <span className="swatch__dot" style={{ background: "var(--text-3)" }} />
              </button>

              {ACCENTS.map((item) => (
                <button
                  type="button"
                  key={item.key}
                  className={cx("swatch", accent === item.key && "is-selected")}
                  style={{
                    "--swatch": `var(--accent-${item.key})`,
                    "--swatch-soft": `var(--accent-${item.key}-soft)`,
                  }}
                  aria-label={item.label}
                  aria-pressed={accent === item.key}
                  title={item.label}
                  onClick={() => setAccent(item.key)}
                >
                  <span className="swatch__dot" style={{ background: `var(--accent-${item.key})` }} />
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="dialog__foot">
          <div className="dialog__foot-spacer" />
          <button type="button" className="button" onClick={onClose} disabled={creating}>
            Cancel
          </button>
          <button type="submit" className="button button--primary" disabled={!canSubmit}>
            {creating ? "Creating\u2026" : "Create companion"}
          </button>
        </div>
      </form>
    </div>
  );
}
