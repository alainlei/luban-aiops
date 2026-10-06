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

The operator portal (`products/operator-portal/web-ui`) is a React 19 / Vite application whose UI styling centers on **Ant Design v6** in its built-in dark algorithm, with a hand-authored design-token layer that mirrors Ant tokens as CSS custom properties for bespoke styles.

- Framework: React 19 + TypeScript + Vite (plugin-react).
- Component library: `antd` ^6.6.2 plus `@ant-design/icons` and `@ant-design/x` ^2.9.0.
- No CSS preprocessor — plain `.css` under `app/src/theme/global.css` (739 lines).
- No Tailwind, no CSS Modules, no styled-components; all bespoke styles live in one global stylesheet.
- Build tooling: Vite config injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time via `define`.

## Key files and packages

- `products/operator-portal/web-ui/app/package.json` — declares antd, @ant-design/icons, @ant-design/x, react, dayjs; Node ≥ 22.22.2 engine.
- `products/operator-portal/web-ui/app/vite.config.ts` — Vite + Vitest setup; injects version/dependency metadata into the bundle; serves `dist/` from `../dist`.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single source of truth for colors, radius, fonts; builds an Ant `ThemeConfig` using `antdTheme.darkAlgorithm`.
- `products/operator-portal/web-ui/app/src/theme/global.css` — root-level CSS custom properties mirroring `tokens.ts`; layout, chat workspace, evidence cards, HITL confirmation cards, markdown rendering, responsive breakpoints.
- `products/operator-portal/nginx.conf` — serves the built static assets at `/`.

## Architecture and conventions

### Dual token channel
`src/theme/tokens.ts` defines a `palette` object (bg, surface, surfaceAlt, border, text, textMuted, accent, accentHover, success, error, warning, codeBg, radius) and maps it onto an Ant Design `ThemeConfig`. The same values are redeclared as `--bg`, `--surface`, `--accent`, etc. CSS custom properties in `global.css` so:
- Ant components consume the JS `ThemeConfig`.
- Bespoke CSS selectors consume the CSS variables.

The file header explicitly states this is a verbatim port from the legacy portal's `styles.css` and ties it to SPEC-023 R-1 (dark theme).

### Dark-only palette
`:root { color-scheme: dark; }` locks the portal to a dark theme. There is no light-mode toggle or alternate token set in the codebase.

### Layout model
`global.css` defines a fixed app shell: a left sidebar (`app-shell .ant-layout-sider-children`) plus one active function view (`view-container`). On narrow screens (`max-width: 860px`) the session panel shrinks from 260px to 200px. A pinned `.mobile-menu-button` toggles between inline sidebar collapse and an off-canvas drawer depending on whether the viewport is below antd's `lg` breakpoint (992px).

### Domain-specific style modules inside one sheet
Despite being a single file, `global.css` is sectioned by feature with comments referencing specs:
- Chat workspace (SPEC-023 R-3): `.chat-view`, `.session-panel`, `.chat-messages`, `.composer-selection-bar`, `.turn-group`.
- Turn arrival animation (SPEC-034 R-1 / SPEC-035 R-4): `.turn-group.turn-arrived` with a 4s fade-out keyframe, suppressed under `prefers-reduced-motion: reduce`.
- Tool evidence groups (SPEC-011 R-4 parity): `.evidence-turn`, `.evidence-card`, `.evidence-pre` capped at 280px height.
- Sticky request banner: `.turn-request-banner` floats above scrolling transcript content.
- HITL confirmation cards (SPEC-020 R-4): `.confirm-card`, `.confirm-call`, `.confirm-execution`, recovery detail grid (SPEC-063 R-5a).
- Shared view chrome (SPEC-023 R-5): `.view-toolbar`, `.report-form`, `.incident-section`.
- Documents drawer bounded panes (SPEC-041 R-3): `.digest-bounded`, `.prose-bounded` use a single `--bounded-pane-max-height` variable set by the view.

### Typography
Fonts are declared once in both the Ant theme config and `body`: Inter for prose, JetBrains Mono / Fira Code for monospace. Markdown content under `.md-content` gets dedicated heading sizes, code block styling, table borders, and link/accent coloring.

### Responsive strategy
- CSS media query at `860px` for the session panel width.
- Relies on antd's built-in `lg` breakpoint (992px) for Sider auto-collapse behavior.
- `prefers-reduced-motion` suppresses the turn-arrival flash animation.

### Accessibility
`:focus-visible` is globally overridden to use the accent color with a 2px offset outline, ensuring keyboard focus remains visible on custom controls.

## Conventions and constraints

- **Design tokens are single-sourced in `tokens.ts` and mirrored into CSS custom properties.** The comment in `tokens.ts` says the palette is "ported verbatim from the legacy portal's :root design tokens" and that the CSS variables exist so "bespoke styles and antd components stay on one vocabulary" (SPEC-023 R-1 dark theme). Any new color must be added to both the JS `palette` and the `:root` CSS variables.
- **The portal is dark-only.** `color-scheme: dark` is set at `:root`; there is no alternate theme configuration.
- **Bespoke styles go in `global.css`, not per-component CSS files.** All domain-specific classes (chat, evidence, confirmations, bounded panes) live in the single stylesheet.
- **Spec-driven style changes are annotated.** Every major visual change in `global.css` is preceded by a comment citing the relevant spec requirement (e.g. `SPEC-023 R-3`, `SPEC-020 R-4`, `SPEC-034 R-1`, `SPEC-035 R-4`, `SPEC-037 R-6`, `SPEC-039 R-8`, `SPEC-041 R-3`, `SPEC-063 R-5a`). This is the repository's enforcement mechanism for traceability between visual changes and requirements.
- **Bounded scroll regions use a shared max-height convention.** Evidence pre blocks, digest tabs, and prose panes cap content at 280px (or a CSS-variable-driven `--bounded-pane-max-height`) so expanding large content does not push the transcript out of view.
- **Build-time injected constants**: `vite.config.ts` injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` into the bundle; the Settings view names the tech stack using these values.
- **No additional CSS framework or preprocessor is configured.** The project has no `tailwind.config.*`, no Sass/Less setup, no CSS-in-JS beyond Ant's own theme API.