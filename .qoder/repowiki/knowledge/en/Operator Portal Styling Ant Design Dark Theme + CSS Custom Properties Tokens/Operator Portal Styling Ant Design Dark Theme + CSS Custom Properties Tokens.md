---
kind: frontend_style
name: 'Operator Portal Styling: Ant Design Dark Theme + CSS Custom Properties Tokens'
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

The Operator Portal (`products/operator-portal/web-ui`) is a React 19 / TypeScript SPA built with Vite and styled primarily through **Ant Design v6** (`antd`, `@ant-design/icons`, `@ant-design/x`). Visual consistency is achieved by:

1. A single design-token file (`app/src/theme/tokens.ts`) that defines the palette, radii, and fonts.
2. An Ant Design `ThemeConfig` (`portalTheme`) using `antdTheme.darkAlgorithm` so all antd components consume the same tokens.
3. A parallel set of CSS custom properties in `app/src/theme/global.css` (`--bg`, `--surface`, `--accent`, `--border`, `--text`, `--success`, `--error`, `--warning`, `--code-bg`, `--radius`) that bespoke component styles reference directly.
4. A hand-authored global stylesheet (`global.css`, ~740 lines) providing layout, chat transcript, evidence cards, HITL confirmation cards, markdown rendering, sticky request banners, and bounded-pane utilities — no CSS-in-JS, no Tailwind, no SCSS preprocessor.
5. The app shell uses Ant Design's `Layout`/`Sider`/`Menu` for navigation; responsive behavior relies on CSS media queries (e.g. `@media (max-width: 860px)` for session-panel folding) rather than a breakpoint framework.

There is no second UI product in this repository — the remaining products are FastAPI services. The styling concern therefore applies only to `products/operator-portal/web-ui`.

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares `react ^19`, `antd ^6.6.2`, `@ant-design/icons ^6`, `@ant-design/x ^2.9`, plus Vite/Vitest tooling.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; builds into `../dist` for nginx.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — canonical token definitions (`palette`, `portalTheme`).
- `products/operator-portal/web-ui/app/src/theme/global.css` — global base styles, CSS variables, layout, chat/evidence/HITL/markdown/bounded-pane rules.
- `products/operator-portal/web-ui/nginx.conf` — serves the built static assets under `/`.

## Architecture and conventions

- **Token duality**: `tokens.ts` is the source of truth for both the Ant Design theme and the CSS custom properties. The comment in `tokens.ts` states the palette was "ported verbatim from the legacy portal's :root design tokens (styles.css)" and that the CSS variables mirror it so "bespoke styles and antd components stay on one vocabulary" (SPEC-023 R-1 dark theme).
- **Dark-only surface**: `global.css` sets `color-scheme: dark` on `:root`; there is no light-mode toggle or algorithmic theme switcher.
- **CSS methodology**: BEM-like class names scoped to feature areas (`.session-panel`, `.chat-view`, `.confirm-card`, `.evidence-card`, `.turn-group`, `.digest-bounded`, `.prose-bounded`). No CSS modules, no CSS-in-JS, no utility-first framework.
- **Responsive strategy**: Minimal breakpoints — an 860px breakpoint collapses the session panel width; the sidebar itself folds via Ant Design's `Sider` collapsed state, with a pinned `.mobile-menu-button` that opens a drawer below Ant Design's `lg` breakpoint (992px). There is no mobile-first grid system.
- **Accessibility**: A global `:focus-visible` rule forces a 2px accent outline with offset; `prefers-reduced-motion` disables the turn-arrival flash animation.
- **Bounded panes**: Views set a `--bounded-pane-max-height` CSS variable on wrappers; `.digest-bounded .ant-tabs-body-holder` and `.prose-bounded .ant-collapse-body` clamp scrolling inside those regions independently of the page scroll.
- **Spec anchoring**: Style decisions are cross-referenced to specs inline (e.g. `/* SPEC-023 R-1 */`, `/* SPEC-019 R-1 */`, `/* SPEC-020 R-4 */`, `/* SPEC-037 R-6 */`, `/* SPEC-063 R-5a */`, `/* SPEC-041 R-3 */`), tying visual changes back to feature requirements.

## Conventions and constraints

- All colors, radii, and fonts flow through `src/theme/tokens.ts`; bespoke CSS references the matching `--*` custom property rather than hard-coding hex values (observed throughout `global.css`).
- Ant Design components receive the `portalTheme` `ThemeConfig` so their internal tokens (backgrounds, borders, text colors, primary/accent/success/error/warning) derive from the same palette.
- The entire portal is dark-only; `color-scheme: dark` is declared globally and no alternate theme is provided.
- Responsive behavior is expressed as plain CSS `@media` queries against fixed pixel breakpoints (860px, 992px via Ant Design's `lg`); no responsive utility classes are used.
- Build-time constants (`__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__`) are injected via Vite's `define` so the Settings view can display the exact shipped dependency versions.
- The Vite dev server proxies `/api` to `http://localhost:8080` (the platform gateway) for local development.
- Styles are authored as a single global stylesheet; there is no per-component CSS file, no CSS-in-JS, no Tailwind config, and no SCSS pipeline.