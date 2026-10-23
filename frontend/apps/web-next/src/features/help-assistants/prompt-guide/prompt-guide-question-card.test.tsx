// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { PromptGuideQuestionCard } from "./prompt-guide-dialog";

afterEach(cleanup);

const describedText = (element: HTMLElement) =>
  document.getElementById(element.getAttribute("aria-describedby") ?? "")?.textContent;

it("shows a missing choice at the question on send, and moves focus to its first option", () => {
  const onAnswer = vi.fn();
  renderInApp(
    <PromptGuideQuestionCard
      question={{
        header: "Målgrupp",
        question: "Vem ska använda assistenten?",
        multiSelect: false,
        options: [{ label: "Medarbetare" }, { label: "Invånare" }]
      }}
      disabled={false}
      onAnswer={onAnswer}
    />
  );
  const send = screen.getByRole("button", { name: "Skicka" });
  expect(send.hasAttribute("disabled")).toBe(false);
  send.focus();

  fireEvent.click(send);

  const options = screen.getByRole("radiogroup", { name: "Vem ska använda assistenten?" });
  expect(document.activeElement).toBe(screen.getByRole("radio", { name: "Medarbetare" }));
  expect(options.getAttribute("aria-invalid")).toBe("true");
  expect(describedText(options)).toBe("Välj ett alternativ eller skriv ett eget svar.");
  expect(onAnswer).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("radio", { name: "Invånare" }));
  expect(options.getAttribute("aria-invalid")).toBeNull();
  fireEvent.click(send);
  expect(onAnswer).toHaveBeenCalledWith("Invånare");
});

it("asks for a free answer at its field when the question has no options", () => {
  const onAnswer = vi.fn();
  renderInApp(
    <PromptGuideQuestionCard
      question={{
        header: "Syfte",
        question: "Vad ska assistenten hjälpa till med?",
        multiSelect: false,
        options: []
      }}
      disabled={false}
      onAnswer={onAnswer}
    />
  );
  const answer = screen.getByRole("textbox", { name: "Ditt svar" });

  fireEvent.keyDown(answer, { key: "Enter" });

  expect(document.activeElement).toBe(answer);
  expect(answer.getAttribute("aria-invalid")).toBe("true");
  expect(describedText(answer)).toBe("Skriv ett svar.");
  expect(onAnswer).not.toHaveBeenCalled();

  fireEvent.change(answer, { target: { value: "Svara på frågor om bygglov" } });
  fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
  expect(onAnswer).toHaveBeenCalledWith("Svara på frågor om bygglov");
});
