---
kind: frontend_style
name: Operator Portal Frontend Style (Ant Design + CSS Custom Properties)
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
    - products/operator-portal/web-ui/app/src/main.tsx
    - products/operator-portal/web-ui/app/src/App.tsx
---

# Operator Portal Frontend Style

## What system/approach is used

The operator portal (`products/operator-portal/web-ui`) is a React 19 / Vite / TypeScript SPA. Styling is built on two layers:

1. **Ant Design v6** as the component library, configured via `ConfigProvider` with a `ThemeConfig` that enables `antd.theme.darkAlgorithm` and maps Ant tokens to a shared palette.
2. **Plain CSS custom properties** defined in `app/src/theme/global.css`, which mirror the same palette so bespoke styles and Ant components share one vocabulary.

There is no Tailwind, SCSS, CSS-in-JS, or design-token generator — the only token source is the hand-maintained pair of `tokens.ts` and `global.css`.

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares `antd ^6.6.2`, `@ant-design/icons ^6.0.0`, `@ant-design/x ^2.9.0`, React 19, Vite 8, Vitest.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — defines the `palette` object and the `portalTheme: ThemeConfig` applied through Ant's `ConfigProvider`.
- `products/operator-portal/web-ui/app/src/theme/global.css` — root-level CSS custom properties (`--bg`, `--surface`, `--accent`, `--border`, `--text`, `--radius`, …) plus all bespoke layout/animation rules.
- `products/operator-portal/web-ui/app/src/main.tsx` — mounts `<ConfigProvider theme={portalTheme}>` around the app.
- `products/operator-portal/web-ui/app/src/App.tsx` — builds the shell using Ant `Layout`/`Sider`/`Menu` and the `.app-shell` / `.sidebar-*` classes from global.css.

## Architecture and conventions

### Dual token sync
`tokens.ts` and `global.css` are kept in lockstep. The comment at the top of `tokens.ts` states explicitly: "Palette ported verbatim from the legacy portal's :root design tokens (styles.css). The CSS custom properties in global.css mirror these so bespoke styles and antd components stay on one vocabulary (SPEC-023 R-1 dark theme)." Every color, radius, and font family appears in both places.

### Dark-only theme
`global.css` sets `color-scheme: dark` on `:root`; `tokens.ts` uses `antdTheme.darkAlgorithm`. There is no light-mode toggle — the portal is dark-only.

### Shared vocabulary
Bespoke class names in global.css consume the CSS variables (`var(--bg)`, `var(--surface)`, `var(--accent)`, `var(--border)`, `var(--text-muted)`, `var(--code-bg)`, `var(--radius)`), while Ant components receive the same values through `portalTheme.token` (e.g. `colorPrimary: palette.accent`, `colorBgBase: palette.bg`).

### Layout model
The app shell is an Ant `Layout` + `Sider` sidebar plus a single active function view. Global CSS provides `.app-shell`, `.view-container`, `.view-container-flush`, `.sidebar-footer`, `.mobile-menu-button`, and collapsed-sidebar overrides for `.ant-layout-sider-collapsed`. A pinned `.mobile-menu-button` toggles between inline sidebar (desktop) and off-canvas drawer (below Ant's `lg` breakpoint, 992px).

### Chat workspace
A dedicated `.chat-view` flex layout splits a fixed-width `.session-panel` (260px, shrinking to 200px at ≤860px) from a fluid transcript column. Transcript rows use `.turn-group`, evidence blocks use `.evidence-turn` / `.evidence-card` / `.evidence-pre`, and incoming turns get a `.turn-arrived` animation (4s fade-out accent edge, suppressed under `prefers-reduced-motion`).

### Markdown and code rendering
Rendered markdown lives under the `.md-content` wrapper; fenced code blocks and tool evidence use `.evidence-pre` with a capped height of 280px so long outputs don't push the transcript out of view.

### HITL confirmation cards
Confirmation UI follows `.confirm-card` / `.confirm-call` / `.confirm-call-details` / `.confirm-execution` / `.confirm-execution-recovery` selectors, with state variants like `.confirm-card.pending` styled via `--warning`.

### Responsive strategy
No media-query framework. Breakpoints are minimal and inline:
- `@media (max-width: 860px)` narrows the session panel.
- `@media (prefers-reduced-motion: reduce)` disables the turn-arrival flash.
- Drawer vs. inline sidebar behavior is driven by Ant's built-in `lg` breakpoint (992px) combined with the pinned mobile trigger.

### Accessibility conventions observed
- `:focus-visible` gets a 2px solid `--accent` outline with 2px offset.
- Pinned elements use `aria-hidden="true"` where appropriate (e.g. the brand spacer).
- Motion-sensitive animations respect `prefers-reduced-motion`.

### Spec-driven style anchors
Global CSS comments repeatedly anchor visual decisions to specs, e.g. `(SPEC-023 R-1 dark theme)`, `(SPEC-023 R-3)`, `(SPEC-034 R-1 / SPEC-035 R-4)`, `(SPEC-037 R-6)`, `(SPEC-063 R-5a)`, `(SPEC-041 R-3, v0.25.1 polish)`. This is the repository's documented convention for tying UI changes back to spec requirements.

## Conventions and constraints

- **Single source of truth for colors**: the `palette` object in `tokens.ts` is the canonical definition; `global.css` and `portalTheme.token` must mirror it verbatim (enforced by the explicit comment in `tokens.ts`).
- **Dark-only**: the portal never switches themes; `color-scheme: dark` and `darkAlgorithm` are set unconditionally.
- **CSS variable usage**: bespoke styles reference `var(--*)` rather than hard-coded hex values, keeping them synchronized with the Ant theme.
- **Component styling split**: Ant primitives (`Button`, `Table`, `Modal`, `Select`, `Tag`, `Typography`, `Collapse`, `Tabs`, `Statistic`, `Alert`, `Pagination`, `Spin`) provide structure; global.css adds layout, spacing, and domain-specific chrome (session list, chat transcript, evidence cards, approval cards).
- **Class naming**: bespoke classes use kebab-case BEM-like names scoped to feature areas (`.session-*`, `.chat-*`, `.composer-*`, `.turn-*`, `.evidence-*`, `.confirm-*`, `.approvals-entry`, `.digest-bounded`, `.prose-bounded`).
- **Spec anchoring**: new UI features add a comment linking the relevant selector(s) to the owning spec requirement (e.g. `SPEC-020 R-4`, `SPEC-039 R-8`, `SPEC-063 R-5a`).