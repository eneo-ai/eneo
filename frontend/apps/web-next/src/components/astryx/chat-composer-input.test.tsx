// @vitest-environment jsdom
import {
  ChatComposer,
  ChatComposerInput as AstryxChatComposerInput
} from "@astryxdesign/core/Chat";
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { ChatComposerInput } from "./chat-composer-input";

afterEach(cleanup);

// Guards the wrapper's reason: Astryx 0.7.12 puts a caller's aria-invalid on
// the input's wrapper only. When the editable element gets it itself, this
// wrapper and this test can go.
it("marks the element you type in as invalid, where Astryx marks its wrapper", () => {
  renderInApp(
    <>
      <span id="hint-a">Enter skickar.</span>
      <ChatComposer
        onSubmit={() => {}}
        input={<AstryxChatComposerInput label="Astryx" aria-describedby="hint-a" aria-invalid />}
      />
      <span id="hint-b">Skift+Enter ger en ny rad.</span>
      <ChatComposer
        onSubmit={() => {}}
        input={<ChatComposerInput label="Eneo" aria-describedby="hint-b" aria-invalid />}
      />
    </>
  );

  const astryx = screen.getByRole("textbox", { name: "Astryx" });
  expect(astryx.getAttribute("aria-invalid")).toBeNull();
  expect(astryx.parentElement?.getAttribute("aria-invalid")).toBe("true");

  const eneo = screen.getByRole("textbox", { name: "Eneo" });
  expect(eneo.getAttribute("aria-describedby")).toBe("hint-b");
  expect(eneo.getAttribute("aria-invalid")).toBe("true");
  expect(eneo.getAttribute("aria-multiline")).toBe("true");
});
