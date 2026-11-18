/**
 * The app's route paths from routeTree.gen.ts, with every parameter written as
 * `$` and every splat or optional segment as `*`.
 */
export function viteRoutePaths(source) {
  const body = source.match(/\binterface FileRoutesByFullPath\s*\{([\s\S]*?)\n\}/)?.[1];
  if (body === undefined) throw new Error("Missing FileRoutesByFullPath declaration");
  const routes = body
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      const route = line.match(/^\s*(['"])(\/.*?)\1\s*:/)?.[2];
      if (!route) throw new Error(`Unsupported FileRoutesByFullPath entry: ${line.trim()}`);
      return (
        "/" +
        route
          .split("/")
          .filter(Boolean)
          .map((part) => {
            if (part === "$" || /^\{-\$[^{}]+\}$/.test(part)) return "*";
            if (/[{}]/.test(part)) throw new Error(`Unsupported route brace syntax: ${route}`);
            return part.startsWith("$") ? "$" : part;
          })
          .join("/")
      );
    });
  return [...new Set(routes)];
}
