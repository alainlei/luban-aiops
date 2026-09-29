---
kind: frontend_style
name: Operator Portal Frontend Style — Ant Design Dark Theme with CSS Custom Properties Tokens
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/vite.config.ts
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
    - products/operator-portal/web-ui/app/src/main.tsx
    - products/operator-portal/web-ui/app/src/App.tsx
---

## What system/approach is used

The operator portal (`products/operator-portal/web-ui`) is a React 19 + Vite application that styles its UI through **Ant Design v6** configured via a centralized `ThemeConfig` and a parallel set of **CSS custom properties (design tokens)** consumed by bespoke component styles. The build toolchain is Vite with the React plugin, TypeScript, Vitest (jsdom), and an nginx reverse proxy for local dev.

There are no other frontend styling systems in this repository — all backend services are Python FastAPI/Starlette apps; the only browser-facing code lives under `products/operator-portal/web-ui/app/src/`.

## Key files and packages

- `app/package.json` — declares `antd`, `@ant-design/icons`, `@ant-design/x`, `react`, `react-dom`; Node ≥ 22.22.2.
- `app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs to `../dist` for nginx; proxies `/api` to `http://localhost:8080`.
- `app/src/theme/tokens.ts` — single source of truth palette (`bg`, `surface`, `surfaceAlt`, `border`, `text`, `textMuted`, `accent`, `success`, `error`, `warning`, `codeBg`, `radius`) and the `portalTheme: ThemeConfig` passed to Ant Design's `ConfigProvider`.
- `app/src/theme/global.css` — mirrors the same token values as CSS custom properties on `:root` (`--bg`, `--surface`, `--accent`, …) so non-Ant components and legacy ported styles consume one vocabulary; also defines layout, chat transcript, evidence cards, HITL confirmation cards, markdown rendering, sticky request banner, and bounded-pane panes.
- `app/src/main.tsx` — mounts `<ConfigProvider theme={portalTheme}>` around the app root.
- `app/src/App.tsx` — composes the antd `Layout` shell (Sider sidebar + content area) and routes views.

## Architecture and conventions

### Dual-token strategy (SPEC-023 R-1)
The design system is intentionally duplicated into two layers so both Ant Design components and hand-written CSS share one vocabulary:

1. **JS tokens** (`src/theme/tokens.ts`): exported `palette` object and `portalTheme` `ThemeConfig` that maps colors, border radius, fonts (`Inter` for body, `JetBrains Mono` / `Fira Code` for code) into Ant Design's dark algorithm.
2. **CSS tokens** (`:root` in `global.css`): identical color names as CSS variables (`--bg`, `--surface`, `--accent`, …) so bespoke selectors like `.session-item`, `.evidence-card`, `.confirm-card`, `.turn-request-banner` can reference them without importing the TS file.

This dual approach is documented inline in both files and referenced by SPEC numbers (SPEC-023 R-1 dark theme).

### Ant Design as the component library
Every view and feature module imports directly from `antd` (`Layout`, `Menu`, `Table`, `Modal`, `Tabs`, `Tag`, `Typography`, `Select`, `Alert`, `Pagination`, `Spin`, `Statistic`, `Collapse`, `Row`, `Col`, etc.). There is no wrapper component library or styled-components layer — styling is done by:
- Passing props to Ant Design primitives (e.g. `theme` prop, `colorPrimary` mapped to `palette.accent`).
- Adding small BEM-style class overrides in `global.css` when Ant's defaults need tweaking (e.g. `.ant-layout-sider-collapsed .ant-menu-item-group-title { display: none }` to replace group titles with hairline dividers in collapsed mode).

### Layout and responsive strategy
- A full-height `Layout.Sider` sidebar plus a single active function view forms the app shell. On desktop the Sider is inline; below Ant Design's `lg` breakpoint (~992px) it collapses to an icon rail, and a pinned `.mobile-menu-button` opens an off-canvas drawer instead.
- The chat workspace uses a fixed-width `.session-panel` (260px, shrinking to 200px at ≤860px) next to a flex column transcript.
- Content panes use `.view-container` (scrollable) or `.view-container-flush` (full-bleed, e.g. chat). Documents drawers use bounded panes via a CSS variable `--bounded-pane-max-height` applied per wrapper, shared between digest tabs and prose collapse sections.
- Reduced motion is respected via `@media (prefers-reduced-motion: reduce)` for the turn-arrival flash animation.

### Visual language
- Dark-only theme (`color-scheme: dark`, `algorithm: antdTheme.darkAlgorithm`).
- Accent color `#38bdf8` (light blue) used for links, focus outlines, active states, and arrival highlights.
- Semantic status colors: success `#4ade80`, error `#f87171`, warning `#fbbf24`.
- Monospace font stack for code blocks, tool names, and session IDs.
- Consistent `border-radius: 8px` across cards, inputs, and badges.

### Build-time versioning
Vite injects the platform version (read from the repo root `VERSION` file) and locked dependency versions (`__REACT_VERSION__`, `__ANTD_VERSION__`) so the Settings view can render an accurate tech-stack table.

## Conventions and constraints

- **All colors flow through `tokens.ts`**: new hues must be added to the `palette` object and mirrored in `:root` CSS variables; ad-hoc hex literals in component CSS are discouraged (the global sheet was ported verbatim from the legacy portal's `styles.css` to keep parity).
- **Ant Design dark theme is mandatory**: the `ConfigProvider` wraps the entire app with `portalTheme`; components should not override base colors with inline styles unless necessary.
- **Bespoke classes follow a flat naming scheme** in `global.css` (`.session-item`, `.evidence-card`, `.confirm-card`, `.turn-request-banner`, `.digest-bounded`, `.prose-bounded`) rather than scoped CSS modules or CSS-in-JS, keeping the stylesheet as the single place for layout and visual tweaks.
- **Responsive breakpoints are minimal**: the main ones are Ant Design's built-in `lg` (992px) for the sidebar collapse and a custom `max-width: 860px` for the session panel width change; there is no media-query-driven theme switcher.
- **Accessibility baseline**: `:focus-visible` gets a 2px accent outline; reduced-motion animations are disabled when requested; the app sets `color-scheme: dark` so OS-level dark-mode semantics apply.
- **No Tailwind, Styled Components, or CSS Modules**: the stack is strictly Ant Design + plain CSS custom properties + Vite.