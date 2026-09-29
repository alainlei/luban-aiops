Two-layer product: a Vite/React 19 + TypeScript SPA under `web-ui/app/src/` and an nginx runtime (`Dockerfile`, `nginx.conf`) that serves hashed assets at `/`, no-store SPA fallback for client routing, and proxies `/api/` and `/health/` to `platform-gateway:8000` with request-id forwarding.

SPA layering inside `src/`:
- Shell & navigation: `main.tsx` bootstraps antd `ConfigProvider` + `AuthProvider`; `App.tsx` owns the two-column layout, role-gated sidebar sections (Chat, Control, Workspace), and routes `ViewId` strings to view components.
- Auth: `auth/AuthContext.tsx` exposes OIDC login/logout/token-refresh via `auth/oidc.ts` and persists sessions in `auth/storage.ts`.
- Domain views: `views/audit/`, `views/control/` (Approvals, Permissions, Settings, Skills, Tools), `views/incidents/`, `views/workspace/` — each is a feature folder with colocated `__tests__/`.
- Chat domain: `chat/` holds the multi-session chat UI plus helpers (`markdown.ts`, `toolNames.ts`, `transcript.ts`, `useToolNames.ts`).
- Streaming transport: `stream/` isolates SSE decoding (`decoder.ts`), transport abstraction (`transport.ts`), shared models (`models.ts`), and the `useChatStream` hook; tests live beside sources.
- Session state: `sessions/useSessionWorkspace.ts` provides per-mode (operation vs development) session lists and pinning, consumed by both Chat and incident/document views.
- API clients: `api/client.ts` centralizes fetch configuration; `api/{approvals,documents,incidents,sessions}.ts` are thin typed wrappers over `/api/v1/*` endpoints, with `api/models.ts` for model catalog.
- Theme: `theme/tokens.ts` + `global.css` provide antd theme overrides.

Dependency direction is one-way: views → chat/stream/api → auth/session; there is no cross-view import. Role gating is centralized in `roles.ts` (`hasAnyRole`, `*_ROLES` constants) and mirrored on every route entry and API call, with server-side enforcement documented as the authoritative boundary.