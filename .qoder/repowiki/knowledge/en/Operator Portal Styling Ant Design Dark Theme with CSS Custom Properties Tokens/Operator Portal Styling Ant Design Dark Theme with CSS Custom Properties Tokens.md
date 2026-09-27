---
kind: frontend_style
name: 'Operator Portal Styling: Ant Design Dark Theme with CSS Custom Properties Tokens'
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/app/package.json
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
---

# Operator Portal Frontend Style System

## Approach

The only frontend in the repository is the **operator-portal** (`products/operator-portal/web-ui/app/`), a React 19 + TypeScript SPA built with Vite and styled via **Ant Design v6** (`antd`, `@ant-design/icons`, `@ant-design/x`). There is no Tailwind, SCSS, CSS-in-JS (other than Antd's own theme config), or component library of its own — styling is a thin layer over Ant Design.

The design system has two synchronized vocabularies:

1. **TypeScript tokens** in `app/src/theme/tokens.ts` define a `palette` object and an Ant Design `ThemeConfig` (`portalTheme`) using `antdTheme.darkAlgorithm`. This drives Ant Design components' colors, radii, fonts, and elevation.
2. **CSS custom properties** in `app/src/theme/global.css` mirror the same palette as `--bg`, `--surface`, `--accent`, `--border`, `--text`, `--success`, `--error`, `--warning`, `--code-bg`, `--radius`, etc., so bespoke (non-Antd) styles can consume the same vocabulary.

The comment at the top of `tokens.ts` states the intent explicitly: "Palette ported verbatim from the legacy portal's :root design tokens" and "the CSS custom properties in global.css mirror these so bespoke styles and antd components stay on one vocabulary (SPEC-023 R-1 dark theme)."

## Key Files

- `products/operator-portal/web-ui/app/package.json` — declares `antd ^6.6.2`, `@ant-design/icons ^6.0.0`, `@ant-design/x ^2.9.0`, React 19, Vite 8, Vitest.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single source of truth for the color palette, border radius, and font families; exports `portalTheme` consumed by Ant Design.
- `products/operator-portal/web-ui/app/src/theme/global.css` — root-level stylesheet defining `:root` CSS variables, base resets, layout chrome (sidebar, drawer, view containers), chat transcript, HITL confirmation cards, markdown rendering, evidence groups, sticky request banners, and bounded panes.
- `products/operator-portal/web-ui/vite.config.ts` — Vite configuration that imports `global.css` (build pipeline).

## Architecture and Conventions

- **Dark-only theme**: `color-scheme: dark` is set on `:root`; there is no light-mode toggle or algorithm switch in the codebase.
- **Token synchronization**: every color/radius/font used by bespoke CSS appears both in `tokens.ts` (for Antd) and in `global.css` `:root` (for hand-written selectors). The spec references `SPEC-023 R-1 dark theme` are embedded as comments throughout `global.css` to tie visual decisions back to requirements.
- **BEM-like class naming**: bespoke classes use flat kebab-case names scoped to feature areas (e.g. `.session-panel`, `.chat-messages`, `.confirm-card`, `.turn-group`, `.approvals-entry`, `.evidence-card`, `.digest-bounded`, `.prose-bounded`). No CSS modules, no CSS-in-JS, no shadow DOM.
- **Ant Design overrides via ThemeConfig**: component-level styling goes through the `portalTheme` passed into Antd providers rather than ad-hoc CSS overrides. Where Antd's default layout needs adjustment (e.g. collapsed sider menu group titles clipped to rail width), targeted selectors under `.ant-layout-sider-collapsed` are added in `global.css`.
- **Responsive strategy**: CSS media queries are minimal. A breakpoint at `860px` narrows `.session-panel` from 260px to 200px. The sidebar uses Antd's built-in `lg` breakpoint (992px) for auto-collapse, and a pinned `.mobile-menu-button` opens an off-canvas drawer below that breakpoint. No mobile-first framework is used.
- **Accessibility**: `:focus-visible` gets a 2px accent outline globally; `prefers-reduced-motion` disables the turn-arrival animation; semantic `<summary>` elements are used for native expanders inside confirmation cards and recovery details.
- **Markdown/evidence styling**: a shared `.md-content` scope styles headings, lists, code blocks, blockquotes, links, tables, and preformatted output (bounded to `max-height: 280px`); evidence groups follow the same visual language.
- **Bounded panes**: document drawers use a CSS variable `--bounded-pane-max-height` set per wrapper, applied via `.digest-bounded .ant-tabs-body-holder` and `.prose-bounded .ant-collapse-body` so structural chrome stays pinned while content scrolls.

## Conventions and Constraints

- All bespoke UI classes live in `global.css`; component files import it once and do not define their own CSS. Observed across all views under `app/src/views/` and `app/src/chat/`.
- Color values are never hard-coded in JSX/CSS selectors; they reference CSS custom properties (`var(--accent)`, `var(--surface)`, `var(--border)`, `var(--text-muted)`, `var(--code-bg)`, `var(--radius)`).
- Spec-driven traceability: comments in `global.css` cite the originating requirement (e.g. `SPEC-023 R-1`, `SPEC-019 R-1`, `SPEC-024`, `SPEC-034 R-1`, `SPEC-035 R-4`, `SPEC-037 R-6`, `SPEC-039 R-8`, `SPEC-041 R-3`, `SPEC-063 R-5a`), tying each visual change to a spec.
- Font families are centralized: sans-serif defaults to `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif`; monospace defaults to `"JetBrains Mono", "Fira Code", monospace` — both declared in `tokens.ts` and repeated in `global.css` body/md-content rules.
- The build enforces TypeScript compilation before bundling (`tsc --noEmit && vite build`), so any TS-side type errors (including unused token usage patterns) fail the build.

No other product in the monorepo contains frontend styling code; all remaining products are Python services served by nginx or exposed through the platform gateway.