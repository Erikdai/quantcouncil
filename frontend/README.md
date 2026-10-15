# FinAgent Web

Web console for FinAgent, a multi-agent LLM research and paper-trading platform for China A-shares.

Vite · React 19 · TypeScript (strict) · Tailwind CSS v4 · TanStack Query v5 · React Router v7 · lightweight-charts v5 · react-markdown

- **Dashboard** `/`: start a run, recent runs, watchlist, service health
- **Run** `/runs/:id`: live agent pipeline over SSE, reports, debates, candles, risk gate, human approval, execution, LLM eval
- **Paper account** `/portfolio`: KPIs, hash-chained ledger check, positions (T+1), orders, reset
- **Research** `/research`: streaming RAG chat with citations, document ingest, retrieval-mode comparison
- **Skills** `/skills`: Agent Skills and their SKILL.md

UI in Chinese or English (follows the browser, switchable in the header), light/dark themes, A-share colours (red = up, green = down).

## Develop

Requires Node.js >= 22.12.

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to http://localhost:8000
```

Point the proxy elsewhere with `VITE_API_TARGET=http://host:port npm run dev`.

## Build

```bash
npm run typecheck  # tsc -b
npm run build      # type-check, then bundle to dist/
npm run preview    # serve dist/ (also proxies /api)
```

## Docker

Multi-stage image: `node:22-alpine` builds, `nginx:1.27-alpine` serves `dist/` with SPA fallback and proxies `/api/` to `http://api:8000` (SSE-safe: no buffering, 1 h read timeout).

```bash
docker build -t finagent-web .
docker run -p 8080:80 --network <compose-network> finagent-web   # needs a service named `api`
```

## Layout

```
src/api         types.ts (mirrors finagent/api/schemas.py), client.ts, sse.ts (SSE parser, useRunEvents, streamChat)
src/i18n        zh.ts / en.ts dictionaries (same typed key set), store + I18nProvider / useT()
src/hooks       React Query hooks, useRunView (persisted run + live events), useResearchChat
src/components  ui/, common/ (Markdown, candles, badges), layout/, dashboard/, run/, research/
src/pages       one lazily loaded page per route
src/lib         formatting, constants, theme, toasts, debate parsing
```
