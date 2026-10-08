---
kind: frontend_style
name: Operator Portal Styling — Ant Design Dark Theme + CSS Custom Properties
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/vite.config.ts
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
---

## System / Approach

The only frontend in the repository is the **operator-portal** web UI under `products/operator-portal/web-ui/app`. It is a React 19 + TypeScript application built with Vite (`@vitejs/plugin-react`) and styled primarily through:

1. **Ant Design v6** (`antd`, `@ant-design/icons`, `@ant-design/x`) as the component library, configured via a `ThemeConfig` object.
2. A single global stylesheet `app/src/theme/global.css` providing CSS custom properties (design tokens) consumed by bespoke component styles.
3. No CSS-in-JS, no Tailwind, no SCSS — plain CSS variables on `:root` paired with an antd dark theme.

There is no separate design-token system beyond the two-file pair `tokens.ts` / `global.css`; there is no responsive framework (no Bootstrap, no Tailwind breakpoints) — responsiveness is handled inline with `@media` queries and antd's built-in responsive Sider behavior.

## Key Files

- `products/operator-portal/web-ui/app/package.json` — declares `react`, `antd`, `@ant-design/icons`, `@ant-design/x`, `dayjs`, plus Vite/Vitest tooling.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs to `../dist` for nginx.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — defines the `palette` object and `portalTheme: ThemeConfig` using `antd.darkAlgorithm`.
- `products/operator-portal/web-ui/app/src/theme/global.css` — `:root` CSS custom properties mirroring `palette`, plus all bespoke layout/animation rules (chat workspace, HITL confirm cards, evidence groups, sticky request banner, bounded panes).
- `products/operator-portal/web-ui/nginx.conf` — serves the built `dist/` directory.

## Architecture and Conventions

### Single source of truth for colors

`tokens.ts` is the canonical palette:

```ts
export const palette = {
  bg: "#0f172a",
  surface: "#1e293b",
  surfaceAlt: "#334155",
  border: "#475569",
  text: "#e2e8f0",
  textMuted: "#94a3b8",
  accent: "#38bdf8",
  accentHover: "#7dd3fc",
  success: "#4ade80",
  error: "f87171",
  warning: "#fbbf24",
  codeBg: "#1a2332",
  radius: 8,
};
```

The same values are redeclared as CSS custom properties on `:root` in `global.css` (`--bg`, `--surface`, `--accent`, …, `--radius`). The comment in `tokens.ts` states this is a verbatim port from the legacy portal's `styles.css` and that the mirror exists so "bespoke styles and antd components stay on one vocabulary" (SPEC-023 R-1 dark theme).

### Ant Design theme configuration

`portalTheme` maps the palette onto antd's token surface:

- `algorithm: antdTheme.darkAlgorithm` — the entire app ships in dark mode.
- `colorPrimary`, `colorBgBase`, `colorBgContainer`, `colorBgElevated`, `colorBorder`, `colorText`, `colorTextSecondary`, semantic colors, `borderRadius`, and font families are set from `palette`.
- Font families: sans-serif stack starts with `Inter`; monospace uses `JetBrains Mono` / `Fira Code`.

Bespoke CSS classes in `global.css` consume the CSS custom properties rather than antd tokens directly, keeping non-antd markup on the same color vocabulary.

### Layout model

The app shell is a fixed-height Flexbox layout (`height: 100%` on `html/body/#root`) composed of an antd `Layout.Sider` sidebar and a main content area. The sidebar supports:

- Collapsed icon rail (64px) where group titles are hidden and replaced with hairline dividers.
- An off-canvas drawer fallback below antd's `lg` breakpoint (992px), triggered by a pinned `.mobile-menu-button`.
- A footer section that collapses to avatar + auth button when folded.

Views use `.view-container` (scrollable, 20px/24px padding) or `.view-container-flush` for full-bleed views like chat.

### Chat workspace layout

A dedicated `.chat-view` flex layout splits into a fixed-width `.session-panel` (260px, shrinks to 200px at ≤860px) and a fluid `.chat-column` transcript. Transcript rows use `.turn-group`; incoming turns after external decisions get a `.turn-arrived` class with a 4s `turn-arrive-flash` keyframe animation (disabled under `prefers-reduced-motion`).

### Evidence and HITL card conventions

- Tool evidence groups: `.evidence-turn` → `.evidence-card` → `.evidence-pre` (bounded to 280px height with its own scrollbar).
- Sticky request banner: `.turn-request-banner` appears above long replies to keep the original prompt visible.
- HITL confirmation cards: `.confirm-card` with `.pending` variant, nested `.confirm-call`, `.confirm-call-details` `<summary>` expanders, and signed-execution receipt rows (SPEC-037 R-6, SPEC-063 R-5a).

### Bounded panes

Document viewer panes use a shared CSS variable `--bounded-pane-max-height` applied to wrapper elements; selectors `.digest-bounded .ant-tabs-body-holder` and `.prose-bounded .ant-collapse-body` clamp scrolling to that height (SPEC-041 R-3).

### Responsive strategy

No media-query framework. Breakpoints are ad-hoc:

- `@media (max-width: 860px)` narrows the session panel.
- `@media (prefers-reduced-motion: reduce)` disables animations.
- Sidebar collapse relies on antd's built-in `lg` breakpoint (992px); mobile drawer is a JS-driven alternative.

### Build-time version injection

`vite.config.ts` reads the repo root `VERSION` file and the local `package-lock.json` to define `__PLATFORM_VERSION__`, `__REACT_VERSION__`, and `__ANTD_VERSION__` constants, which the Settings view consumes to display the shipped tech stack (SPEC-023 R-1).

## Conventions and Constraints

- **Dark-only theme**: `color-scheme: dark` is set on `:root` and antd uses `darkAlgorithm`; no light-mode toggle exists.
- **Token synchronization rule**: `tokens.ts` and `global.css` must remain in sync — both declare the same palette values. This is documented in the comments of both files and referenced as SPEC-023 R-1.
- **CSS custom property vocabulary**: Bespoke styles reference `var(--accent)`, `var(--surface)`, etc., never raw hex literals, so changing a color flows through the single `palette` object.
- **Font policy**: Sans-serif defaults to Inter; code/monospace defaults to JetBrains Mono / Fira Code. Both are declared in the antd theme and repeated in `.md-content code` / `.tool-name` selectors.
- **Border radius**: All rounded corners use `var(--radius)` (8px), sourced from the palette.
- **Accessibility**: Global `:focus-visible` outline uses the accent color with 2px offset; reduced-motion is respected for animated turn arrivals.
- **Build output**: Vite builds to `web-ui/dist/`, served by the product's `nginx.conf`; asset filenames are content-hashed while `index.html` is served without cache (SPEC-023 R-1).
- **No additional CSS methodology**: There is no BEM linter, CSS Modules, CSS-in-JS, or utility framework enforcing naming — class names in `global.css` follow a flat, descriptive convention (e.g. `.session-item`, `.confirm-card`, `.evidence-pre`).