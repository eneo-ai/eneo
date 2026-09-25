// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { installAstryxDomStubs, renderInApp } from "@/features/spaces/testing/render";
import type { InfoBlob } from "./knowledge";

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { text: "" }, response: new Response("{}") })
  }
}));

import { BlobTable } from "./blobs";

beforeAll(installAstryxDomStubs);
afterEach(cleanup);

const blob = (id: string, title: string, size: number) =>
  ({ id, metadata: { title, size } }) as unknown as InfoBlob;

const names = () =>
  within(screen.getByRole("table"))
    .getAllByRole("button", { name: /^\S+\.pdf$/ })
    .map((button) => button.textContent);

describe("BlobTable", () => {
  it("keeps the upload order until a header sorts it", async () => {
    const { container } = renderInApp(
      <BlobTable
        blobs={[blob("1", "b.pdf", 300), blob("2", "ö.pdf", 100), blob("3", "a.pdf", 200)]}
        canEdit
      />
    );

    expect(names()).toEqual(["b.pdf", "ö.pdf", "a.pdf"]);
    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Storlek" }));
    expect(names()).toEqual(["ö.pdf", "a.pdf", "b.pdf"]);
    fireEvent.click(screen.getByRole("button", { name: "Sortera efter Namn" }));
    expect(names()).toEqual(["a.pdf", "b.pdf", "ö.pdf"]);
    expect(screen.getAllByRole("button", { name: /Fler åtgärder för/ })).toHaveLength(3);
    await expectNoAxeViolations(container);
  });

  it("pages through more than 100 files and filters by name", () => {
    const blobs = Array.from({ length: 105 }, (_, index) =>
      blob(String(index), `fil-${String(index).padStart(3, "0")}.pdf`, index)
    );
    renderInApp(<BlobTable blobs={blobs} canEdit={false} />);

    expect(names()).toHaveLength(100);
    const pages = screen.getByRole("navigation", { name: /Bläddra bland filer/ });
    expect(pages).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Fler åtgärder för/ })).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: "Filtrera filer" }), {
      target: { value: "fil-104" }
    });
    expect(names()).toEqual(["fil-104.pdf"]);
    expect(screen.queryByRole("navigation", { name: /Bläddra bland filer/ })).toBeNull();
  });

  it("explains an empty list", () => {
    renderInApp(<BlobTable blobs={[]} canEdit />);
    expect(screen.getByRole("heading", { name: "Du har inga filer uppladdade ännu" })).toBeTruthy();
  });
});
