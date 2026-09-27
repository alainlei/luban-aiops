---
kind: frontend_style
name: 'Operator Portal Styling: Ant Design Dark Theme + CSS Custom Properties'
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/vite.config.ts
    - products/operator-portal/web-ui/app/src/main.tsx
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
---

## What system/approach is used

The only frontend in the repository is the **operator-portal web UI** (`products/operator-portal/web-ui/app`). It is a React 19 + TypeScript application built with Vite and styled exclusively with **Ant Design v6** using its built-in `darkAlgorithm` theme. There is no Tailwind, Sass/SCSS, CSS Modules, or CSS-in-JS library beyond what Ant Design ships; styling is a combination of:

- A single shared `ThemeConfig` object that maps a hand-authored palette to Ant Design tokens.
- One global stylesheet (`src/theme/global.css`) defining CSS custom properties (design tokens) that mirror the JS palette so bespoke component styles can consume them via `var(--*)`.
- Plain `.css` class names scoped to feature areas (chat, approvals, evidence cards, HITL confirmations, bounded panes).

No other product directory contains frontend code — all other services are Python FastAPI-style backends.

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares `antd`, `@ant-design/icons`, `@ant-design/x`, `react`, `vite`, `vitest`; Node ≥22.22.2.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs to `../dist`; proxies `/api` to `http://localhost:8080` in dev.
- `products/operator-portal/web-ui/app/src/main.tsx` — wraps the app in `<ConfigProvider theme={portalTheme}>` and imports `./theme/global.css` once.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — defines the canonical `palette` object (`bg`, `surface`, `surfaceAlt`, `border`, `text`, `textMuted`, `accent`, `accentHover`, `success`, `error`, `warning`, `codeBg`, `radius: 8`) and exports `portalTheme: ThemeConfig` mapping those values into Ant Design's token surface (`colorPrimary`, `colorBgBase`, `colorBgContainer`, `colorBgElevated`, `colorBorder`, `colorText`, `colorTextSecondary`, `colorSuccess`, `colorError`, `colorWarning`, `borderRadius`, `fontFamily`, `fontFamilyCode`).
- `products/operator-portal/web-ui/app/src/theme/global.css` — declares `:root` CSS custom properties mirroring `tokens.ts`, sets `color-scheme: dark`, applies Inter + JetBrains Mono/Fira Code fonts, and contains all bespoke layout/style rules for chat, session panel, approvals inbox, evidence groups, sticky request banners, HITL confirmation cards, document bounded panes, and markdown rendering.
- `products/operator-portal/web-ui/nginx.conf` — serves the built `dist/` assets from the container root path.

## Architecture and conventions

1. **Single source of truth for colors**: The `palette` object in `tokens.ts` is the design-token source. `global.css` duplicates it as CSS variables (`--bg`, `--surface`, `--accent`, …) so non-Ant components can reference the same vocabulary. Comments in both files explicitly state they mirror each other (SPEC-023 R-1 dark theme).

2. **Dark-only theme**: `color-scheme: dark` is set on `:root`, and Ant Design's `darkAlgorithm` is the only algorithm configured. No light-mode toggle exists.

3. **Typography**: Sans-serif stack `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif` for body text; monospace stack `"JetBrains Mono", "Fira Code", monospace` for code, tool names, and evidence output. Both are declared in `tokens.ts` and reused in `global.css`.

4. **Layout model**: A full-height `app-shell` uses an antd `Layout.Sider` sidebar plus one active function view. On narrow screens (`max-width: 860px`) the session panel shrinks; comments note a future off-canvas drawer stage. A pinned mobile menu button appears at desktop breakpoints where the Sider auto-collapses.

5. **Component-scoped CSS classes**: All bespoke styles use BEM-like class names under feature namespaces (`.session-panel*`, `.chat-view`, `.evidence-*`, `.confirm-card*`, `.turn-group`, `.approvals-entry`, `.digest-bounded`, `.prose-bounded`). There are no CSS modules or component-scoped style files — everything lives in the single `global.css`.

6. **Bounded panes**: Scrollable sub-panes (digest tabs, prose collapse) share a single CSS variable `--bounded-pane-max-height` applied by the view, with max-height + overflow-y rules in `.digest-bounded .ant-tabs-body-holder` and `.prose-bounded .ant-collapse-body`.

7. **Accessibility**: `:focus-visible` gets a 2px solid accent outline with offset; `prefers-reduced-motion` disables the turn-arrival flash animation while keeping a subtle tint.

8. **Build-time versioning**: Platform, React, and Ant Design versions are baked into the bundle via `define` constants so the Settings page can display the exact shipped tech stack.

## Conventions and constraints

- **All new visual tokens must be added to `tokens.ts` first**, then mirrored in `global.css` `:root` variables. This dual-mirror is enforced by comments referencing SPEC-023 R-1 and by the fact that every color used outside Ant components references `var(--*)` rather than hard-coded hex values.
- **Ant Design components receive styling through the `ConfigProvider` theme**; ad-hoc overrides should go into `global.css` class selectors, not inline styles.
- **Markdown content is rendered into `.md-content` blocks** with a dedicated rule set (headings, lists, code, pre, blockquote, tables, links) ported from the legacy `styles.css`.
- **Evidence and HITL cards follow fixed visual contracts** documented via spec cross-references in comments (SPEC-011 R-4, SPEC-020 R-4, SPEC-034 R-1/R-4, SPEC-035 R-4, SPEC-037 R-6, SPEC-039 R-8, SPEC-041 R-3, SPEC-063 R-5a), ensuring consistent appearance across features.
- **Responsive behavior is minimal and breakpoint-driven**: the session panel narrows at 860px; the mobile menu button is positioned fixed at top-left when the sidebar collapses.
- **No CSS preprocessing**: there are no `.scss`/`.sass`/`.less` files and no PostCSS/Tailwind configuration — plain CSS is the entire styling pipeline.