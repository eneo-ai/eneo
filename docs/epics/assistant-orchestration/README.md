# Assistant orchestration design — #1150 and #1151

Editable sources and images for the proposed group-chat and shared-space
orchestration design. The GitHub issues own the scope and acceptance criteria.
These pictures illustrate planned behavior, not a released feature.

The presentation follows the HTML-to-PNG approach used in epic #660 and the
Marketplace epic #546. `style.css` adapts the style from
`docs/epics/skill-scripts/style.css` at
`811c4ae046e59762d5fb5ff728b40c1294ea4f1b`.

| Source | Export | Purpose |
| --- | --- | --- |
| `overview.html` | `orchestration-overview.png` | Ownership, boundaries and later space reuse |
| `flow.html` | `orchestration-flow.png` | Two specialists and a focused follow-up |
| `chat.html` | `orchestration-chat.png` | Working and completed conversation states |
| `proof.html` | `orchestration-proof.png` | The first task's proof and failure cases |

## Regenerate

Open any source file directly in a browser; all assets are local. The `.page`
element is 800 CSS pixels wide. Export it at device scale factor 2 for a
1600-pixel-wide PNG.

With Playwright and its Chromium browser already available:

```sh
node render.mjs
```

The script renders four static pages sequentially in one browser, checks for
horizontal overflow, and closes the browser on success or failure. It starts no
server. On the shared Mac, invoke it through the mandatory global supervisor:

```sh
python3 /Users/maxeriksson/.codex/scripts/run-guarded.py --seconds 60 -- node render.mjs
```

Use `NODE_PATH` to point to an existing Playwright installation if needed.
Do not install dependencies or start an application server to render these
standalone diagrams.

Inspect every exported image before replacing the issue's image links. Link to
an immutable commit so later branch changes do not silently replace the design.
Keep the explanatory text and technical details in the issues available to
readers who cannot use the images.
