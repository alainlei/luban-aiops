---
kind: frontend_style
name: 'Operator Portal Styling: Ant Design + CSS Custom Properties Dark Theme'
category: frontend_style
scope:
    - '**'
source_files:
    - products/operator-portal/web-ui/package.json
    - products/operator-portal/web-ui/app/src/main.tsx
    - products/operator-portal/web-ui/app/src/theme/tokens.ts
    - products/operator-portal/web-ui/app/src/theme/global.css
    - products/operator-portal/web-ui/app/src/App.tsx
---

## What system/approach is used

The only frontend in the repository is the **Operator Portal** (`products/operator-portal/web-ui`), a React SPA built with Vite and styled via:

- **Ant Design v6** (`antd`, `@ant-design/icons`, `@ant-design/x`) as the component library.
- A **dark theme** applied through Ant Design's `ConfigProvider` using `antdTheme.darkAlgorithm` plus a hand-authored `ThemeConfig`.
- **CSS custom properties (design tokens)** declared on `:root` in `src/theme/global.css` and mirrored in `src/theme/tokens.ts`; bespoke styles consume the CSS variables while Ant components consume the JS `ThemeConfig`.
- Plain CSS files — no Tailwind, Sass, Styled Components, or Emotion styling in application code. The only Emotion presence is transitive (`@emotion/hash`, `@emotion/unitless` pulled in by Ant).

There is no second UI surface; backend services are pure Python FastAPI apps with no embedded HTML/CSS.

## Key files and packages

- `products/operator-portal/web-ui/package.json` — declares `react ^19`, `antd ^6.6.2`, `@ant-design/x ^2.9.0`, `vite ^8`, `typescript ~5.9`, `vitest ^4`.
- `products/operator-portal/web-ui/app/src/main.tsx` — root entry that mounts `<ConfigProvider theme={portalTheme}>` and imports `./theme/global.css`.
- `products/operator-portal/web-ui/app/src/theme/tokens.ts` — single source of truth for palette, radius, font families, and the `portalTheme: ThemeConfig` object.
- `products/operator-portal/web-ui/app/src/theme/global.css` — global base styles, design-token CSS variables, layout chrome (sidebar, chat view, evidence cards, HITL confirmation cards, markdown rendering, bounded panes).
- `products/operator-portal/web-ui/app/src/App.tsx` — top-level shell that passes `theme="dark"` to Ant Layout/Sider/Menu components.
- `products/operator-portal/web-ui/nginx.conf` — serves the built static assets from `dist/`.

## Architecture and conventions

### Dual token vocabulary

`tokens.ts` defines a `palette` record (`bg`, `surface`, `surfaceAlt`, `border`, `text`, `textMuted`, `accent`, `accentHover`, `success`, `error`, `warning`, `codeBg`, `radius`) and maps it into an Ant Design `ThemeConfig`. `global.css` declares the same values as CSS custom properties under `:root` (`--bg`, `--surface`, `--accent`, …). The comment at the top of both files states the intent explicitly: "Design tokens mirror src/theme/tokens.ts; antd components consume the ThemeConfig, bespoke styles consume these custom properties." This dual mapping keeps Ant components and hand-written CSS on one color vocabulary.

### Dark-only theme

The portal is dark-only. `color-scheme: dark` is set on `:root`, `algorithm: antdTheme.darkAlgorithm` is configured, and every Ant component in `App.tsx` receives `theme="dark"`. There is no light-mode toggle or algorithm switcher.

### Component-library-first, CSS override-second

Layout and chrome are built from Ant Design primitives (`Layout`, `Sider`, `Menu`, `Typography`, `Tabs`, `Collapse`, `Button`). Bespoke CSS classes (e.g. `.app-shell`, `.view-container`, `.chat-view`, `.session-panel`, `.confirm-card`, `.evidence-card`, `.turn-request-banner`, `.digest-bounded`, `.prose-bounded`) style the surrounding structure and content regions. Where Ant defaults conflict with the design, selectors target Ant's internal class names directly (e.g. `.ant-layout-sider-collapsed .ant-menu-item-group-title`, `.ant-tabs-body-holder`, `.ant-collapse-body`).

### Feature-scoped CSS modules

All visual features live in the single `global.css` file rather than per-component CSS modules. Each feature area is sectioned with a comment header referencing its spec requirement (e.g. `/* --- Chat workspace (SPEC-023 R-3) --- */`, `/* --- HITL confirmation cards (SPEC-020 R-4) --- */`, `/* --- Tool evidence groups (SPEC-011 R-4 parity) --- */`, `/* --- Sticky request banner --- */`, `/* --- Shared view chrome (SPEC-023 R-5) --- */`, `/* --- Documents drawer bounded panes (SPEC-041 R-3, v0.25.1 polish) --- */`).

### Responsive strategy

Responsive behavior is minimal and breakpoint-driven:

- A pinned `.mobile-menu-button` appears at `top: 12px; left: 12px` and toggles between inline sidebar collapse (desktop) and an off-canvas drawer (below Ant Design's `lg` breakpoint of 992px).
- A single `@media (max-width: 860px)` shrinks `.session-panel` from 260px to 200px.
- `prefers-reduced-motion: reduce` disables the 4s turn-arrival flash animation.

No fluid typography, container queries, or mobile-first grid system is used.

### Bounded panes pattern

Long-form content (markdown pre blocks, tool evidence output, document digest/narrative panes) is constrained to a fixed height via a CSS variable `--bounded-pane-max-height` set by the view, then scrolled independently inside `.digest-bounded .ant-tabs-body-holder` and `.prose-bounded .ant-collapse-body`. Code blocks use a hard-coded `max-height: 280px` with their own scrollbar so they do not push transcript content out of view.

### Typography

Fonts are declared in the Ant Design theme config: sans-serif stack `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif` and monospace stack `"JetBrains Mono", "Fira Code", monospace`. Both stacks are also referenced directly in `global.css` for bespoke elements.

### Accessibility conventions observed

- `color-scheme: dark` is set on `:root`.
- A global `:focus-visible` rule draws a 2px accent outline with 2px offset on custom controls.
- `prefers-reduced-motion` is respected for animations.
- Semantic HTML (`<summary>` for native expanders, `<dl>/<dt>/<dd>` for recovery facts) is used alongside Ant primitives.

## Conventions and constraints

Observed conventions (descriptive):

- All colors, radii, and fonts flow from `src/theme/tokens.ts`; new palette values should be added there and mirrored in `global.css`'s `:root` block.
- New bespoke styles go in `src/theme/global.css` under a clearly labeled section referencing the governing SPEC requirement.
- Ant Design components are wrapped in `ConfigProvider` at the app root with `portalTheme`; individual components receive `theme="dark"` where needed.
- Long content areas use the bounded-pane pattern (`--bounded-pane-max-height` + `.digest-bounded` / `.prose-bounded`) rather than unbounded scrolling containers.
- No Tailwind, Sass, CSS-in-JS, or utility-first framework is used in this repo.

Enforced rules (from authoritative sources):

- `package.json` pins Node engine to `>=22.22.2` and uses Vite as the dev server and bundler; building runs `tsc --noEmit && vite build`.
- `main.tsx` is the single mount point and always renders `ConfigProvider` with `portalTheme` before `App`; adding a new entrypoint would bypass the theme unless it replicates this wrapper.
- `global.css` is imported once in `main.tsx`; it is the sole stylesheet consumed by the app.
- The comments in `tokens.ts` and `global.css` state the design-token mirroring contract between the JS `ThemeConfig` and the CSS custom properties, which is the de facto convention keeping Ant components and bespoke CSS aligned.