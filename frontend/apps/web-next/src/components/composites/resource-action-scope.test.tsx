// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { setViewport } from "@/test/setup-dom";
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

function RenameDialog({ resource, onClose }: { resource: Item; onClose: () => void }) {
  const [text, setText] = useState("");
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

function Page() {
  const heading = useRef<HTMLHeadingElement>(null);
  return (
    <ResourceActionScope Dialog={RenameDialog} focusTarget={heading}>
      <h1 ref={heading} tabIndex={-1}>
        Appar
      </h1>
      <ResourceCollection>
        {items.map((item) => (
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

  it("asks for its scope instead of opening nothing", () => {
    expect(() => renderInApp(<Menu item={items[0]!} />)).toThrow(/ResourceActionScope/);
  });
});
