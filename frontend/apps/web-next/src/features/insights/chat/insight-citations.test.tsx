// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MessageResponse } from "@/components/ai-elements/message";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import {
  insightCitationReferences,
  InsightCitationsContext,
  type OpenCitedConversation
} from "./insight-citations";

afterEach(cleanup);

const FIRST = "1a2b3c4d-0000-4000-8000-000000000001";
const SECOND = "9f8e7d6c-0000-4000-8000-000000000002";

function renderAnswer(text: string, open: OpenCitedConversation | null = vi.fn()) {
  const view = renderInApp(
    <InsightCitationsContext value={open}>
      <MessageResponse
        remarkPlugins={insightCitationReferences.remarkPlugins}
        components={insightCitationReferences.components}
      >
        {text}
      </MessageResponse>
    </InsightCitationsContext>
  );
  return { ...view, open };
}

describe("conversations an analysis cites", () => {
  it("draws each cited conversation as a button that opens it", async () => {
    const { open, container } = renderAnswer(
      `Många frågar om parkering (session ${FIRST}) och om bygglov (session ${SECOND}).`
    );
    const first = screen.getByRole("button", { name: "konversation 1a2b3c4d" });
    expect(screen.getByRole("button", { name: "konversation 9f8e7d6c" })).toBeTruthy();
    // The ids are not left in the text as written.
    expect(container.textContent).not.toContain(FIRST);
    expect(container.textContent).toContain("(konversation 1a2b3c4d)");

    fireEvent.click(first);
    expect(open).toHaveBeenCalledWith(FIRST, first);
    await expectNoAxeViolations(container);
  });

  it("reads the forms the tools write and a citation in backticks", () => {
    const { open } = renderAnswer(
      `Se session_id=${SECOND.toUpperCase()} och (\`session ${FIRST}\`).`
    );
    fireEvent.click(screen.getByRole("button", { name: "konversation 9f8e7d6c" }));
    expect(open).toHaveBeenCalledWith(SECOND, expect.any(HTMLElement));
    fireEvent.click(screen.getByRole("button", { name: "konversation 1a2b3c4d" }));
    expect(open).toHaveBeenLastCalledWith(FIRST, expect.any(HTMLElement));
  });

  it("leaves code blocks, bare ids and other links as they are", () => {
    const { container } = renderAnswer(
      `Id ${FIRST} utan hänvisning, [källan](https://example.com) och\n\n\`\`\`\nsession ${SECOND}\n\`\`\``
    );
    expect(screen.queryByRole("button", { name: /^konversation/ })).toBeNull();
    expect(container.textContent).toContain(FIRST);
    expect(container.textContent).toContain(`session ${SECOND}`);
    expect(screen.getByRole("link", { name: "källan" }).getAttribute("href")).toBe(
      "https://example.com/"
    );
  });

  it("names a citation as text where nothing can open it", () => {
    const { container } = renderAnswer(`Se (session ${FIRST}).`, null);
    expect(screen.queryByRole("button")).toBeNull();
    expect(container.textContent).toContain("Se (konversation 1a2b3c4d).");
  });
});
