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

# Operator Portal Frontend Style

## System and Approach

The operator portal (`products/operator-portal/web-ui/app`) is a React 19 / Vite 8 / TypeScript SPA whose styling centers on **Ant Design v6** in dark mode, with a single global stylesheet for bespoke layout and component chrome.

- **Component library**: `antd` ^6.6.2 plus `@ant-design/icons` ^6.0.0 and `@ant-design/x` ^2.9.0 (chat-specific extensions).
- **Build tooling**: Vite 8 with `@vitejs/plugin-react`; no Sass/Less/PostCSS pipeline — plain `.css` files only.
- **Theme source of truth**: `app/src/theme/tokens.ts` defines a `palette` object and an Ant Design `ThemeConfig` (`portalTheme`) using `antdTheme.darkAlgorithm`. The same palette values are mirrored as CSS custom properties under `:root` in `app/src/theme/global.css` so that bespoke styles and Ant Design components consume one vocabulary.
- **Responsive strategy**: CSS media queries only; the app shell uses Ant Design's `Layout.Sider` which auto-collapses at its `lg` breakpoint (992px), with a pinned `.mobile-menu-button` opening an off-canvas drawer below that threshold. A second breakpoint at 860px narrows the session panel width.
- **Accessibility baseline**: `color-scheme: dark`, `box-sizing: border-box` reset, and a `:focus-visible` rule forcing a 2px accent outline with 2px offset.

## Key Files

- `products/operator-portal/web-ui/app/package.json` — declares antd, @ant-design/x, react, vite, vitest.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` via `define`; serves built assets from `../dist` behind nginx.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single design-token definition (`palette` + `portalTheme`).
- `products/operator-portal/web-ui/app/src/theme/global.css` — ~740 lines of base styles, layout, chat workspace, markdown rendering, HITL confirmation cards, evidence groups, sticky request banner, and bounded panes.
- `products/operator-portal/web-ui/nginx.conf` — serves the static build at `/`.

## Architecture and Conventions

### Dual token surface

`tokens.ts` and `global.css` are kept in sync by hand. The comment in `tokens.ts` states the intent explicitly:

> Palette ported verbatim from the legacy portal's :root design tokens (styles.css). The CSS custom properties in global.css mirror these so bespoke styles and antd components stay on one vocabulary (SPEC-023 R-1 dark theme).

This means there is no runtime theme switcher — the app is dark-only (`color-scheme: dark`), and all colors flow through the shared palette rather than ad-hoc hex literals in components.

### Ant Design customization

Components receive the `portalTheme` via Ant Design's `ConfigProvider` (consumed elsewhere in the app tree). Tokens mapped include `colorPrimary`, `colorBgBase`, `colorBgContainer`, `colorBgElevated`, `colorBorder`, `colorText`, `colorSuccess/Error/Warning`, `borderRadius`, and fonts (`Inter` for body, `JetBrains Mono` / `Fira Code` for code). No Ant Design overrides are done via CSS-in-JS; visual tweaks live in `global.css` targeting Ant Design class names (e.g. `.ant-layout-sider-collapsed .ant-menu-item-group-title`).

### Global stylesheet organization

`global.css` is organized by feature area with comments referencing spec requirements:

- App shell and sidebar (`.app-shell`, `.sidebar-footer`, `.mobile-menu-button`).
- Chat workspace (`.chat-view`, `.session-panel`, `.chat-messages`, `.turn-group`).
- Markdown content renderer (`.md-content` — headings, code blocks capped at 280px, tables, blockquotes).
- Tool evidence groups (`.evidence-turn`, `.evidence-card`, `.evidence-pre`).
- Sticky request banner (`.turn-request-banner`).
- HITL confirmation cards (`.confirm-card`, `.confirm-call`, `.confirm-execution-recovery`).
- Shared view chrome (`.view-toolbar`, `.report-form`).
- Bounded panes (`.digest-bounded`, `.prose-bounded`) driven by a CSS variable `--bounded-pane-max-height` set per wrapper.

### Responsive behavior

- Desktop: inline sidebar + one active function view.
- Below 992px (Ant Design `lg`): Sider auto-collapses; a fixed-position `.mobile-menu-button` opens a drawer instead.
- Below 860px: session panel shrinks from 260px to 200px.
- Reduced motion: `.turn-group.turn-arrived` animation is disabled when `prefers-reduced-motion: reduce`.

### Spec-driven style gates

Style decisions are cross-referenced to specs throughout the stylesheet (e.g. `SPEC-023 R-1`, `SPEC-019 R-1`, `SPEC-024`, `SPEC-034 R-1`, `SPEC-035 R-4`, `SPEC-037 R-6`, `SPEC-039 R-8`, `SPEC-041 R-3`, `SPEC-063 R-5a`). This is the repository's primary enforcement mechanism for UI consistency — new UI features should add matching spec references in their CSS comments.

## Conventions and Constraints

- **Dark-only theme**: `color-scheme: dark` is set globally; no light-mode toggle exists.
- **Single palette**: Colors come from `tokens.ts` → CSS custom properties; avoid raw color literals in components.
- **No CSS modules / no SCSS**: Styles are plain CSS imported once into the app root; there is no per-component stylesheet convention.
- **Bounded scrollable regions**: Long content areas (code blocks, evidence pre, digest/prose panes) use a fixed `max-height` (280px for code/evidence, CSS-variable-driven for panes) with internal overflow scrolling so they do not push the transcript out of view.
- **Spec-linked comments**: Every significant visual change is annotated with the owning SPEC number and requirement letter, making the spec document the de facto style contract.
- **Font policy**: Body uses `Inter` with system fallbacks; monospace everywhere uses `"JetBrains Mono", "Fira Code"`.
- **Focus visibility**: All interactive elements must remain keyboard-accessible; the global `:focus-visible` rule enforces a visible accent-colored outline.
- **Build-time version injection**: `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` are injected via Vite `define` so the Settings view can display the exact shipped tech stack.