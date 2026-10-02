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
    - products/operator-portal/web-ui/app/src/App.tsx
---

## What system/approach is used

The only frontend in this monorepo lives under `products/operator-portal/web-ui/` and is a React 19 + TypeScript SPA built with Vite (`@vitejs/plugin-react`). Visual styling is centered on **Ant Design v6** (`antd`, `@ant-design/icons`, `@ant-design/x`) configured via its `ThemeConfig` API, with a single global stylesheet for bespoke layout and component chrome.

There is no Tailwind, no CSS-in-JS library beyond Antd's own theme, no SCSS preprocessor, and no design-system package — just one `theme/` directory that holds the token definitions and the global stylesheet.

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares `react ^19`, `antd ^6.6.2`, `@ant-design/icons ^6`, `@ant-design/x ^2.9`, plus Vite/Vitest tooling.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single source of truth for the palette (bg/surface/surfaceAlt/border/text/textMuted/accent/accentHover/success/error/warning/codeBg) and radius; exports `portalTheme: ThemeConfig` using `antdTheme.darkAlgorithm`.
- `products/operator-portal/web-ui/app/src/theme/global.css` — 739-line stylesheet defining CSS custom properties on `:root` that mirror `tokens.ts` verbatim, plus all bespoke layout classes (`.app-shell`, `.sidebar-*`, `.chat-view`, `.session-panel`, `.turn-group`, `.confirm-card`, `.md-content`, evidence panes, bounded-pane helpers).
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs to `../dist` for nginx serving.
- `products/operator-portal/web-ui/app/src/App.tsx` — root antd `<Layout>` shell; drives sidebar/drawer state, role-gated menu entries, and view routing.
- `products/operator-portal/nginx.conf` — serves the built static assets.

## Architecture and conventions

**Dual-token vocabulary.** `tokens.ts` defines the JS-side `palette` object consumed by `portalTheme`; `global.css` re-declares the same values as CSS custom properties (`--bg`, `--surface`, `--accent`, …). The comment in `tokens.ts` states the intent explicitly: "CSS custom properties in global.css mirror these so bespoke styles and antd components stay on one vocabulary (SPEC-023 R-1 dark theme)." This lets Antd components get colors from `ThemeConfig` while hand-written CSS reads `var(--accent)` etc., keeping both paths synchronized.

**Dark-only theme.** `color-scheme: dark` is set on `:root`, and `portalTheme.algorithm = antdTheme.darkAlgorithm`. There is no light-mode toggle or algorithm switcher in the codebase.

**Component composition over style inheritance.** Most UI is built from Antd primitives (`Layout.Sider`, `Menu`, `Drawer`, `Button`, `Tag`, `Alert`, `Typography`, `Spin`) rather than custom styled elements. Bespoke overrides live in `global.css` targeting Antd selectors (e.g. `.ant-layout-sider-collapsed .ant-menu-item-group-title`, `.ant-tabs-body-holder`, `.ant-collapse-body`).

**Bounded pane pattern.** Shared panes use a CSS variable `--bounded-pane-max-height` set inline by the view, then applied via `.digest-bounded .ant-tabs-body-holder { max-height: var(--bounded-pane-max-height); overflow-y: auto }` and the equivalent for collapse panes. Code blocks and evidence panels cap content at `max-height: 280px` to keep transcripts scrollable.

**Responsive strategy.** Desktop uses an inline `Layout.Sider` (width 230, collapsedWidth 64) with `breakpoint="lg"` (antd's 992px). Below that width a fixed-position `.mobile-menu-button` opens a left `Drawer` with the full menu. A narrower `@media (max-width: 860px)` rule shrinks the session panel to 200px. No mobile-first breakpoints drive layout changes inside component files.

**Accessibility conventions.** `:focus-visible` gets a 2px accent outline; navigation buttons carry `aria-label`s; the mobile menu button toggles between "Open navigation" / "Show navigation" / "Hide navigation" based on viewport state.

**Spec-driven annotations.** Many CSS comments reference SPEC numbers (SPEC-019, SPEC-020, SPEC-023, SPEC-034, SPEC-035, SPEC-037, SPEC-039, SPEC-041, SPEC-063), tying visual behavior to requirements such as turn arrival flash animations, HITL confirmation cards, signed-execution receipts, and bounded document panes.

## Conventions and constraints

- All color/radius/font tokens flow through `src/theme/tokens.ts` → `portalTheme` for Antd and `:root` CSS variables for bespoke styles; new palette values should be added in both places (enforced by the mirroring comment referencing SPEC-023 R-1).
- The portal is dark-only; no light-theme configuration exists.
- Layout is expressed in plain CSS classes in `global.css` (BEM-style names like `.app-shell`, `.view-container`, `.session-panel`, `.turn-group`, `.confirm-card`, `.approvals-entry`, `.evidence-*`, `.md-content`) rather than CSS modules or styled-components.
- Responsive behavior is breakpoint-driven via CSS media queries and Antd's `breakpoint="lg"` prop, not via a utility framework.
- Build-time constants (`__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__`) are injected by `vite.config.ts` and surfaced to the Settings view for the tech-stack inventory table.
- Production output goes to `web-ui/dist`, served by the product's `nginx.conf`; development proxies `/api` to `http://localhost:8080`.