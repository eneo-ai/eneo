import { cache } from "react";
import { generateStaticParamsFor } from "nextra/pages";
import { sourceForPage } from "./languages";

export const getSourceRoutes = cache(async () => {
  const params = await generateStaticParamsFor("mdxPath")();
  return new Set(
    params.map(
      ({ mdxPath }) =>
        `/${Array.isArray(mdxPath) ? mdxPath.filter(Boolean).join("/") : mdxPath}`,
    ),
  );
});

export async function resolveContent(mdxPath: string[] = []) {
  return sourceForPage(`/${mdxPath.join("/")}`, await getSourceRoutes());
}
