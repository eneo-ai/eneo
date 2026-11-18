import { expect, test } from "bun:test";

type Ranges = Partial<Record<string, Record<string, string>>>;
type Lock = {
  workspaces: Record<string, Ranges>;
  packages: Record<string, [string, string, Ranges?, ...unknown[]]>;
};
const FIELDS = ["dependencies", "devDependencies", "optionalDependencies", "peerDependencies"];

// An exact resolution that every dependent's range already admits only freezes
// the package: bun.lock holds the fixed version without it.
test("every resolution lifts a version some dependent's range excludes", async () => {
  const pkg = await Bun.file(new URL("../package.json", import.meta.url)).json();
  const lock = Bun.JSONC.parse(
    await Bun.file(new URL("../bun.lock", import.meta.url)).text(),
  ) as Lock;
  const dependents = [
    ...Object.values(lock.workspaces),
    ...Object.values(lock.packages).map((entry) => entry[2] ?? {}),
  ];
  const redundant = Object.entries<string>(pkg.resolutions ?? {})
    .filter(([name, version]) =>
      dependents
        .flatMap((ranges) => FIELDS.map((field) => ranges[field]?.[name]))
        .every((range) => range === undefined || Bun.semver.satisfies(version, range)),
    )
    .map(([name, version]) => `${name}@${version}`);
  expect(redundant).toEqual([]);
});
