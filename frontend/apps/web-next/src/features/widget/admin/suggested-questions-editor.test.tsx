// @vitest-environment jsdom
import { fireEvent, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { SuggestedQuestionsEditor } from "./suggested-questions-editor";

it("correcting a long saved question keeps the rest of it", () => {
  // Saved through the API at its 160-character limit, above the old field cap.
  const saved =
    "Vilka handlingar beh\u00f6ver jag f\u00f6r att s\u00f6ka bygglov f\u00f6r ett attefallshus p\u00e5 en fastighet utanf\u00f6r detaljplanerat omr\u00e5de i kommunen i \u00e5r?";
  expect(saved.length).toBeGreaterThan(120);
  const onChange = vi.fn<(questions: string[]) => void>();
  renderInApp(<SuggestedQuestionsEditor questions={[saved]} onChange={onChange} />);
  const [field] = screen.getAllByRole("textbox");
  fireEvent.change(field!, { target: { value: `Hej! ${saved}` } });
  fireEvent.blur(field!);
  expect(onChange).toHaveBeenLastCalledWith([`Hej! ${saved}`]);
});
