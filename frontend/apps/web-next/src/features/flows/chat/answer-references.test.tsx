// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { createRef, useState, type Ref } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageResponse } from "@/components/ai-elements/message";
import { Composer, type ComposerHandle } from "@/features/chat/composer";
import { useAttachments } from "@/features/chat/use-attachments";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeFlow, makeStep } from "../flow-fixtures";
import { referenceComponents, referenceRemarkPlugins } from "./answer-references";
import { FlowReferences, insertMessage } from "./reference-pill";

afterEach(cleanup);

const flow = makeFlow({
  steps: [
    makeStep(1, {
      user_description: "Extrahera",
      output_type: "json",
      output_contract: { type: "object", properties: { atgard: { type: "string" } } }
    }),
    makeStep(2, { user_description: "Hämta register" }),
    makeStep(3, { user_description: "Bedömning" })
  ]
});

function renderAnswer(text: string, onShowStep = vi.fn(() => true)) {
  const composer = { insertText: vi.fn(), insertToken: vi.fn() };
  const view = renderInApp(
    <FlowReferences flow={flow} onShowStep={onShowStep} composer={composer}>
      <MessageResponse remarkPlugins={referenceRemarkPlugins} components={referenceComponents}>
        {text}
      </MessageResponse>
    </FlowReferences>
  );
  return { ...view, onShowStep, composer };
}

describe("references in an answer", () => {
  it("draws a step mention and a value reference as pills that open a card", async () => {
    const { onShowStep, container } = renderAnswer(
      "Steget @[Bedömning](step:step-3) läser nu {{step_1.output.structured.atgard}} i stället för {{step_2.output.text}}."
    );
    const step = screen.getByRole("button", { name: "Steg 3: Bedömning" });
    expect(screen.getByRole("button", { name: "Steg 1: Extrahera › atgard" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Steg 2: Hämta register › text" })).toBeTruthy();
    // The references are not left in the text as written.
    expect(container.textContent).not.toContain("{{");
    expect(container.textContent).not.toContain("@[");

    fireEvent.click(step);
    const card = await screen.findByRole("dialog", { name: "Referens" });
    expect(within(card).getByText("@[Bedömning](step:step-3)")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Visa steget" }));
    expect(onShowStep).toHaveBeenCalledWith("step-3");
  });

  it("puts the reference into the composer as a pill from its card", async () => {
    const { composer } = renderAnswer("Se {{step_2.output.text}}.");
    fireEvent.click(screen.getByRole("button", { name: "Steg 2: Hämta register › text" }));
    const card = await screen.findByRole("dialog", { name: "Referens" });
    fireEvent.click(within(card).getByRole("button", { name: "Infoga i meddelandet" }));
    expect(composer.insertToken).toHaveBeenCalledWith(
      expect.objectContaining({ value: "{{step_2.output.text}}" })
    );
    expect(screen.queryByRole("dialog", { name: "Referens" })).toBeNull();
  });

  it("explains a reference the flow cannot read and offers what the step provides", async () => {
    const { composer } = renderAnswer("Utan {{step_1...}} går det inte.");
    fireEvent.click(screen.getByRole("button", { name: "step_1..." }));
    const card = await screen.findByRole("dialog", { name: "Referens" });
    expect(within(card).getByText("Flödet kan inte läsa step_1....")).toBeTruthy();
    expect(within(card).getByText("Steg 1: Extrahera ger i stället:")).toBeTruthy();
    fireEvent.click(within(card).getByRole("button", { name: "Steg 1: Extrahera › atgard" }));
    expect(composer.insertToken).toHaveBeenCalledWith(
      expect.objectContaining({ value: "{{step_1.output.structured.atgard}}" })
    );
  });

  it("says when a step is gone and when a field is read from a step that answers in text", async () => {
    renderAnswer("Se @[Borta](step:step-9) och {{step_2.output.structured.x}}.");
    fireEvent.click(screen.getByRole("button", { name: "Borta" }));
    const card = await screen.findByRole("dialog", { name: "Referens" });
    expect(within(card).getByText("Steget finns inte längre i flödet.")).toBeTruthy();
    expect(within(card).queryByRole("button", { name: "Visa steget" })).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Steg 2: Hämta register › fält, men steget svarar inte i fast format"
      })
    ).toBeTruthy();
  });

  it("draws a reference the answer put in backticks, spaces and all", () => {
    renderAnswer("Läser `{{ step_1.output.structured.atgard }}` och `step_1`.");
    expect(screen.getByRole("button", { name: "Steg 1: Extrahera › atgard" })).toBeTruthy();
    expect(screen.getByText("step_1").tagName).toBe("CODE");
  });

  it("keeps the text of a code block as it is", () => {
    const { container } = renderAnswer("```\n{{step_1.output.text}}\n```");
    expect(container.querySelector("code")?.textContent).toContain("{{step_1.output.text}}");
    // The code block's own buttons (copy, download) are there; no pill is.
    expect(screen.queryByRole("button", { name: /Extrahera/ })).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderAnswer(
      "Läser @[Extrahera](step:step-1) och {{step_1.output.text}}."
    );
    await expectNoAxeViolations(container);
  });
});

/** The flow chat's composer as the person sees it, reporting its value. */
function ComposerHarness({
  inputRef,
  onChange,
  onSubmit
}: {
  inputRef: Ref<ComposerHandle>;
  onChange: (value: string) => void;
  onSubmit: () => void;
}) {
  const [value, setValue] = useState("");
  const attachments = useAttachments({ type: "assistant", id: "assistant-chat", name: "Flöde" });
  return (
    <FlowReferences flow={flow} onShowStep={() => true}>
      <Composer
        value={value}
        onChange={(next) => {
          setValue(next);
          onChange(next);
        }}
        onSubmit={onSubmit}
        canSubmit={value.trim().length > 0}
        busy={false}
        onStop={vi.fn()}
        label="Meddelande till flödeschatten"
        placeholder="Fråga om flödet"
        attachments={attachments}
        onOpenFileDialog={vi.fn()}
        inputRef={inputRef}
      />
    </FlowReferences>
  );
}

describe("insertMessage", () => {
  it("puts a prepared message in the composer, steps as pills, and sends nothing", async () => {
    const ref = createRef<ComposerHandle>();
    const onChange = vi.fn();
    const onSubmit = vi.fn();
    const { container } = renderInApp(
      <ComposerHarness inputRef={ref} onChange={onChange} onSubmit={onSubmit} />
    );
    const text =
      "Förklara förslaget och föreslå en ändring. Steg: @[Bedömning](step:step-3) @[Extrahera](step:step-1)";

    act(() => insertMessage(ref.current!, text, flow));

    const textbox = screen.getByRole("textbox");
    expect(
      [...textbox.querySelectorAll("[data-astryx-token-value]")].map((token) =>
        token.getAttribute("data-astryx-token-value")
      )
    ).toEqual(["@[Bedömning](step:step-3)", "@[Extrahera](step:step-1)"]);
    // The message travels as written (each pill brings its own space, which
    // Astryx writes as a no-break space); the person sends it when they choose.
    const value = onChange.mock.lastCall?.[0] as string;
    expect(value.replace(/\s+/g, " ").trim()).toBe(text);
    expect(document.activeElement).toBe(textbox);
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Skicka meddelande" }).hasAttribute("disabled")).toBe(
      false
    );
    await expectNoAxeViolations(container);
  });
});
