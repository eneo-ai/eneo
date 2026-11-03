// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import { makeCollection } from "@/features/spaces/testing/space-fixture";

const state = vi.hoisted(() => ({ modelEnabled: true }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeSpace } = await import("@/features/spaces/testing/space-fixture");
  return {
    useSpace: () =>
      useSpaceFromQuery(
        () => makeSpace(state.modelEnabled ? {} : { overrides: { embedding_models: [] } }) as Space
      )
  };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (path: string) => {
      const data =
        path === "/api/v1/groups/{id}/"
          ? makeCollection()
          : path === "/api/v1/groups/{id}/info-blobs/"
            ? { items: [{ id: "blob-1", metadata: { title: "lou.pdf", size: 2048 } }] }
            : { items: [] };
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { CollectionDetail } from "@/features/knowledge/detail/collection-detail.client";

afterEach(() => {
  cleanup();
  state.modelEnabled = true;
});

describe("CollectionDetail", () => {
  it("names the file table after the collection", async () => {
    const { container } = renderInApp(<CollectionDetail collectionId="collection-1" />);

    const heading = await screen.findByRole("heading", { level: 1, name: "Upphandlingspolicy" });
    const table = screen.getByRole("table", { name: "Upphandlingspolicy" });
    expect(table.getAttribute("aria-labelledby")).toBe(heading.id);
    await expectNoAxeViolations(container);
  });
});

it("explains how to enable add-text and upload when the collection's model is disabled", async () => {
  state.modelEnabled = false;
  renderInApp(<CollectionDetail collectionId="collection-1" />);
  const add = await screen.findByRole("button", { name: "Lägg till text" });
  const upload = screen.getByRole("button", { name: "Ladda upp filer" });
  for (const button of [add, upload]) {
    expect(button.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(button);
  }
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(
    screen
      .getAllByRole("tooltip")
      .map((tooltip) => tooltip.textContent)
      .filter((text) => text?.startsWith("Aktivera modellen"))
  ).toEqual(Array(2).fill("Aktivera modellen i inställningarna för att lägga till text"));
});
