import { NotFoundPage } from "nextra-theme-docs";

import { getDocsVersions, versionTitle } from "@/lib/versions";

// Also served by GitHub Pages as the site-wide 404.html, so it must make sense
// for a path under any version.
export default function NotFound() {
  const versions = getDocsVersions();

  return (
    <NotFoundPage content="Report this broken link">
      <h1 className="text-2xl font-bold">Page not found</h1>
      {versions.length > 1 && (
        <>
          <p className="mt-4">
            The page may exist in another version of the documentation:
          </p>
          <ul className="mt-2 list-disc pl-6">
            {versions.map((version) => (
              <li key={version.id}>
                <a href={version.basePath || "/"} className="underline">
                  {versionTitle(version)}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
    </NotFoundPage>
  );
}
