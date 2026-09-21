# @eneo/widget-loader

The script a website includes to show an Eneo assistant as a chat widget.
It registers the `<eneo-widget>` custom element (a launcher button in a
shadow root) and, on first open, an iframe with the embed page served from
the Eneo origin. All chat UI, tokens and API calls live inside the iframe;
the loader only owns placement, focus and a small `postMessage` bridge.

Built with Vite library mode to a classic IIFE (`dist/eneo.js`, es2019, no
dependencies) so it works with `async` in any CMS. The build writes
`dist/manifest.json` (version, SRI hash, sizes) and fails when the bundle
exceeds **5 kB gzipped**. The web app serves the bundle from
`/widget/v1/eneo.js` (floating) and `/widget/<version>/eneo.js` (pinned,
immutable, for hosts that require `integrity`).

## Host snippet

```html
<script async src="https://eneo.example.se/widget/v1/eneo.js" data-widget-id="wgt_…"></script>
```

Optional `data-*` attributes (also usable as attributes on a hand-written
`<eneo-widget>` element for single-page apps):

| Attribute      | Values                                            | Default                     |
| -------------- | ------------------------------------------------- | --------------------------- |
| `lang`         | `sv`, `en`                                        | the page's `<html lang>`    |
| `position`     | `bottom-right`, `bottom-left`                     | `bottom-right`              |
| `color-scheme` | `auto`, `light`, `dark`                           | `auto`                      |
| `auto-open`    | `true`                                            | closed                      |
| `launcher`     | `none` (host renders its own)                     | built-in button             |
| `label`        | accessible name of the button                     | "Öppna chatt" / "Open chat" |
| `frame-title`  | accessible name of the iframe                     | "Chatt" / "Chat"            |
| `prefetch`     | `true` (load before first open)                   | lazy                        |
| `preview`      | preview token from the admin page (draft widgets) | none                        |

The launcher takes the widget's primary colour (and its dark-mode colour when
the page is dark) as soon as the embed page reports ready. CSS custom
properties on the element or `:root` override it: `--eneo-widget-color`,
`--eneo-widget-on-color`, `--eneo-widget-radius`, `--eneo-widget-z`,
`--eneo-widget-offset-x`, `--eneo-widget-offset-y`. Parts: `launcher`, `panel`.

## JavaScript API

`window.Eneo` is a command queue, so calls made before the script has
loaded are replayed:

```html
<script>
  window.Eneo =
    window.Eneo ||
    function () {
      (window.Eneo.q = window.Eneo.q || []).push(arguments);
    };
  Eneo("on", "conversation_started", function (detail) {
    /* analytics */
  });
</script>
<button onclick="Eneo('open')">Ask us</button>
```

Commands: `open`, `close`, `toggle`, `on(event, listener)`, `off(event, listener)`,
`setContext({ page_url, page_title })`. Events: `ready`, `open`, `close`,
`conversation_started`, `unread`. The same events are dispatched on the element
as `eneo-widget:<event>` DOM events. Events carry no visitor or conversation
identifiers; `conversation_started` only says that one began. `setContext` is accepted and parsed by the
embed page but not used by the chat yet, so no page context reaches Eneo.

## Accessibility

The launcher is a `<button aria-haspopup="dialog" aria-expanded aria-controls>`
with a visible focus ring; the iframe has a title. Opening moves focus into the
iframe, `Escape` inside it closes the panel and focus returns to the launcher
(or to the element that was focused when the launcher is hidden). Below 640 px
the panel is full-screen and follows the visual viewport so the on-screen
keyboard never covers the composer. Transitions respect `prefers-reduced-motion`.

## Development

```bash
bun run --filter @eneo/widget-loader build   # dist/eneo.js + manifest.json, size budget
bun run --filter @eneo/widget-loader test    # builds, then Vitest in headless Chromium
```

The web app's `/widget/...` route reads `dist/` at build time and answers 503
until the package has been built.
