---
kind: frontend_style
name: Operator Portal Frontend Style — Ant Design Dark Theme with CSS Custom Properties
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/vite.config.ts
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
---

## What system/approach is used

The only frontend in this repository lives under `products/operator-portal/web-ui/app/`. It is a React 19 + TypeScript application built with Vite (`@vitejs/plugin-react`) and styled primarily through **Ant Design v6** (`antd` + `@ant-design/icons` + `@ant-design/x`). There is no Tailwind, Sass, CSS-in-JS library, or component-library theme override file beyond what is shown below.

Styling follows a two-layer approach:

1. **Design tokens in TypeScript** — `app/src/theme/tokens.ts` defines a single `palette` object (bg, surface, surfaceAlt, border, text, textMuted, accent, accentHover, success, error, warning, codeBg, radius) and an Ant Design `ThemeConfig` (`portalTheme`) that maps those tokens onto antd's token schema using `antdTheme.darkAlgorithm`.
2. **CSS custom properties mirroring the same palette** — `app/src/theme/global.css` declares the identical values as `:root` CSS variables (`--bg`, `--surface`, `--accent`, …) so bespoke styles and antd components share one vocabulary. The comment on line 3 of `tokens.ts` explicitly states the mirror relationship.

There is no light-theme implementation; `global.css` sets `color-scheme: dark` and the antd theme uses `darkAlgorithm`, making the portal a dark-only UI.

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares `antd ^6.6.2`, `@ant-design/icons ^6.0.0`, `@ant-design/x ^2.9.0`, React 19, Vite 8, Vitest 4.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time via `define`; outputs to `../dist` for nginx consumption.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single source of truth for colors, radii, and fonts; exports `portalTheme`.
- `products/operator-portal/web-ui/app/src/theme/global.css` — global base styles, CSS custom properties, layout shell, chat workspace, markdown rendering, evidence cards, HITL confirmation cards, sticky request banner, bounded panes, and narrow-viewport breakpoints.
- `products/operator-portal/web-ui/nginx.conf` — serves the built `web-ui/dist` at `/`.

## Architecture and conventions

- **Token discipline**: Colors, spacing radii, and font families are defined once in `tokens.ts` and mirrored into `global.css` as CSS custom properties. Bespoke selectors reference `var(--accent)`, `var(--border)`, etc., rather than hard-coded hex values. This keeps antd overrides and hand-written CSS on the same palette.
- **Component styling model**: Ant Design components receive the `portalTheme` `ThemeConfig` at the app root; custom component chrome is written as plain CSS classes in `global.css` (e.g. `.app-shell`, `.sidebar-footer`, `.view-container`, `.chat-view`, `.session-panel`, `.confirm-card`, `.evidence-card`, `.turn-request-banner`).
- **Layout strategy**: A full-height sidebar + function view shell (`app-shell`) with antd `Layout.Sider`. On desktop the sidebar folds to a 64px icon rail; below antd's `lg` breakpoint (992px) it switches to an off-canvas drawer driven by a pinned `.mobile-menu-button`. Session list panels use fixed widths (260px, 200px at ≤860px).
- **Responsive handling**: Pure CSS media queries (`max-width: 860px` for session panel, `prefers-reduced-motion: reduce` for turn-arrival animation). No responsive utility framework.
- **Accessibility baseline**: `:focus-visible` gets a 2px solid `var(--accent)` outline with 2px offset; `color-scheme: dark` is declared globally.
- **Content rendering**: Markdown content goes through a `.md-content` scope with explicit rules for headings, lists, code blocks (monospace `JetBrains Mono` / `Fira Code`, max-height 280px), blockquotes, tables, links, and horizontal rules.
- **Feature-scoped CSS modules**: Styles are co-located with feature areas in `global.css` — chat workspace (SPEC-023 R-3), tool evidence groups (SPEC-011 R-4 parity), HITL confirmation cards (SPEC-020 R-4), signed-execution receipts (SPEC-037 R-6), owner recovery details (SPEC-063 R-5a), shared view toolbar (SPEC-023 R-5), and documents bounded panes (SPEC-041 R-3).
- **Bounded panes**: Fixed-height scrollable regions (`digest-bounded`, `prose-bounded`) whose `max-height` is supplied per-instance via a `--bounded-pane-max-height` CSS variable set by the view layer.

## Conventions and constraints

- **Dark-only theme**: `color-scheme: dark` in `global.css` and `algorithm: antdTheme.darkAlgorithm` in `portalTheme` make the portal render exclusively in dark mode; no alternate theme configuration exists.
- **Single palette source**: `tokens.ts` and `global.css` must stay in sync — the comment in `tokens.ts` documents that the CSS custom properties are "ported verbatim from the legacy portal's :root design tokens" and exist so "bespoke styles and antd components stay on one vocabulary" (referenced as SPEC-023 R-1 dark theme).
- **Token usage over literals**: Bespoke CSS selectors use `var(--accent)`, `var(--surface)`, `var(--border)`, `var(--text-muted)`, `var(--code-bg)`, `var(--radius)` instead of inline color/hex values, keeping visual consistency across antd and hand-written components.
- **Font policy**: Sans-serif stack is `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif`; monospace stack is `"JetBrains Mono", "Fira Code", monospace`. Both are declared in `portalTheme.token.fontFamily` / `fontFamilyCode` and repeated in `global.css` body and code rules.
- **Border radius**: All rounded corners derive from `palette.radius = 8` (applied as `8px` via `--radius`); there is no ad-hoc radius value in the stylesheet.
- **Spec-linked style rules**: Many CSS blocks carry comments tying them to a spec requirement (e.g. `SPEC-023 R-1`, `SPEC-023 R-3`, `SPEC-011 R-4`, `SPEC-020 R-4`, `SPEC-037 R-6`, `SPEC-039 R-8`, `SPEC-041 R-3`, `SPEC-063 R-5a`), providing traceability between visual behavior and product specs.
- **Build-time version injection**: `vite.config.ts` reads the repo `VERSION` file and the lockfile to define `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` constants consumed at runtime (the Settings platform inventory displays these versions).
- **No Tailwind / SCSS / CSS Modules**: The dependency manifest and project structure contain no Tailwind config, no `.scss` files, and no CSS module imports — styling is centralized in `global.css` plus antd's built-in class names.