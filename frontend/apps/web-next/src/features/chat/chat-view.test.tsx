// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ChatPartner, EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ChatView, type ActivityState } from "./chat-view";

const api = vi.hoisted(() => ({
  GET: vi.fn(async (path: string) => {
    if (path === "/api/v1/dashboard/") {
      return {
        data: {
          spaces: {
            items: [
              {
                id: "space-1",
                name: "Upphandling",
                personal: false,
                organization: false,
                applications: {
                  assistants: {
                    items: [{ id: "assistant-9", name: "Upphandlingsassistenten", icon_id: null }]
                  }
                }
              }
            ]
          }
        },
        response: new Response()
      };
    }
    return { data: undefined, error: { message: "unexpected" }, response: new Response() };
  }),
  POST: vi.fn(async () => ({ data: undefined, response: new Response() })),
  DELETE: vi.fn(),
  PATCH: vi.fn()
}));

vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

const personal: ChatPartner = {
  type: "default-assistant",
  id: "personal-1",
  name: "Personlig assistent"
};

const assistant: ChatPartner = {
  type: "assistant",
  id: "assistant-1",
  name: "Upphandlingsassistenten",
  description: "Granskar upphandlingar mot LOU."
};

const history: EneoUIMessage[] = [
  { id: "m1-q", role: "user", parts: [{ type: "text", text: "Vad gäller?" }] },
  {
    id: "m1",
    role: "assistant",
    parts: [{ type: "text", text: "Direktupphandlingsgränsen är 700 000 kr.", state: "done" }]
  }
];

function Harness({
  partner,
  messages = [],
  sessionId = null
}: {
  partner: ChatPartner;
  messages?: EneoUIMessage[];
  sessionId?: string | null;
}) {
  const [activity, setActivity] = useState<ActivityState | null>(null);
  return (
    <div className="flex h-[600px] flex-col">
      <ChatView
        partner={partner}
        initialMessages={messages}
        initialSessionId={sessionId}
        activity={activity}
        onActivityChange={setActivity}
      />
    </div>
  );
}

describe("ChatView start state", () => {
  it("greets the user, fills the composer from a starter card and links their assistants", async () => {
    renderInApp(<Harness partner={personal} />);
    expect(
      screen.getByRole("heading", { level: 1, name: /^God (morgon|dag|kväll), Anna$/ })
    ).toBeTruthy();

    const textarea = screen.getByRole("textbox", { name: "Meddelande till Personlig assistent" });
    fireEvent.click(screen.getByRole("button", { name: /Gör en plan/ }));
    expect((textarea as HTMLTextAreaElement).value).toBe("Gör en konkret plan för: ");
    expect(document.activeElement).toBe(textarea);

    const quickLinks = await screen.findByRole("region", { name: "Dina assistenter" });
    const link = within(quickLinks).getByRole("link", { name: /Upphandlingsassistenten/ });
    expect(link.getAttribute("href")).toBe("/spaces/space-1/chat?type=assistant&id=assistant-9");
    expect(within(quickLinks).getByRole("link", { name: "Visa alla" })).toBeTruthy();
  });

  it("introduces other assistants by name and description", () => {
    renderInApp(<Harness partner={assistant} />);
    expect(screen.getByRole("heading", { level: 1, name: "Upphandlingsassistenten" })).toBeTruthy();
    expect(screen.getByText("Granskar upphandlingar mot LOU.")).toBeTruthy();
    expect(screen.queryByRole("region", { name: "Dina assistenter" })).toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(<Harness partner={personal} />);
    await screen.findByRole("region", { name: "Dina assistenter" });
    await expectNoAxeViolations(container);
  });
});

describe("ChatView conversation", () => {
  it("names the message list and keeps it out of live announcements", () => {
    renderInApp(<Harness partner={assistant} messages={history} sessionId="session-1" />);
    const log = screen.getByRole("log", { name: "Konversation" });
    expect(log.getAttribute("aria-live")).toBe("off");
    expect(within(log).getByRole("article", { name: "Ditt meddelande" })).toBeTruthy();
    expect(
      within(log).getByRole("article", { name: /svar från upphandlingsassistenten/i })
    ).toBeTruthy();
    // Answer text never sits in a live region (announcements go through
    // Astryx useAnnounce instead of reading streamed tokens).
    const answerText = within(log).getByText("Direktupphandlingsgränsen är 700 000 kr.");
    expect(answerText.closest('[aria-live]:not([aria-live="off"])')).toBeNull();
    expect(screen.getByRole("button", { name: "Skicka meddelande" })).toBeTruthy();
  });

  it("offers session feedback on the latest answer", () => {
    renderInApp(<Harness partner={assistant} messages={history} sessionId="session-1" />);
    expect(screen.getByRole("button", { name: "Bra svar" })).toBeTruthy();
  });

  it("has no axe violations", async () => {
    const { container } = renderInApp(
      <Harness partner={assistant} messages={history} sessionId="session-1" />
    );
    await waitFor(() => expect(screen.getByRole("log")).toBeTruthy());
    await expectNoAxeViolations(container);
  });
});
