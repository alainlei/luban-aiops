---
kind: frontend_style
name: Operator Portal Styling — Ant Design Dark Theme + CSS Custom Properties Tokens
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
    - products/operator-portal/web-ui/app/vite.config.ts
    - products/operator-portal/web-ui/app/package.json
---

## Approach

The only frontend in the repository is the **operator-portal** (`products/operator-portal/web-ui/app`). It is a React 19 + TypeScript SPA built with Vite and styled with:

- **Ant Design v6** (`antd`, `@ant-design/icons`, `@ant-design/x`) as the component library.
- A **dark-only theme** driven by Ant Design's `ThemeConfig` plus `darkAlgorithm`.
- A single shared palette expressed as both a TypeScript constant (`src/theme/tokens.ts`) and mirrored into CSS custom properties on `:root` (`src/theme/global.css`).
- No CSS-in-JS, no Tailwind, no SCSS — plain `.css` imported once from the app entry.

There is no design-token system beyond this pair of files; there are no responsive breakpoints defined in CSS (the layout relies on Ant Design's Sider auto-collapse at its `lg` breakpoint, ~992px) and no dark/light toggle — `color-scheme: dark` is set globally.

## Key Files

| File | Role |
|---|---|
| `products/operator-portal/web-ui/app/src/theme/tokens.ts` | Single source of truth for colors, radius, fonts; builds the `portalTheme: ThemeConfig` passed to Ant Design. |
| `products/operator-portal/web-ui/app/src/theme/global.css` | Global base styles, CSS custom property tokens, layout chrome (sidebar, session panel, chat transcript, evidence cards, HITL confirmation cards, document panes). |
| `products/operator-portal/web-ui/app/vite.config.ts` | Injects `__PLATFORM_VERSION__`, `__REACT_VERSION__`, `__ANTD_VERSION__` at build time; outputs hashed assets to `../dist`. |
| `products/operator-portal/web-ui/app/package.json` | Declares `react`, `antd`, `@ant-design/x`, `@ant-design/icons`, `vite`, `vitest`. |
| `products/operator-portal/nginx.conf` | Serves the built `web-ui/dist` directory. |

## Architecture and Conventions

### Token model

`tokens.ts` defines a `palette` object (`bg`, `surface`, `surfaceAlt`, `border`, `text`, `textMuted`, `accent`, `accentHover`, `success`, `error`, `warning`, `codeBg`, `radius`) and maps it onto Ant Design's token surface (`colorPrimary`, `colorBgBase`, `colorBgContainer`, `colorBgElevated`, `colorBorder`, `colorText`, `colorTextSecondary`, `colorSuccess`, `colorError`, `colorWarning`, `borderRadius`, `fontFamily`, `fontFamilyCode`). The comment explicitly states these values were "ported verbatim from the legacy portal's :root design tokens" and that the CSS custom properties mirror them so bespoke styles and Ant Design components share one vocabulary. This is documented as part of **SPEC-023 R-1 dark theme**.

The same palette is re-declared as CSS custom properties under `:root` in `global.css` (`--bg`, `--surface`, `--accent`, etc.) so non-Ant Design CSS can consume them via `var(--accent)`, `var(--surface)`, `var(--radius)`, etc.

### Component styling strategy

- Ant Design components receive the `portalTheme` config at the app root; their internal tokens follow the palette.
- Custom UI chrome (sidebar, session list, chat transcript, evidence groups, HITL confirmation cards, approval inbox entries, document panes) is written as plain CSS classes in `global.css` using BEM-style names prefixed by domain (e.g. `.session-panel`, `.chat-messages`, `.confirm-card`, `.evidence-card`, `.approvals-entry`, `.digest-bounded`, `.prose-bounded`).
- There is no per-component stylesheet; all global overrides live in the single `global.css` file.

### Responsive behavior

Responsive handling is minimal:

- Ant Design's `Layout.Sider` auto-collapses below its `lg` breakpoint (~992px); the code comments note that below this width the sidebar becomes an off-canvas drawer instead of inline.
- A narrow-viewport media query (`@media (max-width: 860px)`) narrows `.session-panel` from 260px to 200px.
- A `prefers-reduced-motion` rule disables the turn-arrival flash animation.
- No mobile-first grid or utility framework is used.

### Accessibility conventions observed

- `color-scheme: dark` is set globally.
- A global `:focus-visible` rule gives a 2px accent outline with offset.
- The `turn-group.turn-arrived` animation has a `prefers-reduced-motion` fallback.
- Comments call out keyboard focus visibility on custom controls.

### Build-time versioning

`vite.config.ts` reads the repo-level `VERSION` file and the local `package-lock.json` to inject `__PLATFORM_VERSION__`, `__REACT_VERSION__`, and `__ANTD_VERSION__` constants at build time. The comment ties this to SPEC-023 R-1 and notes that `make validate-version` asserts the platform version constant propagates to this injection point. Output filenames are content-hashed so assets are immutable-cacheable while `index.html` stays no-store.

## Conventions and Constraints

- **Dark-only**: `color-scheme: dark` is set on `:root`; no light theme exists.
- **Single token source**: Colors, radius, and fonts are declared once in `tokens.ts` and mirrored into CSS custom properties; bespoke styles must use `var(--*)` rather than hard-coded hex values.
- **Ant Design tokens over overrides**: Visual changes go through the `portalTheme` `ThemeConfig` token map rather than ad-hoc CSS overrides of Ant Design internals.
- **CSS class naming**: Custom classes use descriptive kebab-case prefixes scoped to feature area (`.session-*`, `.chat-*`, `.confirm-*`, `.evidence-*`, `.approvals-*`, `.view-toolbar`, `.digest-bounded`, `.prose-bounded`).
- **Spec-linked styles**: Many style blocks carry comments referencing the originating spec requirement (e.g. `SPEC-023 R-1`, `SPEC-023 R-3`, `SPEC-024`, `SPEC-034 R-1`, `SPEC-035 R-4`, `SPEC-037 R-6`, `SPEC-039 R-8`, `SPEC-041 R-3`), tying visual decisions back to requirements.
- **Bounded scrollable panes**: Large content areas (fenced code blocks, tool evidence, digest/prose panes) are capped at `max-height: 280px` with their own overflow scroll so they do not push the surrounding transcript out of view.
- **No Tailwind / SCSS / CSS modules**: The dependency manifest and build config show none of these tools; the styling approach is plain CSS + Ant Design.