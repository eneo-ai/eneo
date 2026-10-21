"use client";

import { useEffect, useState } from "react";

import {
  type DocsLanguage,
  languageAtLocation,
  languagePath,
} from "@/lib/languages";
import { getDocsVersions, versionTitle } from "@/lib/versions";

const versions = getDocsVersions();

// Also served by GitHub Pages as the site-wide 404.html, so it answers any
// path under any version. The export is English; the address decides the
// language once the page has hydrated.
export default function NotFound() {
  const [language, setLanguage] = useState<DocsLanguage>("en");
  const [pathname, setPathname] = useState("");
  useEffect(() => {
    const detected = languageAtLocation(
      window.location.pathname,
      versions.map((version) => version.basePath),
    );
    setPathname(window.location.pathname);
    if (detected !== "en") {
      setLanguage(detected);
      document.documentElement.lang = detected;
    }
  }, []);
  const sv = language === "sv";
  const issue = new URL("https://github.com/eneo-ai/eneo/issues/new");
  issue.searchParams.set(
    "title",
    sv
      ? `Trasig länk: ${pathname}`
      : `Found broken "${pathname}" link. Please fix!`,
  );
  issue.searchParams.set("labels", "bug");

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center">
      <h1 className="text-2xl font-bold">
        {sv ? "Sidan finns inte" : "Page not found"}
      </h1>
      {versions.length > 1 && (
        <>
          <p className="mt-4">
            {sv
              ? "Sidan kan finnas i en annan version av dokumentationen:"
              : "The page may exist in another version of the documentation:"}
          </p>
          <ul className="mt-2 list-disc pl-6">
            {versions.map((version) => (
              <li key={version.id}>
                <a
                  href={`${version.basePath}${languagePath("/", language)}`}
                  className="underline"
                >
                  {versionTitle(version, language)}
                </a>
              </li>
            ))}
          </ul>
        </>
      )}
      <a className="mt-6 underline" href={issue.href}>
        {sv ? "Rapportera den trasiga länken" : "Report this broken link"}
      </a>
    </div>
  );
}
