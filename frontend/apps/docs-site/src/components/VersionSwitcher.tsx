"use client";

import { usePathname } from "next/navigation";
import type { ChangeEvent } from "react";

import { type DocsVersion, versionTitle } from "@/lib/versions";

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

  if (versions.length < 2) return null;

  async function onChange(event: ChangeEvent<HTMLSelectElement>) {
    const next = versions.find((version) => version.id === event.target.value);
    if (!next || next.id === current.id) return;

    const root = next.basePath || "/";
    const samePage = pathname === "/" ? root : `${next.basePath}${pathname}`;
    let target = root;
    try {
      // Every version is a separate static build; the page may not exist there.
      const response = await fetch(samePage, { method: "HEAD" });
      if (response.ok) target = samePage;
    } catch {
      // Offline or blocked HEAD request: fall back to the version root.
    }
    window.location.assign(target);
  }

  return (
    <select
      aria-label="Documentation version"
      value={current.id}
      onChange={onChange}
      className="h-8 rounded-md border border-gray-300 bg-transparent px-2 text-sm text-gray-700 hover:border-gray-400 focus:outline-none focus:ring-2 focus:ring-primary-500 dark:border-neutral-700 dark:text-gray-200 dark:hover:border-neutral-500"
    >
      {versions.map((version) => (
        <option key={version.id} value={version.id}>
          {versionTitle(version)}
        </option>
      ))}
    </select>
  );
}
