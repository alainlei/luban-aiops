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
    - products/operator-portal/web-ui/app/src/App.tsx
---

## What system/approach is used

The operator portal (`products/operator-portal/web-ui`) is a React 19 + TypeScript SPA built with **Vite** and styled primarily through the **Ant Design (antd) v6** component library. The visual theme is a **dark-only palette** ported from the legacy portal's `:root` design tokens into a single source of truth, then mirrored between:

1. A JavaScript token file (`app/src/theme/tokens.ts`) that exports an `antd` `ThemeConfig` using `antdTheme.darkAlgorithm`.
2. A global stylesheet (`app/src/theme/global.css`) that defines matching CSS custom properties on `:root` so bespoke styles and antd components consume one vocabulary.

There is no Tailwind, SCSS, or CSS-in-JS styling framework beyond antd's built-in theming. Component-level styling uses plain CSS classes in `global.css` (BEM-style names like `.session-item`, `.confirm-card`, `.evidence-pre`).

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares `antd ^6.6.2`, `@ant-design/icons ^6.0.0`, `@ant-design/x ^2.9.0`, React 19, Vite 8, Vitest for tests.
- `products/operator-portal/web-ui/app/vite.config.ts` — injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs to `../dist` served by nginx.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — central palette (`bg`, `surface`, `accent`, `success`, `error`, `warning`, `border`, `text`, `textMuted`, `codeBg`, `radius`) and the `portalTheme: ThemeConfig` applied via antd's dark algorithm.
- `products/operator-portal/web-ui/app/src/theme/global.css` — root `:root` CSS variables mirroring `tokens.ts`, plus all bespoke view chrome (sidebar, chat transcript, evidence cards, HITL confirmation cards, sticky request banner, markdown rendering, bounded panes).
- `products/operator-portal/web-ui/app/src/App.tsx` — top-level antd `Layout.Sider`/`Layout.Content` shell, drawer-based navigation on narrow screens, role-gated menu entries.

## Architecture and conventions

### Single-source design tokens
The palette is defined once in `tokens.ts` as a `const` object and reused to construct both the antd `ThemeConfig` and the `:root` CSS variables in `global.css`. Comments explicitly state the mirror relationship and tie it to SPEC-023 R-1 (dark theme). Any new color must be added to both places to stay consistent.

### Ant Design as the UI foundation
All interactive primitives (Layout, Menu, Drawer, Button, Tag, Badge, Alert, Spin, Typography, Avatar, Collapse, Tabs) come from antd. The app sets `theme="dark"` on Layout and Menu, and the `portalTheme` overrides antd's default dark tokens (primary color, background layers, borders, text colors, border radius, fonts). Font families are centralized: `Inter` sans-serif for prose, `JetBrains Mono` / `Fira Code` monospace for code.

### Bespoke CSS coexists alongside antd
Custom layout and component chrome live in `global.css` under semantic class names (`.app-shell`, `.view-container`, `.chat-view`, `.session-panel`, `.confirm-card`, `.evidence-card`, `.turn-request-banner`, `.digest-bounded`, `.prose-bounded`). These classes reference the CSS variables rather than hard-coded colors, keeping bespoke styles on the same palette as antd components.

### Responsive strategy
- Desktop: antd `Layout.Sider` with `breakpoint="lg"` (992px) auto-collapses to a 64px icon rail; a pinned `.mobile-menu-button` toggles collapse.
- Narrow viewport (`max-width: 860px` in CSS, `991px` in JS `useNarrowViewport`): the inline sidebar folds and a left-placed `Drawer` provides the full labeled menu.
- A `prefers-reduced-motion` media query disables the turn-arrival flash animation.

### Build-time version injection
`vite.config.ts` reads the repo root `VERSION` and the lockfile to define `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` constants consumed by the Settings view's tech stack table. This ensures the shipped bundle's dependency versions match what the UI reports.

### Markdown and content rendering
A shared `.md-content` rule set in `global.css` styles rendered markdown (headings, lists, code blocks, tables, blockquotes, links) consistently across views, using the portal palette variables.

## Conventions and constraints

- **Dark theme only**: `color-scheme: dark` is declared on `:root`; there is no light-mode toggle.
- **Token parity**: every color used by antd via `portalTheme` has a corresponding `--*` CSS variable in `global.css`; comments document this as a requirement tied to SPEC-023 R-1.
- **No per-component CSS modules or scoped styles**: all bespoke styles are global classes in `global.css`, relying on BEM-style naming to avoid collisions.
- **Responsive breakpoints are synchronized**: the JS `useNarrowViewport` hook and the CSS `@media (max-width: 860px)` rule share the same breakpoint intent (drawer vs. inline sidebar), though the exact pixel values differ slightly between JS and CSS.
- **Accessibility baseline**: `:focus-visible` gets a 2px accent outline; the mobile menu button includes descriptive `aria-label` text that changes based on current state.
- **Content bounds**: long-form content (fenced code blocks, tool evidence, bounded panes) is capped at `max-height: 280px` with its own scrollbar so scrolling never pushes the transcript out of view.
- **Build output**: the Vite build writes to `../dist` and produces content-hashed filenames for immutable caching while `index.html` stays no-store, as documented in the vite config comment referencing SPEC-023 R-1.