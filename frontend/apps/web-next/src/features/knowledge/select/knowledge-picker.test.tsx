// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";
import {
  makeCollection,
  makeIntegration,
  makeSpace,
  makeWebsite
} from "@/features/spaces/testing/space-fixture";
import type { Collection, IntegrationKnowledge, Website } from "../knowledge";

const state = vi.hoisted(() => ({ space: null as unknown }));

vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") })
  }
}));

import { KnowledgePicker } from "./knowledge-picker";

afterEach(cleanup);

describe("KnowledgePicker", () => {
  it.each([
    {
      kind: "shared",
      personal: false,
      addLabel: "Lägg till kunskap (den här ytan)",
      emptyLabel: "Det finns inga tillgängliga källor i den här ytan."
    },
    {
      kind: "personal",
      personal: true,
      addLabel: "Lägg till kunskap (Personlig)",
      emptyLabel: "Inga personliga källor tillgängliga."
    }
  ])("names current-space knowledge in a $kind space", ({ personal, addLabel, emptyLabel }) => {
    state.space = makeSpace({ overrides: { personal } });

    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{ collections: [], websites: [], integrationKnowledge: [] }}
        onChange={() => {}}
      />
    );

    fireEvent.click(screen.getByRole("button", { name: addLabel }));
    expect(screen.getByText(emptyLabel)).toBeTruthy();
  });

  it("counts the selected knowledge with plural forms", () => {
    const collection = makeCollection({ metadata: { num_info_blobs: 1, size: 10 } });
    const website = makeWebsite({
      latest_crawl: {
        ...(makeWebsite().latest_crawl as Record<string, unknown>),
        pages_crawled: 1,
        pages_failed: 1
      }
    });
    state.space = makeSpace({ collections: [collection], websites: [website] });

    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{
          collections: [collection as unknown as Collection],
          websites: [website as unknown as Website],
          integrationKnowledge: []
        }}
        onChange={() => {}}
      />
    );

    expect(screen.getByText("1 fil")).toBeTruthy();
    expect(screen.getByText("1 sida")).toBeTruthy();
    expect(screen.getByText("1 sida misslyckades")).toBeTruthy();
  });
  it("adds a source picked from the searchable, axe-clean list with the keyboard", async () => {
    const collection = makeCollection();
    const other = makeCollection({ id: "collection-2", name: "Avtalsregister" });
    state.space = makeSpace({ collections: [collection, other] });
    const onChange = vi.fn();
    renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{ collections: [], websites: [], integrationKnowledge: [] }}
        onChange={onChange}
      />
    );

    const add = screen.getByRole("button", { name: "Lägg till kunskap (den här ytan)" });
    add.focus();
    fireEvent.keyDown(add, { key: "Enter" });
    // Focus moves to the list's search field (its name is Astryx's own) once it is open.
    const search = await screen.findByRole("combobox", { name: "Sökalternativ" });
    await waitFor(() => expect(document.activeElement).toBe(search));
    await expectNoAxeViolations(document.body);
    fireEvent.change(search, { target: { value: "avtal" } });
    expect(screen.queryByRole("option", { name: /Upphandlingspolicy/ })).toBeNull();
    fireEvent.keyDown(search, { key: "ArrowDown" });
    fireEvent.keyDown(search, { key: "Enter" });

    expect(onChange).toHaveBeenCalledWith({
      collections: [other],
      websites: [],
      integrationKnowledge: []
    });
  });

  it("shows a selected collection's files behind its disclosure button and is axe-clean", async () => {
    const collection = makeCollection();
    const website = makeWebsite({
      latest_crawl: {
        ...(makeWebsite().latest_crawl as Record<string, unknown>),
        pages_failed: 2
      }
    });
    const integration = makeIntegration();
    state.space = makeSpace({
      collections: [collection],
      websites: [website],
      integrations: [integration]
    });
    const onChange = vi.fn();
    const { container } = renderInApp(
      <KnowledgePicker
        origin="personal"
        selections={{
          collections: [collection as unknown as Collection],
          websites: [website as unknown as Website],
          integrationKnowledge: [integration as unknown as IntegrationKnowledge]
        }}
        onChange={onChange}
      />
    );

    const disclosure = screen.getByRole("button", { name: /Upphandlingspolicy/ });
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(disclosure);
    expect(disclosure.getAttribute("aria-expanded")).toBe("true");
    expect(await screen.findByText("Inga filer hittades")).toBeTruthy();
    await expectNoAxeViolations(container);

    const removes = screen.getAllByRole("button", { name: "Ta bort" });
    expect(removes).toHaveLength(3);
    fireEvent.click(removes[0]!);
    expect(onChange).toHaveBeenCalledWith({
      collections: [],
      websites: [website],
      integrationKnowledge: [integration]
    });
  });
});
