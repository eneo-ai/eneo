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

// Guards the wrapper's reason: Astryx 0.7.3 puts a caller's aria-describedby
// on the input's wrapper. When the editable element gets it itself, this
// wrapper and this test can go.
it("describes the element you type in, where Astryx describes its wrapper", () => {
  renderInApp(
    <>
      <span id="hint-a">Enter skickar.</span>
      <ChatComposer
        onSubmit={() => {}}
        input={<AstryxChatComposerInput label="Astryx" aria-describedby="hint-a" />}
      />
      <span id="hint-b">Skift+Enter ger en ny rad.</span>
      <ChatComposer
        onSubmit={() => {}}
        input={<ChatComposerInput label="Eneo" aria-describedby="hint-b" />}
      />
    </>
  );

  const astryx = screen.getByRole("textbox", { name: "Astryx" });
  expect(astryx.getAttribute("aria-describedby")).toBeNull();
  expect(astryx.parentElement?.getAttribute("aria-describedby")).toBe("hint-a");

  const eneo = screen.getByRole("textbox", { name: "Eneo" });
  expect(eneo.getAttribute("aria-describedby")).toBe("hint-b");
  expect(eneo.getAttribute("aria-multiline")).toBe("true");
});
