# Eneo Frontend

Multirepo containing:
- The Eneo Web GUI, a SvelteKit app in `/apps/web`
- The Intric.js API client, a plain JS client wrapping all Intric endpoints used in the Web GUI in `packages/intric.js`
- The Intric UI Library, offering reusable Svelte components for our frontend applications in `packages/ui`

## Setup
### Installing
```bash
bun -w run setup
```
Will install all required dependencies. Have a look at the README files in the respective subfolders for further instructions.

### Local dev server
If you want to develop the Web GUI while also working on the UI librart at the same time run
```bash
bun -w run dev
```
This will start the dev task in all relevant subfolders. More info in the `app/web` directory.

### Formatting & Linting

Prettier is configured for this project, you can format your code before committing either through a format action in your code editor, or by running:

```bash
bun run format
```

The same goes for linting, you can run it via

```bash
bun run lint
```

__Hint:__ The linter will also check formatting, so it makes sense to first format your code befor running the linter.
