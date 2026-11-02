// @vitest-environment jsdom
import { createRoute } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { loadPreview } from "@/features/workspace/preview/load-preview";
import Link from "@/lib/link";
import type { EneoUIMessage } from "@/lib/chat/types";
import { toast } from "@/lib/toast";
import { renderWithRouter } from "@/test/router";
import { observedElements, reportResize } from "@/test/setup-dom";
import { replaceInstructionText } from "@/test/skill-instructions";
import { ChatView, type ActivityState } from "./chat-view";

vi.unmock("@/lib/link");

const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { POST: post } }));
vi.mock("@/features/workspace/preview/load-preview", () => ({
  loadPreview: vi.fn(),
  PreviewTooLargeError: class extends Error {}
}));
afterEach(() => vi.restoreAllMocks());
const file = { id: "file-1", name: "Plan.md", mimetype: "text/markdown", size: 10 };
const messages: EneoUIMessage[] = [
  {
    id: "answer-1",
    role: "assistant",
    parts: [{ type: "text", text: "Här" }],
    metadata: { generatedFiles: [file] }
  }
];
function Chat() {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatView
      partner={{ type: "assistant", id: "assistant-1", name: "Assistant" }}
      initialSessionId="session-1"
      initialMessages={messages}
      activity={activity}
      onActivityChange={setActivity}
    />
  );
}

it("keeps a document after a failed save and cancelled navigation, then leaves after saving", async () => {
  let refuseSave = true;
  let finishSave!: () => void;
  const saved = new Promise<void>((resolve) => {
    finishSave = resolve;
  });
  const toastError = vi.spyOn(toast, "error");
  post.mockImplementation(async (path: string) => {
    if (path === "/api/v1/files/{id}/original/signed-url/")
      return {
        data: { url: "https://example.test/api/v1/files/file-1/original/download/?token=fixture" },
        response: new Response()
      };
    if (path === "/api/v1/conversations/{session_id}/documents/{file_id}/versions/") {
      if (refuseSave)
        return { error: { message: "Unavailable" }, response: new Response(null, { status: 503 }) };
      await saved;
      return {
        data: { ...file, id: "file-2", revises_file_id: file.id },
        response: new Response()
      };
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.mocked(loadPreview).mockResolvedValue({
    kind: "markdown",
    text: "# Plan\n\nOriginal.\n",
    truncated: false
  });
  const { router, container } = await renderWithRouter(
    <Link href="/done">Leave conversation</Link>,
    {
      route: "/chat",
      routes: (root) => [
        createRoute({ getParentRoute: () => root, path: "/chat", component: Chat }),
        createRoute({ getParentRoute: () => root, path: "/done", component: () => <h1>Done</h1> })
      ]
    }
  );
  const log = screen.getByRole("log");
  const regions = observedElements().filter((element) => element.contains(log));
  const region = regions.find((element) => regions.every((other) => element.contains(other)))!;
  act(() => reportResize(region, { width: 1200, height: 600 }));
  fireEvent.click(await screen.findByRole("button", { name: "Förhandsgranska Plan.md" }));
  await screen.findByRole("heading", { name: "Plan", level: 1 });
  const editor = container.querySelector<HTMLElement>('.tiptap[contenteditable="true"]')!;
  expect(editor).not.toBeNull();
  await act(async () => replaceInstructionText(editor, "Changed document."));
  const save = await screen.findByRole("button", { name: "Spara" });
  fireEvent.click(save);
  await waitFor(() =>
    expect(toastError).toHaveBeenCalledWith("Ändringarna kunde inte sparas. Försök igen.")
  );
  await act(async () => {
    fireEvent.click(screen.getByRole("link", { name: "Leave conversation" }));
  });
  await screen.findByRole("alertdialog", { name: "Lämna sidan?" });
  expect(router.state.location.pathname).toBe("/chat");
  fireEvent.click(within(screen.getByRole("alertdialog")).getByRole("button", { name: "Avbryt" }));
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(editor.textContent).toBe("Changed document.");
  refuseSave = false;
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
  fireEvent.click(screen.getByRole("link", { name: "Leave conversation" }));
  await screen.findByRole("alertdialog");
  await act(async () => finishSave());
  await screen.findByRole("heading", { name: "Done" });
  await waitFor(() => expect(screen.queryByRole("button", { name: "Spara" })).toBeNull());
  await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
  expect(router.state.location.pathname).toBe("/done");
  expect(post).toHaveBeenLastCalledWith(
    "/api/v1/conversations/{session_id}/documents/{file_id}/versions/",
    {
      params: { path: { session_id: "session-1", file_id: "file-1" } },
      body: { content: "Changed document.\n" }
    }
  );
  expect(screen.queryByRole("alertdialog")).toBeNull();
});
