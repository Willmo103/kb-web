# Live Server Route Audit Report

- **Date**: October 05, 2026 14:19:45
- **Target Server**: `https://kb-test.willmo.dev`
- **Audit Tool**: `curl` CLI via `live-server-test` skill
- **Scope**: Read-only site route integrity & authentication audit
- **Verdict Summary**: **20/20 routes PASSED**

---

## Route Audit Findings

| Category | Route | Status | Expected | Latency | Content-Type | Security Headers | Verdict | Notes |
|---|---|---|---|---|---|---|---|---|
| Public | `/api/health` | `200` | `200` | 0.138s | application/json | 3/3 | **PASS** | Health probe endpoint |
| Public | `/login` | `200` | `200` | 0.247s | text/html | 3/3 | **PASS** | User authentication login page |
| Public | `/manifest.json` | `200` | `200` | 0.107s | application/json | 3/3 | **PASS** | PWA manifest configuration |
| Public | `/favicon.ico` | `200` | `200,302,303,404` | 0.077s | image/vnd.microsoft.icon | 3/3 | **PASS** | Site favicon icon |
| Public | `/icon.png` | `200` | `200` | 0.115s | image/png | 3/3 | **PASS** | PWA touch icon asset |
| Public | `/sw.js` | `200` | `200` | 0.064s | application/javascript | 3/3 | **PASS** | PWA service worker script |
| UI Protected | `/` | `303` | `303` | 0.120s | N/A | 3/3 | **PASS** | -> ...tp%3A%2F%2Fkb-test.willmo.dev%2F |
| UI Protected | `/pages` | `303` | `303` | 0.092s | N/A | 3/3 | **PASS** | -> ...%2F%2Fkb-test.willmo.dev%2Fpages |
| UI Protected | `/sites` | `303` | `303` | 0.082s | N/A | 3/3 | **PASS** | -> ...%2F%2Fkb-test.willmo.dev%2Fsites |
| UI Protected | `/notes` | `303` | `303` | 0.082s | N/A | 3/3 | **PASS** | -> ...%2F%2Fkb-test.willmo.dev%2Fnotes |
| UI Protected | `/collections` | `303` | `303` | 0.085s | N/A | 3/3 | **PASS** | -> ...kb-test.willmo.dev%2Fcollections |
| UI Protected | `/conversations` | `303` | `303` | 0.095s | N/A | 3/3 | **PASS** | -> ...-test.willmo.dev%2Fconversations |
| UI Protected | `/reports` | `303` | `303` | 0.116s | N/A | 3/3 | **PASS** | -> ...F%2Fkb-test.willmo.dev%2Freports |
| UI Protected | `/reports/rag` | `303` | `303` | 0.086s | N/A | 3/3 | **PASS** | -> ...-test.willmo.dev%2Freports%2Frag |
| UI Protected | `/taxonomy` | `303` | `303` | 0.087s | N/A | 3/3 | **PASS** | -> ...%2Fkb-test.willmo.dev%2Ftaxonomy |
| UI Protected | `/workspaces` | `303` | `303` | 0.097s | N/A | 3/3 | **PASS** | -> ...Fkb-test.willmo.dev%2Fworkspaces |
| API Protected | `/api/sites` | `401` | `401` | 0.105s | application/json | 3/3 | **PASS** | REST Sites collection |
| API Protected | `/api/articles` | `401` | `401` | 0.086s | application/json | 3/3 | **PASS** | REST Articles collection |
| API Protected | `/api/tags` | `401` | `401` | 0.079s | application/json | 3/3 | **PASS** | REST Tags collection |
| API Protected | `/api/notes` | `401` | `401` | 0.082s | application/json | 3/3 | **PASS** | REST Notes collection |

---

## Security Posture & Guardrails
- **Read-Only Scope**: No state-changing requests or `/admin/*` operations were executed.
- **Authentication Enforcement**: Protected UI routes correctly reject unauthenticated requests with HTTP 303 redirects to `/login`.
- **API Gate**: Protected API routes correctly return HTTP 401 Unauthorized for unauthenticated callers.
- **Public Endpoints**: Core health probes (`/api/health`), login UI (`/login`), and PWA manifests (`/manifest.json`) are responsive and healthy.