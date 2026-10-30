// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { QuestionPrompt } from "./question-prompt";
import type { OpenQuestion } from "./questions";

afterEach(cleanup);

const single: OpenQuestion = {
  messageId: "a1",
  toolCallId: "ask-1",
  question: "Vem ska läsa PM:et?",
  header: "Mottagare",
  options: [
    { label: "Nämnden", description: "Beslutsunderlag." },
    { label: "Ledningen", description: "Läget i korthet." }
  ],
  multiSelect: false
};
const several: OpenQuestion = {
  ...single,
  toolCallId: "ask-2",
  question: "Vilka delar?",
  header: null,
  options: [
    { label: "Riktlinjer", description: null },
    { label: "Mallar", description: null }
  ],
  multiSelect: true
};

function render(question: OpenQuestion) {
  const onAnswer = vi.fn();
  const onDismiss = vi.fn();
  renderInApp(<QuestionPrompt question={question} onAnswer={onAnswer} onDismiss={onDismiss} />);
  return { onAnswer, onDismiss };
}

describe("QuestionPrompt", () => {
  it("sends a single choice as soon as it is made, with no Svara button", () => {
    const { onAnswer } = render(single);
    expect(screen.queryByRole("button", { name: "Svara" })).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: /Ledningen/ }));
    expect(onAnswer).toHaveBeenCalledTimes(1);
    expect(onAnswer).toHaveBeenCalledWith("Ledningen");
  });

  it("sends a single choice from its number key", () => {
    const { onAnswer } = render(single);
    fireEvent.keyDown(window, { key: "2" });
    expect(onAnswer).toHaveBeenCalledWith("Ledningen");
  });

  it("sends the person's own words from the field on Enter", () => {
    const { onAnswer } = render(single);
    const other = screen.getByRole("textbox", { name: "Annat svar" });
    fireEvent.change(other, { target: { value: "Revisorerna" } });
    fireEvent.keyDown(other, { key: "Enter" });
    expect(onAnswer).toHaveBeenCalledWith("Revisorerna");
  });

  it("joins several picks in the question's order and waits for Svara", () => {
    const { onAnswer } = render(several);
    fireEvent.click(screen.getByRole("checkbox", { name: /Mallar/ }));
    expect(onAnswer).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: /Riktlinjer/ }));
    fireEvent.click(screen.getByRole("button", { name: "Svara" }));
    expect(onAnswer).toHaveBeenCalledWith("Riktlinjer, Mallar");
  });

  it("hands over to the composer on Esc in the field or the free-answer action", () => {
    const { onDismiss, onAnswer } = render(single);
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Annat svar" }), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Svara fritt i stället" }));
    expect(onDismiss).toHaveBeenCalledTimes(2);
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("names the question's subject and has no axe violations", async () => {
    render(single);
    expect(screen.getByText("Mottagare")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Vem ska läsa PM:et?" })).toBeTruthy();
    await expectNoAxeViolations(document.body);
  });
});
