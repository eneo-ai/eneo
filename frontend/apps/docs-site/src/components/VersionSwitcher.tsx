"use client";

import { usePathname } from "next/navigation";
import type { ChangeEvent } from "react";

import { type DocsVersion, versionTitle } from "@/lib/versions";
import { splitDocsPath, versionTargets } from "@/lib/languages";

interface VersionSwitcherProps {
  versions: DocsVersion[];
  current: DocsVersion;
}

export default function VersionSwitcher({
  versions,
  current,
}: VersionSwitcherProps) {
  // usePathname() excludes the basePath, so it can be re-rooted under another version.
  const pathname = usePathname();
  const { language } = splitDocsPath(pathname);

  if (versions.length < 2) return null;

  async function onChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = versions.find((version) => version.id === event.target.value);
    if (!next || next.id === current.id) return;

    let target = next.basePath || "/";
    const candidates = versionTargets(next.basePath, pathname);
    for (const candidate of candidates) {
      try {
        // Both page and language availability can differ in another version.
        const response = await fetch(candidate, { method: "HEAD" });
        if (response.ok) {
          target = candidate;
          break;
        }
      } catch {
        // Offline: use the known version root.
        break;
      }
    }
    const samePage =
      target === `${next.basePath}${pathname}` ||
      target === `${next.basePath}${splitDocsPath(pathname).page}`;
    window.location.assign(
      target + window.location.search + (samePage ? window.location.hash : ""),
    );
  }

  return (
    <select
      aria-label={
        language === "sv" ? "Dokumentationens version" : "Documentation version"
      }
      value={current.id}
      onChange={onChange}
      className="h-8 rounded-md border border-gray-300 bg-transparent px-2 text-sm text-gray-700 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 dark:border-neutral-700 dark:text-gray-200 dark:hover:border-neutral-500"
    >
      {versions.map((version) => (
        <option key={version.id} value={version.id}>
          {versionTitle(version, language)}
        </option>
      ))}
    </select>
  );
}
