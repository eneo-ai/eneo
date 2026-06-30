// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createRef } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  PromptInput,
  PromptInputBody,
  PromptInputTextarea,
  type AttachmentsContext,
  type PromptInputMessage
} from "./prompt-input";

afterEach(cleanup);

function externalAttachments(overrides: Partial<AttachmentsContext> = {}): AttachmentsContext {
  return {
    add: vi.fn(),
    clear: vi.fn(),
    fileInputRef: createRef<HTMLInputElement>(),
    files: [],
    openFileDialog: vi.fn(),
    remove: vi.fn(),
    ...overrides
  };
}

it("routes pasted files to an external attachment owner", () => {
  const add = vi.fn();
  render(
    <PromptInput attachments={externalAttachments({ add })} onSubmit={vi.fn()}>
      <PromptInputBody>
        <PromptInputTextarea placeholder="Ask" />
      </PromptInputBody>
    </PromptInput>
  );

  const file = new File(["hello"], "hello.txt", { type: "text/plain" });
  fireEvent.paste(screen.getByPlaceholderText("Ask"), {
    clipboardData: {
      items: [{ kind: "file", getAsFile: () => file }]
    }
  });

  expect(add).toHaveBeenCalledWith([file]);
});

it("submits files from an external attachment owner", async () => {
  const onSubmit = vi.fn();
  const existing = {
    filename: "report.pdf",
    id: "uploaded-1",
    mediaType: "application/pdf",
    type: "file" as const,
    url: ""
  };

  const { container } = render(
    <PromptInput attachments={externalAttachments({ files: [existing] })} onSubmit={onSubmit}>
      <PromptInputBody>
        <PromptInputTextarea placeholder="Ask" />
      </PromptInputBody>
      <button type="submit">Send</button>
    </PromptInput>
  );

  fireEvent.change(screen.getByPlaceholderText("Ask"), { target: { value: "Summarize this" } });
  fireEvent.submit(container.querySelector("form")!);

  await waitFor(() => expect(onSubmit).toHaveBeenCalled());
  const firstCall = onSubmit.mock.calls[0];
  if (!firstCall) throw new Error("expected submit callback");
  const message = firstCall[0] as PromptInputMessage;
  expect(message.text).toBe("Summarize this");
  expect(message.files).toEqual([
    {
      filename: "report.pdf",
      mediaType: "application/pdf",
      type: "file",
      url: ""
    }
  ]);
});
