"use client";

import { usePathname } from "next/navigation";
import { languagePath, splitDocsPath } from "@/lib/languages";

export default function LanguageSwitcher() {
  const pathname = usePathname();
  const { language, page } = splitDocsPath(pathname);
  return (
    <select
      aria-label={
        language === "sv" ? "Dokumentationens språk" : "Documentation language"
      }
      value={language}
      className="h-8 rounded-md border border-gray-300 bg-transparent px-2 text-sm dark:border-neutral-700"
      onChange={(event) => {
        const next = event.target.value === "sv" ? "sv" : "en";
        // A document navigation resets Pagefind's language-specific singleton.
        window.location.assign(
          `${process.env.NEXT_PUBLIC_BASE_PATH || ""}${languagePath(page, next)}${window.location.search}${window.location.hash}`,
        );
      }}
    >
      <option value="en" lang="en">
        English
      </option>
      <option value="sv" lang="sv">
        Svenska
      </option>
    </select>
  );
}
