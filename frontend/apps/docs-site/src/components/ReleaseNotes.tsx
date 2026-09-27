import {
  releases,
  type EntryType,
  type Release,
  type ReleaseEntry,
} from "@eneo/whats-new";

const TYPE_LABEL: Record<EntryType, string> = {
  new: "New",
  improved: "Improved",
  fixed: "Fixed",
};

const TYPE_CLASS: Record<EntryType, string> = {
  new: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200",
  improved: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200",
  fixed: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200",
};

// Typed exhaustively against the package; unknown values (a newer schema than
// this build) fall back to the raw value instead of failing the docs build.
const AREA_LABEL: Record<ReleaseEntry["area"], string> = {
  chat: "Chat",
  assistants: "Assistants",
  knowledge: "Knowledge",
  spaces: "Spaces",
  skills: "Skills",
  account: "Account",
  admin: "Administration",
  platform: "Platform",
};

function formatDate(date: string): string {
  // "YYYY-MM-DD" via new Date() is UTC midnight; build as a local date.
  const [year, month, day] = date.split("-").map(Number);
  return new Intl.DateTimeFormat("en-GB", { dateStyle: "long" }).format(
    new Date(year, month - 1, day),
  );
}

function Entry({ entry, version }: { entry: ReleaseEntry; version: string }) {
  // Ids are unique within a release only; every release shares this page.
  const anchor = `v${version}-${entry.id}`;
  return (
    <li
      id={anchor}
      className="rounded-lg border border-gray-200 p-4 dark:border-neutral-800"
    >
      <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
        <span
          className={`rounded-full px-2 py-0.5 ${TYPE_CLASS[entry.type] ?? ""}`}
        >
          {TYPE_LABEL[entry.type] ?? entry.type}
        </span>
        <span className="rounded-full border border-gray-300 px-2 py-0.5 dark:border-neutral-700">
          {AREA_LABEL[entry.area] ?? entry.area}
        </span>
        {entry.audience === "admin" && (
          <span className="rounded-full bg-gray-100 px-2 py-0.5 dark:bg-neutral-800">
            Administrators
          </span>
        )}
      </div>
      <h3 className="mt-2 text-base font-semibold">
        <a href={`#${anchor}`} className="no-underline hover:underline">
          {entry.title.en}
        </a>
      </h3>
      <p className="mt-1 text-sm leading-relaxed text-gray-600 dark:text-gray-300">
        {entry.body.en}
      </p>
    </li>
  );
}

function ReleaseSection({ release }: { release: Release }) {
  const anchor = `v${release.version}`;
  return (
    <section aria-labelledby={anchor} className="mt-10">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 id={anchor} className="text-xl font-semibold">
          <a href={`#${anchor}`} className="no-underline hover:underline">
            Version {release.version}
          </a>
        </h2>
        <span className="text-sm text-gray-500">
          {release.date ? formatDate(release.date) : "Upcoming"}
        </span>
      </div>
      <ul className="mt-4 flex list-none flex-col gap-4 p-0">
        {release.entries.map((entry) => (
          <Entry key={entry.id} entry={entry} version={release.version} />
        ))}
      </ul>
    </section>
  );
}

/** Renders every release in @eneo/whats-new, newest first. English only on the docs site. */
export default function ReleaseNotes() {
  if (releases.length === 0) {
    return <p className="mt-6 text-gray-500">No release notes yet.</p>;
  }
  return (
    <div>
      {releases.map((release) => (
        <ReleaseSection key={release.version} release={release} />
      ))}
    </div>
  );
}
