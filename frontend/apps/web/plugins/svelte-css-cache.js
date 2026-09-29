// @ts-check
/**
 * Compile a component before Svelte handles its virtual CSS request.
 *
 * vite-plugin-svelte 5 can receive CSS before the component after a restart or
 * dependency-cache hit. Without a populated CSS cache its load hook falls
 * through to Vite's file loader, which passes the entire .svelte file to
 * Tailwind as CSS.
 *
 * @returns {import("vite").Plugin}
 */
export function svelteCssCache() {
  /** @type {import("vite").ViteDevServer | undefined} */
  let server;
  return {
    name: "eneo:svelte-css-cache",
    apply: "serve",
    enforce: "pre",
    configureServer(devServer) {
      server = devServer;
    },
    async load(id) {
      const separator = id.indexOf("?");
      if (!server || separator === -1) return null;
      const filename = id.slice(0, separator);
      const query = new URLSearchParams(id.slice(separator + 1));
      if (
        !filename.endsWith(".svelte") ||
        !query.has("svelte") ||
        query.get("type") !== "style" ||
        query.has("raw") ||
        query.has("direct") ||
        query.has("url")
      )
        return null;

      // transformRequest reuses Vite's compiled module cache for warm requests.
      // Svelte's own loader then returns its correctly scoped, preprocessed CSS.
      await server.transformRequest(filename);
      return null;
    }
  };
}
