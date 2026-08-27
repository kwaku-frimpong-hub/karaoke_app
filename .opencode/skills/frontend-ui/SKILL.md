---
name: frontend-ui
description: Use when implementing or modifying any frontend UI for the Friday Karaoke app — screens, components, CSS (participant join/submit/queue, host login/home/dashboard). Codifies the dark design system, the two-surface layout rules (mobile-first participant vs projector/TV host), component patterns, accessibility, and the frontend Definition of Done.
---

# Friday Karaoke — Frontend UI skill

This skill defines how the Friday Karaoke frontend should look and be built.
It applies to **every** frontend change: new screens, CSS, component refactors,
or style fixes. Follow it unless the user explicitly overrides.

## 1. Design tokens (CSS variables)

Define these in `frontend/src/index.css` on `:root`. Use the variables everywhere;
never hard-code hex values or ad-hoc spacing in components.

| Token | Value | Used for |
| ----- | ----- | -------- |
| `--bg` | `#12131a` | page background |
| `--surface` | `#171a24` | cards, list rows, panels |
| `--surface-2` | `#1b1e29` | inputs, raised areas |
| `--surface-3` | `#2f3550` | chips, positions, subtle fills |
| `--border` | `#2b3140` | card/row borders |
| `--border-strong` | `#333a4d` | inputs, ghost buttons |
| `--text` | `#eef0f6` | primary text |
| `--muted` | `#9aa0b4` | secondary text, labels |
| `--primary` | `#5b8cff` | primary buttons, accents, focus ring |
| `--primary-ink` | `#0d1220` | text on primary buttons |
| `--success` | `#3fae74` | success states |
| `--danger` | `#b3374c` | destructive buttons |
| `--danger-text` | `#ff7b7b` | destructive text/link actions |
| `--on-danger` | `#ffffff` | text on danger buttons |
| `--warn` | `#ffc66d` | warnings |
| `--qr-bg` | `#ffffff` | QR code background (must stay white to scan) |
| `--active-bg` | `#1f5f3d` | ACTIVE/Live badge background |
| `--active-text` | `#9dffc2` | ACTIVE/Live badge text, join code |
| `--paused-bg` | `#5f531f` | PAUSED badge background |
| `--paused-text` | `#ffe49d` | PAUSED badge text |
| `--ended-bg` | `#5c2330` | ENDED badge background |
| `--ended-text` | `#ffb3c0` | ENDED badge text |
| `--radius` | `10px` | inputs, buttons, chips |
| `--radius-lg` | `14px` | cards |
| `--focus` | `#7aa2ff` | `:focus-visible` outline |
| `--space-1` | `4px`, `--space-2` | `8px`, `--space-3` | `12px`, `--space-4` | `16px`, `--space-5` | `24px`, `--space-6` | `40px` |
| `--text-sm` | `0.875rem`, `--text-base` | `1rem`, `--text-lg` | `1.25rem`, `--text-xl` | `1.75rem`, `--text-2xl` | `2rem`, `--text-display` | `2.4rem` |

Buttons: primary = `--primary` bg with `--primary-ink` text. Ghost = transparent
bg, `--border-strong` border, `--text` color. Danger = `--danger` bg, white text.
Link-button = transparent, `--danger-text`, underlined.

## 2. Two surfaces — layout rules

### Participant (mobile-first)
- Single column, `max-width: 28rem` container.
- Every interactive target ≥ 44px (`min-height` on buttons/inputs).
- Primary action last/thumb-reachable; secondary actions as ghost/link buttons.
- The **queue** view: session status badge → "Now singing" card → "Up next" card →
  queue list → own-entry controls.

### Host dashboard (projector / TV)
- Wider container (`max-width: 72rem`), large text (`--text-lg`+ for body,
  `--text-display` for the join code).
- High contrast; nothing relies on color alone.
- **Above the fold**: session title + status, join code + QR, current singer,
  next singer, primary action buttons. Queue scrolls beneath.
- Group actions visually; disabled actions must look disabled (opacity + cursor)
  and carry a `title` explaining why.
- Responsive: the two-column `now/next + actions | queue` grid collapses to one
  column under `60rem`.

## 3. Component patterns

- **Cards**: `--surface` bg, `--border` border, `--radius-lg`, `--space-4` padding.
  Highlight card: `--primary` border (current singer).
- **Badges** (session/status/round): pill, `--space-2`/`--space-3` padding, `--radius`
  (999px), small uppercase bold, colored per status (created/paused muted,
  active green, ended red; `round` uses `--surface-3` with `--text`).
- **Inputs**: `--surface-2` bg, `--border-strong` border, `--radius`, min-height
  48px. Must have a visible `:focus-visible` ring (`--focus`). Text inputs should
  have a visible label (`<label>`) or an aria-label.
- **Buttons**: `--radius`, min-height 48px (participant) / 52px (host actions),
  font-weight 600. Disabled: `opacity: 0.5`, `cursor: not-allowed`.
- **List rows** (queue/sessions): flex with a position chip, a main column
  (title + muted metadata line), and trailing actions. Key by stable id.
- **States**: every async region renders loading, empty, and error states.
  Loading = muted "Loading…". Empty = a friendly muted message. Error = `--warn`
  or `--danger-text` message surfaced near the action that failed. Never leave a
  fetch silently blank.
- **Navigation**: header bar with the session/app name on the left and primary
  nav (Add Song, Open, Back) on the right. `Link`s for navigation, `button`s for
  actions — never nest a `<button>` inside an `<a>` (invalid HTML).

## 4. Accessibility

- WCAG AA contrast for text on its background (muted text on `--bg`/`--surface`
  is already tuned; don't darken it further).
- `:focus-visible` outlines everywhere; remove default `outline: none` only when
  replacing it with the custom focus ring.
- Use real `<label>`s (or `aria-label`) for inputs; `aria-live` is unnecessary
  for this app's scale.
- Semantic HTML: `ol`/`ul` for lists, `section`/`header`/`main` landmarks,
  `<strong>` for emphasis, not styling.
- Don't rely on color alone to convey state (e.g. a status badge always includes
  text).

## 5. Code conventions

- State: **never own authoritative state client-side.** Render API responses
  (typed `src/api/` client). The only persistence is participant/host identity
  in localStorage (`src/lib/token.ts`, `src/lib/hostToken.ts`).
- Reuse shared helpers: `formatDuration` (`src/lib/format.ts`),
  `statusLabel` (`src/lib/session.ts`).
- No inline styles; styles live in `src/index.css` (tokens) and `src/App.css`
  (component classes). Name classes semantically (`host-dashboard`, `queue-list`).
- Keep the existing structure: one component file per screen under
  `src/features/<feature>/`.
- TypeScript strict: no `any`, no unused imports/params. Run `npm run typecheck`.

## 6. Definition of done (frontend)

For any frontend change, all of these must hold before considering it done:

- [ ] Design tokens used (no hard-coded colors/spacing).
- [ ] Surface rules respected (participant mobile-first, host projector-ready).
- [ ] Loading, empty, and error states present for every fetch.
- [ ] Interactive targets ≥ 44px; `:focus-visible` visible.
- [ ] No `<a>` wrapping `<button>`; semantic HTML used.
- [ ] `npm run typecheck`, `npm run lint`, and `npm run build` pass.
- [ ] Visually verified at the target breakpoints (phone / projector).
