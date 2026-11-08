// @vitest-environment jsdom
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { PageFrame } from "./page-frame";

afterEach(cleanup);

const srcDir = path.resolve(import.meta.dirname, "../..");

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(directory, entry.name);
    if (entry.isDirectory()) return sources(file);
    return /\.tsx$/.test(entry.name) && !/\.test\.tsx$/.test(entry.name) ? [file] : [];
  });
}

describe("PageFrame", () => {
  it("puts the page in one centred 1152 px column inside the page inset", () => {
    render(
      <PageFrame className="gap-6">
        <p>Sidans innehåll</p>
      </PageFrame>
    );
    const column = screen.getByText("Sidans innehåll").parentElement!;
    for (const name of ["mx-auto", "w-full", "max-w-6xl", "gap-6"]) {
      expect(column.classList).toContain(name);
    }
    // A phone's 16 px inset, held either way; 24 px otherwise.
    expect([...column.parentElement!.classList]).toEqual(
      expect.arrayContaining(["p-4", "wide:p-6"])
    );
  });

  it("is the only place a page is centred: a page caps its width on the shared left edge", () => {
    // What centres itself on purpose: the column, Konto's own settings frame,
    // the full-screen editors, the chat's reading column, a document's prose
    // and an icon's preview.
    const allowed = [
      "components/composites/page-frame.tsx",
      "components/composites/sectioned-settings.tsx",
      "components/composites/icon-field.tsx",
      "features/account/",
      "features/chat/",
      "features/spaces/chat/",
      "features/workspace/preview/"
    ];
    const centred = sources(srcDir)
      .map((file) => path.relative(srcDir, file).split(path.sep).join("/"))
      .filter((file) => !allowed.some((prefix) => file.startsWith(prefix)))
      .filter((file) => /\bmx-auto\b/.test(readFileSync(path.join(srcDir, file), "utf8")));
    expect(centred).toEqual([]);
  });
});
