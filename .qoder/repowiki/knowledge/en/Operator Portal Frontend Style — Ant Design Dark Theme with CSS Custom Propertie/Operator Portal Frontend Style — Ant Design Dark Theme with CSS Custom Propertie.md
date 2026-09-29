---
kind: frontend_style
name: Operator Portal Frontend Style — Ant Design Dark Theme with CSS Custom Properties
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/package.json
    - products/operator-portal/web-ui/app/vite.config.ts
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
    - products/operator-portal/web-ui/app/src/main.tsx
---

## What system/approach is used

The operator portal (`products/operator-portal/web-ui`) is a React 19 + TypeScript SPA built with Vite and styled primarily through **Ant Design v6** in dark mode. The visual identity is defined by a single source of truth — `src/theme/tokens.ts` — which exports an `antd` `ThemeConfig` using `antdTheme.darkAlgorithm` and a matching palette object. That same palette is mirrored as CSS custom properties in `src/theme/global.css` under `:root`, so bespoke component styles consume the same vocabulary via `var(--accent)`, `var(--surface)`, etc., while Ant Design components consume it through the theme config. This dual export is explicitly documented as part of SPEC-023 R-1 (dark theme).

There is no Tailwind, Sass, or CSS-in-JS library beyond what Ant Design ships; styling is plain CSS modules-free global CSS plus Ant Design's built-in component classes.

## Key files and packages

- `products/operator-portal/web-ui/package.json` — declares `antd ^6.6.2`, `@ant-design/icons ^6.0.0`, `@ant-design/x ^2.9.0`, React 19, Vite, Vitest.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs to `../dist` for nginx serving; proxies `/api` to `localhost:8080` in dev.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single design-token file exporting `palette` (bg, surface, surfaceAlt, border, text, textMuted, accent, accentHover, success, error, warning, codeBg, radius) and `portalTheme` (`ThemeConfig`).
- `products/operator-portal/web-ui/app/src/theme/global.css` — root-level CSS variables mirroring `tokens.ts`; defines app shell, sidebar, chat transcript, evidence cards, HITL confirmation cards, markdown rendering, sticky request banner, bounded panes, and responsive breakpoints.
- `products/operator-portal/web-ui/app/src/main.tsx` — wraps the app in `antd` `ConfigProvider` with `portalTheme`.
- `products/operator-portal/nginx.conf` — serves the built `web-ui/dist` at `/`.

## Architecture and conventions

1. **Single token source**: All colors, spacing radii, and font families are declared once in `tokens.ts`. The `palette` object is the canonical definition; `global.css` re-declares them as `--bg`, `--surface`, `--accent`, etc., and `portalTheme` maps them into Ant Design tokens (`colorPrimary`, `colorBgBase`, `colorText`, `borderRadius`, `fontFamily`, `fontFamilyCode`).
2. **Dark-only theme**: `color-scheme: dark` is set on `:root`; there is no light-mode toggle. The entire portal is designed for a dark background (`#0f172a`) with `#e2e8f0` body text and `#38bdf8` accent.
3. **Component library usage**: Components are imported directly from `antd` (Layout, Menu, Sider, Button, Table, Modal, Tag, Typography, Tabs, Collapse, Statistic, Alert, Spin, Segmented, Select). No third-party UI kit is layered on top of Ant Design.
4. **Bespoke CSS scope**: Custom layout and view-specific styles live in `global.css` using BEM-like class names (`.app-shell`, `.session-panel`, `.chat-view`, `.evidence-card`, `.confirm-card`, `.turn-group`, `.view-toolbar`, `.digest-bounded`, `.prose-bounded`). These classes target both raw DOM elements and Ant Design component wrappers (e.g., `.ant-layout-sider-collapsed .ant-menu-item-group-title`).
5. **Responsive strategy**: A single `@media (max-width: 860px)` breakpoint narrows the session panel; the sidebar uses Ant Design's `Sider` collapse behavior above that width and switches to an off-canvas drawer below, driven by a pinned `.mobile-menu-button`.
6. **Accessibility hooks**: `:focus-visible` gets a 2px accent outline; `prefers-reduced-motion` disables the turn-arrival flash animation.
7. **Build-time versioning**: `vite.config.ts` reads the repo root `VERSION` and the lockfile to inject `__PLATFORM_VERSION__`, `__REACT_VERSION__`, and `__ANTD_VERSION__` constants, so the Settings view can report the exact shipped tech stack.
8. **Markdown/evidence rendering**: A shared `.md-content` stylesheet normalizes headings, lists, code blocks, blockquotes, tables, and links to match the dark palette; fenced code blocks are capped at 280px height with internal scrolling.

## Conventions and constraints

- **All color/spacing values must come from `tokens.ts`** — new hues or radii are added to the `palette` object and mirrored in `global.css`; ad-hoc hex literals in component CSS are discouraged per the comment that tokens are "ported verbatim" and kept in sync.
- **Components consume Ant Design via `ConfigProvider`** at the app root; individual components do not pass inline theme props.
- **Custom styles use CSS variables** (`var(--accent)`, `var(--surface)`, `var(--border)`, `var(--radius)`) rather than hard-coded colors, keeping bespoke CSS aligned with the Ant Design theme.
- **Chat and evidence areas use bounded scroll containers** (`.chat-messages`, `.evidence-pre`, `.digest-bounded`, `.prose-bounded`) with explicit `max-height` to prevent long tool output from pushing content out of view.
- **HITL confirmation cards, evidence groups, and signed-execution receipts** follow the class naming patterns in `global.css` (`.confirm-card`, `.evidence-turn`, `.confirm-execution`, `.recovery-facts`) and are referenced by spec requirements (SPEC-020, SPEC-037, SPEC-063).
- **Fonts**: Sans-serif defaults to Inter/system stack; code uses JetBrains Mono / Fira Code monospace, applied consistently across markdown code, tool names, and recovery facts.