export type DocsLanguage = "en" | "sv";

export function splitDocsPath(pathname: string): {
  language: DocsLanguage;
  page: string;
} {
  const swedish = /^\/sv(?:[/?#]|$)/.test(pathname);
  const page = (swedish ? pathname.slice(3) : pathname) || "/";
  return {
    language: swedish ? "sv" : "en",
    page: page.startsWith("/") ? page : `/${page}`,
  };
}

export function languagePath(page: string, language: DocsLanguage): string {
  const canonical = splitDocsPath(page).page;
  return language === "sv"
    ? `/sv${canonical === "/" ? "" : canonical}`
    : canonical;
}

// Assets, external URLs, fragments and explicitly versioned links are not pages.
export function localizeDocsHref(href: string, language: DocsLanguage): string {
  return /^\/(?:$|[?#]|(?:docs|guides|contributing|about|sv)(?:[/?#]|$))/.test(
    href,
  )
    ? languagePath(href, language)
    : href;
}

export function sourceForPage(
  pathname: string,
  sourceRoutes: ReadonlySet<string>,
) {
  const { language, page } = splitDocsPath(pathname);
  const translated = languagePath(page, language);
  const fallback = language === "sv" && !sourceRoutes.has(translated);
  return { language, page, source: fallback ? page : translated, fallback };
}

export function publishedRoutes(sourceRoutes: readonly string[]): string[] {
  // English owns the page inventory. A translation cannot introduce a feature
  // which does not exist in this version's English source.
  return sourceRoutes
    .filter((route) => splitDocsPath(route).language === "en")
    .flatMap((route) => [route, languagePath(route, "sv")]);
}

export function hasSwedishPages(sourceRoutes: ReadonlySet<string>): boolean {
  return [...sourceRoutes].some((route) => {
    const { language, page } = splitDocsPath(route);
    return language === "sv" && sourceRoutes.has(page);
  });
}

export function versionTargets(basePath: string, pathname: string): string[] {
  const { language, page } = splitDocsPath(pathname);
  return [
    ...new Set([
      `${basePath}${languagePath(page, language)}`,
      `${basePath}${page}`,
      `${basePath}${languagePath("/", language)}`,
      basePath || "/",
    ]),
  ];
}
