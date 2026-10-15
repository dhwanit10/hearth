# Hearth - frontend

React + Vite UI for the Hearth companion chat. One screen, two themes, no
shadows, no emoji, and not a single cold colour.

## Setup

```powershell
npm install
npm run dev        # http://localhost:5173
```

The dev server proxies `/api` and `/ws` to `http://127.0.0.1:8000`
(`VITE_PROXY_TARGET` overrides it), so the browser only ever talks to one origin
and there is no CORS or preflight handling in the app code.

| Script | Does |
| --- | --- |
| `npm run dev` | Dev server with proxy and HMR |
| `npm run build` | Production bundle into `dist/` |
| `npm run preview` | Serve the built bundle on port 4173 |
| `npm test` | Vitest (render, markdown, time, palette guard) |

> Vite binds to `localhost`, which resolves to IPv6 first on some Windows
> machines. Use <http://localhost:5173> rather than `127.0.0.1`.

## Design system

Everything lives in `src/styles.css`. There is no CSS framework and no styling
dependency.

### The palette rule

The brief was strict: **no blue, violet, purple, green or pink anywhere.** What
is left is the warm arc of the colour wheel - red, terracotta, orange, amber,
gold - over warm neutral surfaces.

| Token | Light | Dark | Role |
| --- | --- | --- | --- |
| `--bg` | `#f7f4ef` | `#141110` | App background, sidebar |
| `--surface` | `#ffffff` | `#1b1715` | Panels, chat canvas, bubbles in |
| `--surface-2` | `#f2ede5` | `#251f1b` | Incoming bubbles, hovers, chips |
| `--surface-3` | `#e8e1d6` | `#2e2723` | Pressed states, inline code |
| `--border` / `--border-strong` | `#e4ddd1` / `#cfc5b6` | `#2e2823` / `#453b34` | Hairlines and emphasis |
| `--text` / `--text-2` / `--text-3` | `#1b1917` / `#57534e` / `#8a8178` | `#f3eee7` / `#b3a99d` / `#82786c` | Foreground ramp |
| `--accent` | `#c2410c` | `#e8834a` | Brand, user bubbles, send button |

Each companion gets a tint from eight warm accents (`clay`, `amber`, `rust`,
`ember`, `gold`, `cocoa`, `chestnut`, `graphite`), defined per theme as
`--accent-<key>` and `--accent-<key>-soft`. `Avatar.jsx` points `--agent` and
`--agent-soft` at one pair via inline style, so a single component serves every
companion in both themes.

The user's own bubbles are a solid accent block with `--on-accent` text
(contrast 5.0:1 light, 8:1 dark); incoming bubbles are a warm surface with a
hairline border. That alone tells you who said what, with no avatars needed on
the right-hand side.

### Depth without shadows

There is not a single `box-shadow` in the stylesheet, and a test enforces it.
Hierarchy comes from layering (`--bg` behind `--surface`), 1px borders, and
contrast between the accent soft-fill and its line colour. Dialog scrims use a
translucent warm overlay with a light blur.

### Type and motion

- UI text: the system sans stack. Brand and large headings: a serif
  (`--font-serif`) for a warmer, editorial feel.
- Motion is short (120-200ms) and eased; messages rise 5px on entry, the caret
  blinks, the typing indicator is three bouncing dots drawn with spans.
- `prefers-reduced-motion: reduce` collapses every animation.

### Icons

All iconography is `lucide-react`. No emoji is used anywhere in the UI or in the
icon layer. Icon-only buttons always carry both `aria-label` and `title`, so they
are screen-reader named and get a native tooltip for free.

## Structure

```
src/
├─ App.jsx                    State owner: data loading, socket wiring, dialogs
├─ main.jsx                   Entry point
├─ styles.css                 Tokens, layout, all component styles
├─ lib/
│  ├─ api.js                  REST client + websocket URL builder
│  ├─ useChatSocket.js        Socket lifecycle, reconnect/backoff, send guards
│  ├─ hooks.js                usePersistentState, useStreamBuffer (rAF batching)
│  ├─ accents.js              Warm accent map, tint styles, initials
│  ├─ time.js                 relativeTime, clockTime, dayLabel, previewText
│  └─ cx.js                   Class-name joiner
└─ components/
   ├─ Sidebar.jsx             Brand, new button, search, companion list, theme switch
   ├─ ChatHeader.jsx          Avatar, status, overflow menu
   ├─ MessageList.jsx         Day separators, grouping, autoscroll, streaming row
   ├─ Composer.jsx            Auto-growing input, Enter/Shift+Enter, stop button
   ├─ Markdown.jsx            Dependency-free renderer for replies
   ├─ Avatar.jsx              Initials disc tinted per companion
   ├─ EmptyStates.jsx         WelcomePane (no selection) + StartPane (no messages)
   ├─ NewAgentDialog.jsx      Archetype, name shuffle, brief, accent picker
   ├─ ConfirmDialog.jsx       Destructive and clearing confirmations
   ├─ ui.jsx                  IconButton, Notice, StatusDot
   └─ personaIcons.js         Archetype → lucide icon
```

### Notable behaviours

**Streaming stays smooth.** `useStreamBuffer` accumulates incoming `delta`
frames in a ref and flushes on `requestAnimationFrame`, so a fast token stream
costs one render per frame instead of one per chunk. Completion replaces the
buffer with the authoritative text the server saved.

**Typing never scrolls away from you.** `MessageList` auto-scrolls only while
the reader is within 80px of the bottom, so scrolling back through history is
never interrupted by an incoming reply. It scrolls a bottom sentinel into view
rather than assigning `scrollTop`, so it still works if the document (not the
transcript) turns out to be the scroller on a short window.

**Nothing ever clips.** See the layout rules below.

**Reconnects are visible, not silent.** `useChatSocket` retries with exponential
backoff (400ms to 8s) and resets on success. If a frame cannot be delivered the
composer says so instead of dropping your message. A `4404` close means the
companion was deleted, so it does not retry - it removes the row and explains.

### Layout and scrolling

The shell is pinned to the viewport (`height: 100dvh`, `body { overflow: hidden }`)
so the composer stays reachable and the transcript scrolls under it. Three
invariants keep that from turning into clipped, unreachable content - all three
are enforced by `test/layout.test.js`:

1. **Every scroll region declares its own `overflow-y: auto`.** `.messages`,
   `.sidebar__list`, `.dialog__body` and the empty states do not depend on a
   utility class being remembered in JSX.
2. **Full-height panes centre with `margin: auto` on the child, never with
   `place-items: center`.** Centring an item that overflows its container pushes
   the top edge above the scroll origin, where no amount of scrolling reaches it.
3. **The columns declare `min-height: 0`.** Without it the flex column outgrows
   its grid row, `body { overflow: hidden }` clips the excess, and the transcript
   appears to have no scrolling at all.

Fixed chrome (header, composer, sidebar head/section/foot, dialog head/foot) is
`flex: none`, so only the content regions absorb leftover height.

Short viewports are handled by compaction rather than by hiding things:

| Breakpoint | Effect |
| --- | --- |
| `max-height: 740px` | Tighter header, composer, empty state, dialog and sidebar paddings |
| `max-height: 620px` | Keyboard hint row dropped, compact companion rows, smaller empty-state mark |
| `max-width: 860px` | Sidebar becomes a drawer, one-column layout |
| `max-width: 620px` | Single-column persona grid, header hint hidden |

**Rendering is injection-proof.** `Markdown.jsx` returns React elements rather
than HTML strings - fenced code, inline code, bold, italic (nesting included),
links, lists and quotes - so message content can never inject markup. A test
asserts that a raw `<img onerror>` payload comes out escaped.

**Two tabs, one conversation.** The backend broadcasts each companion's events to
every listener, so both windows stay in step.

### Keyboard

| Key | Action |
| --- | --- |
| `Enter` | Send |
| `Shift` + `Enter` | New line |
| `N` | New companion (ignored while typing in a field) |
| `Esc` | Close dialog or menu |

## Tests

```powershell
npm test
```

- **Render** - the real React tree through `react-dom/server` under jsdom, which
  catches broken imports, hook misuse and JSX mistakes a build alone would miss.
- **Layout guard** - parses `styles.css` into rules and asserts the scrolling
  invariants above: every scroll region declares `overflow-y`, the full-height
  panes never use `place-items`, the columns declare `min-height: 0`, fixed
  chrome never shrinks, `vh` fallbacks precede `dvh`, and the short-viewport
  breakpoints exist.
- **Markdown** - emphasis (including nesting), code fences, lists, quotes, links,
  and HTML escaping.
- **Time helpers** - relative/absolute formatting and day grouping.
- **Palette guard** - parses every colour literal in `styles.css`, converts to
  HSL, and fails if anything leaves the warm band. It also asserts all eight
  accents exist in both themes, that `box-shadow` never appears, and that both
  themes are present.

## Deploying

Build with `npm run build` and serve `dist/` from any static host. There is no
dev proxy in production, so point the app at the API explicitly:

```bash
VITE_API_BASE=https://api.example.com
VITE_WS_BASE=wss://api.example.com
```

Both are baked in at build time. Then add the UI origin to the backend's
`CORS_ORIGINS`. Serving the API and the static bundle from the same origin needs
neither variable.
