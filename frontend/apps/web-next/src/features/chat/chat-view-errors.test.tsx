// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { ChatView, type ActivityState } from "./chat-view";
import { ChatTestProviders, installDomPolyfills } from "./testing";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  sent: [] as { text: string; body: unknown }[]
}));

// A transport that always fails before streaming starts.
vi.mock("@/lib/chat/transport", () => ({
  createChatTransport: () => ({
    sendMessages: async ({ messages, body }: { messages: EneoUIMessage[]; body: unknown }) => {
      const last = messages.at(-1);
      const text = last?.parts.find((part) => part.type === "text");
      spies.sent.push({ text: text?.type === "text" ? text.text : "", body });
      throw new Error("Tjänsten svarar inte");
    },
    reconnectToStream: async () => null
  })
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

beforeAll(() => installDomPolyfills());
afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.sent.length = 0;
});

const partner: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten"
};

function Harness() {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <ChatTestProviders>
      <ChatView partner={partner} activity={activity} onActivityChange={setActivity} />
    </ChatTestProviders>
  );
}

describe("ChatView when generation fails", () => {
  it("shows and announces the error, keeps the question and retries it", async () => {
    render(<Harness />);
    const textarea = screen.getByRole("textbox", {
      name: "Meddelande till Upphandlingsassistenten"
    });
    fireEvent.change(textarea, { target: { value: "Vilken gräns gäller?" } });
    fireEvent.click(screen.getByRole("button", { name: "Skicka meddelande" }));

    expect(await screen.findByText("Tjänsten svarar inte")).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Tjänsten svarar inte");
    // The failed first question returns to the composer instead of vanishing.
    await waitFor(() =>
      expect(
        (screen.getByRole("textbox", { name: /Meddelande till/ }) as HTMLTextAreaElement).value
      ).toBe("Vilken gräns gäller?")
    );

    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    await waitFor(() => expect(spies.sent).toHaveLength(2));
    expect(spies.sent.map((call) => call.text)).toEqual([
      "Vilken gräns gäller?",
      "Vilken gräns gäller?"
    ]);
  });
});
