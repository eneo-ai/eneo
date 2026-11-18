// @vitest-environment jsdom
import { ChatTokenizedText } from "@astryxdesign/core/Chat";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import type { ComposerInsert } from "@/features/chat/chat-references";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageResponse } from "@/components/ai-elements/message";
import { Composer } from "@/features/chat/composer";
import { useAttachments } from "@/features/chat/use-attachments";
import { ReferenceMenuButton } from "@/features/references/reference-menu";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import {
  SettingReferences,
  insertSettingMessage,
  useSettingReferenceMenu
} from "./setting-reference-pills";
import type { SettingReference } from "./setting-references";

afterEach(cleanup);

/** What the form shows this person: two sections, the second one's settings. */
const LIST: SettingReference[] = [
  {
    key: "section:general",
    section: "general",
    sectionLabel: "Allmänt",
    label: "Allmänt",
    value: "Hela avsnittet"
  },
  {
    key: "name",
    section: "general",
    sectionLabel: "Allmänt",
    label: "Namn",
    value: "Bygglov",
    control: "assistant-name"
  },
  {
    key: "section:ai",
    section: "ai",
    sectionLabel: "AI-inställningar",
    label: "AI-inställningar",
    value: "Hela avsnittet"
  },
  {
    key: "completion_model",
    section: "ai",
    sectionLabel: "AI-inställningar",
    label: "Chattmodell",
    value: "Nordic Large",
    control: "assistant-completion-model"
  },
  {
    key: "completion_model_kwargs",
    section: "ai",
    sectionLabel: "AI-inställningar",
    label: "Modellbeteende",
    value: "Standard",
    control: "assistant-model-behaviour"
  }
];
const MAP = new Map(LIST.map((reference) => [reference.key, reference]));

/** The composer on screen, to type into as a keyboard would. */
let field: ComposerInsert | null = null;

/** A helper chat's composer and its "@" button, with what a send would send. */
function ChatHarness({ onSubmit }: { onSubmit: (value: string) => void }) {
  const { references, composer } = useSettingReferenceMenu(LIST);
  const [value, setValue] = useState("");
  const attachments = useAttachments({ type: "assistant", id: "helper", name: "Hjälpen" });
  return (
    <SettingReferences references={MAP} show={vi.fn()}>
      <Composer
        value={value}
        onChange={setValue}
        onSubmit={() => onSubmit(value)}
        busy={false}
        onStop={vi.fn()}
        label="Fråga hjälpassistenten"
        placeholder="Fråga om assistenten…"
        attachments={attachments}
        onOpenFileDialog={vi.fn()}
        triggers={references.triggers}
        onInput={(input) => {
          field = input;
          references.onComposer?.(input);
        }}
        footerActions={
          composer ? (
            <ReferenceMenuButton label="Referera till en inställning" input={composer} />
          ) : null
        }
      />
      {composer ? (
        <button type="button" onClick={() => insertSettingMessage(composer, ASK_MODEL, MAP)}>
          Fråga om modellen
        </button>
      ) : null}
      <output data-testid="value">{value}</output>
    </SettingReferences>
  );
}

const ASK_MODEL =
  "Hjälp mig välja @[Chattmodell](setting:completion_model) och @[Webbwidget](setting:section:widget).";

function tokenValues() {
  return [...screen.getByRole("combobox").querySelectorAll("[data-astryx-token-value]")].map(
    (token) => token.getAttribute("data-astryx-token-value")
  );
}

describe("The '@' menu of the assistant's settings", () => {
  it("lists the form's settings under their sections, with their values, and filters as typed", async () => {
    renderInApp(<ChatHarness onSubmit={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Referera till en inställning" }));

    const menu = await screen.findByRole("listbox", { name: "Inställningar" });
    const groups = within(menu).getAllByRole("group");
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "Allmänt",
      "AI-inställningar"
    ]);
    expect(
      within(groups[1]!)
        .getAllByRole("option")
        .map((option) => option.textContent)
    ).toEqual([
      "AI-inställningarHela avsnittet",
      "ChattmodellNordic Large",
      "ModellbeteendeStandard"
    ]);
    // The field is the combobox; the highlighted option is what it points at.
    const combobox = screen.getByRole("combobox");
    expect(combobox.getAttribute("aria-expanded")).toBe("true");
    expect(combobox.getAttribute("aria-activedescendant")).toBe(
      within(menu).getAllByRole("option")[0]!.id
    );
    await expectNoAxeViolations(document.body);
  });

  it("filters by what is typed after '@': a name, a value or a section", async () => {
    renderInApp(<ChatHarness onSubmit={vi.fn()} />);
    await screen.findByRole("button", { name: "Referera till en inställning" });
    const options = () =>
      within(screen.getByRole("listbox"))
        .getAllByRole("option")
        .map((o) => o.textContent);

    act(() => field!.insertText("@nordic"));
    await waitFor(() => expect(options()).toEqual(["ChattmodellNordic Large"]));
    act(() => field!.insertText(" @allmä"));
    await waitFor(() => expect(options()).toEqual(["AllmäntHela avsnittet", "NamnBygglov"]));
    act(() => field!.insertText(" @ingetsådant"));
    await waitFor(() =>
      expect(screen.getByRole("listbox").textContent).toBe("Ingen inställning matchar.")
    );
  });

  it("puts the chosen setting in the field as a pill with the keyboard, and sends nothing", async () => {
    const onSubmit = vi.fn();
    renderInApp(<ChatHarness onSubmit={onSubmit} />);
    fireEvent.click(await screen.findByRole("button", { name: "Referera till en inställning" }));
    await screen.findByRole("listbox", { name: "Inställningar" });
    const combobox = screen.getByRole("combobox");

    fireEvent.keyDown(combobox, { key: "ArrowDown" });
    fireEvent.keyDown(combobox, { key: "Enter" });

    await waitFor(() => expect(screen.queryByRole("listbox")).toBeNull());
    expect(tokenValues()).toEqual(["@[Namn](setting:name)"]);
    expect(within(combobox).getByText("Namn")).toBeTruthy();
    expect(screen.getByTestId("value").textContent).toContain("@[Namn](setting:name)");
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("Setting references in a message", () => {
  it("puts a prepared question in the composer, a setting as a pill and the rest as text", async () => {
    const onSubmit = vi.fn();
    renderInApp(<ChatHarness onSubmit={onSubmit} />);
    fireEvent.click(await screen.findByRole("button", { name: "Fråga om modellen" }));

    expect(tokenValues()).toEqual(["@[Chattmodell](setting:completion_model)"]);
    // A section the form does not show this person is its name in words.
    expect(screen.getByTestId("value").textContent?.replace(/\s+/g, " ")).toBe(
      "Hjälp mig välja @[Chattmodell](setting:completion_model) och Webbwidget."
    );
    expect(document.activeElement).toBe(screen.getByRole("combobox"));
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("draws a sent message's references as pills that show the setting", () => {
    const show = vi.fn();
    function Sent({ text }: { text: string }) {
      const { references } = useSettingReferenceMenu(LIST);
      return (
        <SettingReferences references={MAP} show={show}>
          <ChatTokenizedText tokens={references.tokens!(text)}>{text}</ChatTokenizedText>
        </SettingReferences>
      );
    }
    const { container } = renderInApp(
      <Sent text="Vad gör @[Modellbeteende](setting:completion_model_kwargs) och @[Widget](setting:section:widget)?" />
    );

    fireEvent.click(screen.getByRole("button", { name: "Modellbeteende" }));
    expect(show).toHaveBeenCalledWith("completion_model_kwargs");
    // What the form does not show is plain text, by the name it was written with.
    expect(screen.queryByRole("button", { name: "Widget" })).toBeNull();
    expect(container.textContent).toBe("Vad gör Modellbeteende och Widget?");
  });

  it("draws an answer's references as pills, and the rest as the chat draws it", async () => {
    const show = vi.fn();
    function Answer({ text }: { text: string }) {
      const { references } = useSettingReferenceMenu(LIST);
      return (
        <SettingReferences references={MAP} show={show}>
          <MessageResponse
            remarkPlugins={references.remarkPlugins}
            components={references.components}
          >
            {text}
          </MessageResponse>
        </SettingReferences>
      );
    }
    const { container } = renderInApp(
      <Answer text="Byt @[Chattmodell](setting:completion_model) under @[AI-inställningar](setting:section:ai); `@[Namn](setting:name)` och @[Bortom](setting:section:widget) också." />
    );

    fireEvent.click(screen.getByRole("button", { name: "Chattmodell" }));
    expect(show).toHaveBeenCalledWith("completion_model");
    fireEvent.click(screen.getByRole("button", { name: "AI-inställningar" }));
    expect(show).toHaveBeenCalledWith("section:ai");
    // In backticks it is still the reference.
    expect(screen.getByRole("button", { name: "Namn" })).toBeTruthy();
    // Drawn with the editor's name now, not the name it was written with; the
    // markup never shows.
    expect(screen.queryByRole("button", { name: "Bortom" })).toBeNull();
    expect(container.textContent).toContain("Bortom också");
    expect(container.textContent).not.toContain("setting:");
    await expectNoAxeViolations(container);
  });
});
