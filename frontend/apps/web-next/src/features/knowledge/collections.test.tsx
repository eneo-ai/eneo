// @vitest-environment jsdom
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const api = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn() }));
const space = vi.hoisted(() => ({ current: null as unknown }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => space.current as Space) };
});

import { makeCollection, makeSpace } from "@/features/spaces/testing/space-fixture";
import { CollectionActions, CreateCollectionButton } from "./collections";
import { KnowledgeActionScope } from "./knowledge-action-scope";
import type { Collection } from "./knowledge";

// Radix Select scrolls its selected option into view; jsdom has no layout.
beforeAll(() => {
  Element.prototype.scrollIntoView = () => {};
});
afterEach(() => vi.clearAllMocks());

async function openDialog() {
  renderInApp(<CreateCollectionButton />);
  fireEvent.click(screen.getByRole("button", { name: "Skapa samling" }));
  const dialog = await screen.findByRole("dialog", { name: "Skapa en ny samling" });
  return { dialog, create: within(dialog).getByRole("button", { name: "Skapa samling" }) };
}

it("shows a missing name at the field on create, which takes focus", async () => {
  space.current = makeSpace();
  api.POST.mockReturnValue(new Promise(() => {}));
  const { dialog, create } = await openDialog();
  // Never disabled: a disabled button says nothing about what is missing.
  expect((create as HTMLButtonElement).disabled).toBe(false);

  fireEvent.click(create);
  const name = within(dialog).getByLabelText("Namn");
  expect(name.getAttribute("aria-invalid")).toBe("true");
  expect(document.activeElement).toBe(name);
  expect(api.POST).not.toHaveBeenCalled();
  await expectNoAxeViolations(dialog);

  fireEvent.change(name, { target: { value: "Upphandlingspolicyer" } });
  fireEvent.click(create);
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
});

it("moves focus to the warning when the space has no embedding model", async () => {
  space.current = makeSpace({ overrides: { embedding_models: [] } });
  const { dialog, create } = await openDialog();

  fireEvent.click(create);

  expect(document.activeElement?.textContent).toContain(
    "Denna yta har för närvarande inga inbäddningsmodeller aktiverade"
  );
  expect(dialog.contains(document.activeElement)).toBe(true);
  expect(api.POST).not.toHaveBeenCalled();
});

it("keeps a newer draft open when a previous save finishes after its dialog closed", async () => {
  space.current = makeSpace();
  let finish!: () => void;
  api.POST.mockReturnValue(
    new Promise((resolve) => {
      finish = () => resolve({ data: { id: "collection-1" }, response: new Response("{}") });
    })
  );
  renderInApp(
    <KnowledgeActionScope focusTarget={{ current: null }}>
      <CollectionActions collection={makeCollection() as Collection} />
      <CollectionActions
        collection={makeCollection({ id: "collection-2", name: "Avtal" }) as Collection}
      />
    </KnowledgeActionScope>
  );
  function edit(name: string) {
    const trigger = screen.getByRole("button", { name: `Fler åtgärder för ${name}` });
    fireEvent.click(trigger);
    const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Redigera" }));
  }
  edit("Upphandlingspolicy");
  let dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByRole("button", { name: "Spara ändringar" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
  edit("Avtal");
  dialog = await screen.findByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Namn"), { target: { value: "Nytt utkast" } });

  await act(async () => finish());

  expect(screen.getByRole("dialog")).toBe(dialog);
  expect((within(dialog).getByLabelText("Namn") as HTMLInputElement).value).toBe("Nytt utkast");
});

it("keeps a standalone pending deletion open when an earlier rename finishes", async () => {
  space.current = makeSpace();
  let finishRename!: () => void;
  api.POST.mockReturnValue(
    new Promise((resolve) => {
      finishRename = () => resolve({ data: { id: "collection-1" }, response: new Response("{}") });
    })
  );
  api.DELETE.mockReturnValue(new Promise(() => {}));
  renderInApp(<CollectionActions collection={makeCollection() as Collection} />);
  const trigger = screen.getByRole("button", { name: "Fler åtgärder för Upphandlingspolicy" });
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("menuitem", { name: "Redigera" }));
  const edit = await screen.findByRole("dialog");
  fireEvent.click(within(edit).getByRole("button", { name: "Spara ändringar" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  fireEvent.click(within(edit).getByRole("button", { name: "Avbryt" }));

  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("menuitem", { name: "Ta bort" }));
  const confirmation = await screen.findByRole("alertdialog", { name: "Radera samling" });
  fireEvent.click(within(confirmation).getByRole("button", { name: "Ta bort" }));
  await waitFor(() => expect(api.DELETE).toHaveBeenCalledTimes(1));
  await act(async () => finishRename());

  expect(screen.getByRole("alertdialog", { name: "Radera samling" })).toBe(confirmation);
  expect(confirmation.querySelector('[aria-busy="true"]')).not.toBeNull();
});
