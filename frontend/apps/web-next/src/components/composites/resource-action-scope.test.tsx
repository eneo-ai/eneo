// @vitest-environment jsdom
import { DropdownMenu, DropdownMenuItem } from "@astryxdesign/core/DropdownMenu";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useEffect, useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
import { ConfirmDialogControlled } from "./confirm-dialog";
import { createResourceActions } from "./resource-action-scope";
import { ResourceCard, ResourceCollection } from "./resource-tile";

afterEach(cleanup);

type Item = { id: string; name: string };
const { ResourceActionScope, useOpenResourceAction } = createResourceActions<Item, "rename">();

function Menu({ item }: { item: Item }) {
  const open = useOpenResourceAction();
  return (
    <button type="button" onClick={() => open("rename", item)}>
      Fler åtgärder för {item.name}
    </button>
  );
}

/** What each dialog was given to close itself with, for a request that finishes late. */
const closers: Record<string, () => void> = {};

function RenameDialog({ resource, onClose }: { resource: Item; onClose: () => void }) {
  const [text, setText] = useState("");
  useEffect(() => {
    closers[resource.id] = onClose;
  });
  return (
    <div role="dialog" aria-label={`Byt namn på ${resource.name}`}>
      <input
        aria-label="Nytt namn"
        value={text}
        onChange={(event) => setText(event.target.value)}
      />
      <button type="button" onClick={onClose}>
        Stäng
      </button>
    </div>
  );
}

const items: Item[] = [
  { id: "a1", name: "Protokoll" },
  { id: "a2", name: "Avtal" }
];

const controls = { removeFirst: () => {} };

function Page() {
  const heading = useRef<HTMLHeadingElement>(null);
  const [shown, setShown] = useState(items);
  useEffect(() => {
    controls.removeFirst = () => setShown((current) => current.slice(1));
  });
  return (
    <ResourceActionScope Dialog={RenameDialog} focusTarget={heading}>
      <h1 ref={heading} tabIndex={-1}>
        Appar
      </h1>
      <ResourceCollection>
        {shown.map((item) => (
          <ResourceCard
            key={item.id}
            href={`/spaces/s1/apps/${item.id}`}
            name={item.name}
            tile={<span aria-hidden="true">{item.name[0]}</span>}
            actions={<Menu item={item} />}
          />
        ))}
      </ResourceCollection>
    </ResourceActionScope>
  );
}

describe("a resource's dialog across 768 px (a phone turned)", () => {
  it("stays open, with what was typed in it, when rows turn into cards and back", () => {
    setViewport("phone");
    renderInApp(<Page />);
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Avtal" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nytt namn" }), {
      target: { value: "Avtalsanalys" }
    });

    act(() => setViewport("tablet-portrait"));
    expect(screen.getByRole("dialog", { name: "Byt namn på Avtal" })).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Nytt namn" }) as HTMLInputElement).value).toBe(
      "Avtalsanalys"
    );

    act(() => setViewport("phone"));
    expect((screen.getByRole("textbox", { name: "Nytt namn" }) as HTMLInputElement).value).toBe(
      "Avtalsanalys"
    );
  });

  it("closes once, with focus on the resource's link where the turn put it", async () => {
    setViewport("phone");
    renderInApp(<Page />);
    const menu = screen.getByRole("button", { name: "Fler åtgärder för Protokoll" });
    act(() => menu.focus());
    fireEvent.click(menu);

    act(() => setViewport("tablet-portrait"));
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("link", { name: "Protokoll" }))
    );
  });

  it("gives focus to the page's heading when the control that opened it is gone", async () => {
    setViewport("phone");
    renderInApp(<Page />);
    // Not focused (Safari never focuses a tapped button): the turn has nothing to carry over.
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Avtal" }));
    act(() => setViewport("tablet-portrait"));
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));

    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Appar" }))
    );
  });

  it("lets a request that finishes late close its own dialog, not the one opened since", async () => {
    setViewport("phone");
    renderInApp(<Page />);
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Protokoll" }));
    const first = closers["a1"]!;
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder för Avtal" }));
    expect(screen.getByRole("dialog", { name: "Byt namn på Avtal" })).toBeTruthy();
    // The first dialog's move, cancelled while it ran, is done now.
    act(() => first());
    expect(screen.getByRole("dialog", { name: "Byt namn på Avtal" })).toBeTruthy();
  });

  it("finds the heading when the control that opened a dialog leaves after the dialog closed", async () => {
    setViewport("phone");
    renderInApp(<Page />);
    const menu = screen.getByRole("button", { name: "Fler åtgärder för Protokoll" });
    act(() => menu.focus());
    fireEvent.click(menu);
    fireEvent.click(screen.getByRole("button", { name: "Stäng" }));
    // Publishing moves the item to another list: its menu is gone once the lists refetch.
    act(() => controls.removeFirst());

    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Appar" }))
    );
  });

  it("asks for its scope instead of opening nothing", () => {
    expect(() => renderInApp(<Menu item={items[0]!} />)).toThrow(/ResourceActionScope/);
  });
});

const deletes = createResourceActions<Item, "delete">();

/** An Astryx menu, as a row has: the dialog opens from its item, gone once the dialog is up. */
function DeleteMenu({ item }: { item: Item }) {
  const open = deletes.useOpenResourceAction();
  return (
    <DropdownMenu button={{ label: `Fler åtgärder för ${item.name}`, isIconOnly: true }}>
      <DropdownMenuItem label="Ta bort" onClick={() => open("delete", item)} />
    </DropdownMenu>
  );
}

/** What a confirmed delete does to the list: nothing, or the item goes once the list is read again. */
const deleted: { removes: boolean; remove: (item: Item) => void } = {
  removes: false,
  remove: () => {}
};

function DeleteDialog({ resource, onClose }: { resource: Item; onClose: () => void }) {
  return (
    <ConfirmDialogControlled
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Ta bort ${resource.name}`}
      description="Det går inte att ångra."
      confirmLabel="Ta bort"
      onConfirm={async () => {
        // The request answers, and the dialog closes, outside the click.
        await Promise.resolve();
        onClose();
        // The refetch answers after the dialog has gone.
        if (deleted.removes) setTimeout(() => deleted.remove(resource), 0);
      }}
    />
  );
}

function DeletePage() {
  const heading = useRef<HTMLHeadingElement>(null);
  const [shown, setShown] = useState(items);
  useEffect(() => {
    deleted.remove = (item) => setShown((current) => current.filter(({ id }) => id !== item.id));
  });
  return (
    <deletes.ResourceActionScope Dialog={DeleteDialog} focusTarget={heading}>
      <h1 ref={heading} tabIndex={-1}>
        Appar
      </h1>
      <ul>
        {shown.map((item) => (
          <li key={item.id}>
            <DeleteMenu item={item} />
          </li>
        ))}
      </ul>
    </deletes.ResourceActionScope>
  );
}

describe("a confirmation the scope drops once it is done", () => {
  async function confirmDelete(name: string) {
    renderInApp(<DeletePage />);
    const menu = screen.getByRole("button", { name: `Fler åtgärder för ${name}` });
    act(() => menu.focus());
    // jsdom does not turn Enter into a click; Astryx opens menus on the key.
    fireEvent.keyDown(menu, { key: "Enter" });
    const items = document.getElementById(menu.getAttribute("aria-controls")!)!;
    fireEvent.click(within(items).getByRole("menuitem", { name: "Ta bort" }));
    const dialog = await screen.findByRole("alertdialog", { name: `Ta bort ${name}` });
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    return menu;
  }

  it("gives focus back to the menu that opened it when the item stays", async () => {
    deleted.removes = false;
    const menu = await confirmDelete("Avtal");
    await waitFor(() => expect(document.activeElement).toBe(menu));
  });

  it("gives focus to the page's heading when the item leaves after the dialog has gone", async () => {
    deleted.removes = true;
    await confirmDelete("Avtal");
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Fler åtgärder för Avtal" })).toBeNull()
    );
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { name: "Appar" }))
    );
  });
});
