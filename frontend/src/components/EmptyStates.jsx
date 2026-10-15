import { ArrowRight, Flame, Plus } from "lucide-react";

import Avatar from "./Avatar.jsx";
import { personaIcon } from "./personaIcons.js";

/** Shown when no companion is selected. */
export function WelcomePane({ personas, onNew, onQuickStart }) {
  return (
    <div className="welcome">
      <div className="welcome__inner">
        <span className="welcome__mark" aria-hidden="true">
          <Flame size={26} strokeWidth={1.9} />
        </span>
        <h1 className="welcome__title">
          Pick a companion,
          <br />
          or invent one.
        </h1>
        <p className="welcome__lede">
          Every companion has its own name, voice and memory. Conversations are
          stored locally, so they pick up exactly where you left off.
        </p>

        <div className="welcome__actions">
          <button type="button" className="button button--primary" onClick={onNew}>
            <Plus size={16} aria-hidden="true" />
            New companion
          </button>
        </div>

        <div className="welcome__grid">
          {personas.map((persona) => {
            const Icon = personaIcon(persona.id);
            return (
              <button
                type="button"
                key={persona.id}
                className="welcome__card"
                onClick={() => onQuickStart(persona.id)}
              >
                <span className="welcome__card-label">
                  <Icon size={15} aria-hidden="true" />
                  {persona.label}
                  <ArrowRight size={13} style={{ marginLeft: "auto" }} aria-hidden="true" />
                </span>
                <span className="welcome__card-tag">{persona.tagline}</span>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/** Shown inside a companion that has no messages yet. */
export function StartPane({ agent, persona, starters, onStarter }) {
  const Icon = personaIcon(agent.persona);
  const list = (starters ?? persona?.starters ?? []).slice(0, 4);

  return (
    <div className="start scroll-area">
      <div className="start__inner">
        <Avatar name={agent.name} accent={agent.accent} size="lg" />
        <h2 className="start__title">
          <Icon size={17} aria-hidden="true" style={{ verticalAlign: "-3px", marginRight: 8 }} />
          {agent.name}
        </h2>
        <p className="start__desc">{persona?.description ?? agent.tagline}</p>

        {persona?.traits?.length ? (
          <div className="traits">
            {persona.traits.map((trait) => (
              <span className="trait" key={trait}>
                {trait}
              </span>
            ))}
          </div>
        ) : null}

        {list.length ? (
          <div className="chips">
            {list.map((starter) => (
              <button
                type="button"
                key={starter}
                className="chip"
                onClick={() => onStarter(starter)}
              >
                {starter}
              </button>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  );
}
