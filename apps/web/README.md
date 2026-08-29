# exposure-web

The desk's two pages — the book workbench (`/`) and the issuer workspace
(`/issuer/[ticker]`) — plus the analyst dock, the evidence column and the
portfolio dialog that sit over both.

Everything here is a client component talking to the API over one transport
(`lib/http.ts`). There is no server-side data fetching and no route handler: the
API is a separate container behind the same origin, and `NEXT_PUBLIC_API_URL` is
**inlined at build time**, so changing it in `.env` under a running container
does nothing at all — the image has to be rebuilt.

## Next 16 — what actually differs from what an agent expects

`AGENTS.md` says to read `node_modules/next/dist/docs/` before writing code.
These are the four things that turned out to matter for this app (read
2026-08-29 against 16.2.9); the rest of the upgrade guide is about features this
app does not use.

- **Request APIs are async, with no synchronous compatibility left.** `params`
  in a page and `searchParams` are Promises. The issuer page already does the
  right thing — `use(params)` in a client component, `useSearchParams()` behind
  a `<Suspense>` boundary — and the boundary is not optional: without one, a
  production build fails outright rather than degrading.
  (`01-getting-started/18-upgrading.md`, `02-guides/upgrading/version-16.md`.)

- **`cacheComponents` is off, so nothing preserves state across navigation.**
  With Cache Components enabled, Next keeps the previous route mounted under
  React's `<Activity>` and state survives a navigation for free. It is not
  enabled here (`next.config.ts` sets only `output: "standalone"`), so the
  pre-Activity rule applies: **state that must survive `/` → `/issuer/AAPL`
  has to be hoisted into the shared layout or an external store.** That is why
  the analyst dock lives at the layout level rather than in each page.
  (`02-guides/preserving-ui-state.md`.)

- **Turbopack is the default bundler** for `dev` and `build`. Nothing in this
  app configures a bundler, so this is invisible — worth knowing only because a
  webpack-shaped answer to a build question would be the wrong answer.

- **Next no longer overrides `scroll-behavior` during navigation.** If a global
  `scroll-behavior: smooth` is ever added to `globals.css`, route changes will
  animate their scroll unless `<html>` carries `data-scroll-behavior="smooth"`.
  There is no such rule today; this is a note for whoever adds one.

## Layout

```
app/
  layout.tsx            ClerkProvider (only with a publishable key) + fonts
  page.tsx              the book workbench
  issuer/[ticker]/      the issuer workspace
  components/           shared surfaces (analyst dock, evidence, timeline, …)
lib/
  http.ts               the ONE transport — the token is attached in one place
  api.ts / issuer.ts    typed clients over it
  types.ts              the wire shapes, mirroring apps/api
  errors.ts             a server refusal -> a sentence a person can act on
  formatting.ts         money / percent / date / duration
```

## Checks

There is no front-end test runner. What stands in for one:

```bash
npx tsc --noEmit          # the wire shapes and the components agree
npx next build            # the production build the image runs
```

plus two Python guards that read this directory as text, so the two languages
cannot drift apart silently:

- `tests/test_error_vocabulary.py` — every code `lib/errors.ts` explains is one
  the API actually raises.
- `tests/test_ui_surface.py` — the reader's layer renders no internal ids and no
  transport strings (V13).

## Local

```bash
npm run dev     # :3000, expects the API on :8103
```
