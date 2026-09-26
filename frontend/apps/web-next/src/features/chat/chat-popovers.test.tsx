// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ComposerAttachments } from "./attachments";
import { ContextUsageBar } from "./context-usage-bar";
import { ChatMcpServers, type McpServerSummary } from "./mcp-controls";
import { McpSnippetButton } from "./message-parts";

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

function renderInChat(ui: React.ReactNode) {
  return renderInApp(ui);
}

const servers: McpServerSummary[] = [
  { id: "lou", name: "LOU-register", description: "Tröskelvärden och praxis", icon_url: null },
  { id: "diarium", name: "Diarium", description: null, icon_url: null }
];

function McpHarness({ onDisabled = vi.fn() }: { onDisabled?: (ids: Set<string>) => void }) {
  const [disabled, setDisabled] = useState<Set<string>>(new Set(["diarium"]));
  const [autoAccept, setAutoAccept] = useState(false);
  return (
    <ChatMcpServers
      servers={servers}
      disabledServerIds={disabled}
      autoAcceptTools={autoAccept}
      onDisabledServerIdsChange={(next) => {
        onDisabled(next);
        setDisabled(next);
      }}
      onAutoAcceptToolsChange={setAutoAccept}
    />
  );
}

describe("ChatMcpServers", () => {
  it("switches servers and tool approval from the tools popover", async () => {
    const onDisabled = vi.fn();
    renderInChat(<McpHarness onDisabled={onDisabled} />);
    const trigger = screen.getByRole("button", { name: "Verktyg: 1 av 2 aktiva" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    const popover = await screen.findByRole("dialog", { name: "MCP-servrar" });
    expect(trigger.getAttribute("aria-expanded")).toBe("true");

    const diarium = within(popover).getByRole("switch", { name: "Diarium" });
    expect((diarium as HTMLInputElement).checked).toBe(false);
    fireEvent.click(diarium);
    expect(onDisabled).toHaveBeenLastCalledWith(new Set());
    expect(screen.getByRole("button", { name: "Verktyg: 2 av 2 aktiva" })).toBeTruthy();

    fireEvent.click(within(popover).getByRole("button", { name: "Alla av" }));
    expect(onDisabled).toHaveBeenLastCalledWith(new Set(["lou", "diarium"]));

    const auto = within(popover).getByRole("switch", { name: "Kör verktyg automatiskt" });
    expect(auto.getAttribute("aria-describedby")).toBeTruthy();
    fireEvent.click(auto);
    expect(within(popover).getByText("Verktyg körs automatiskt utan godkännande")).toBeTruthy();
    await expectNoAxeViolations(popover);
  });
});

describe("ContextUsageBar", () => {
  const usage = {
    contextLimit: 10_000,
    lockedInputTokens: 6_000,
    lockedOutputTokens: 1_500,
    pendingTextTokens: 200,
    pendingFileTokens: 0,
    usedTokens: 7_700,
    willExceedContext: false
  };

  it("explains the estimate in a popover and can be hidden", async () => {
    renderInChat(
      <ContextUsageBar
        usage={usage}
        modelName="Claude Haiku 4.5"
        cumulativeTokens={9_000}
        turnCount={2}
      />
    );
    const bar = screen.getByRole("button", { name: /^Kontextanvändning:/ });
    fireEvent.click(bar);
    const popover = await screen.findByRole("dialog", { name: "Beräknad kontextanvändning" });
    expect(within(popover).getByText("Ditt meddelande")).toBeTruthy();
    expect(within(popover).getByText("Claude Haiku 4.5")).toBeTruthy();
    await expectNoAxeViolations(popover);

    fireEvent.click(within(popover).getByRole("button", { name: "Dölj fält" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Visa kontextanvändning" })).toBeTruthy()
    );
    expect(screen.queryByRole("button", { name: /^Kontextanvändning:/ })).toBeNull();
  });
});

describe("chat dialogs", () => {
  it("shows an MCP source's snippet and returns focus to it", async () => {
    renderInChat(
      <McpSnippetButton
        source={{ key: "mcp-1", title: "Policy -> Avsnitt 4", sourceId: "ref-1" }}
        snippet={{
          uri: "https://intranat.kommun.se/policy",
          content: "Direktupphandling får göras under **700 000 kr**.",
          pageRange: "4, 9",
          section: "Avsnitt 4"
        }}
      />
    );
    const trigger = screen.getByRole("button", { name: "Policy -> Avsnitt 4" });
    trigger.focus();
    fireEvent.click(trigger);
    const dialog = await screen.findByRole("dialog", { name: "Policy -> Avsnitt 4" });
    expect(within(dialog).getByText(/Direktupphandling får göras/)).toBeTruthy();
    expect(within(dialog).getByText(/sid\. 4, 9/)).toBeTruthy();
    const external = within(dialog).getByRole("link", { name: "Öppna källa" });
    expect(external.getAttribute("href")).toBe("https://intranat.kommun.se/policy");
    await expectNoAxeViolations(dialog);

    fireEvent.click(within(dialog).getByRole("button", { name: "Klar" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(trigger));
  });

  function renderAttachment(name: string, mimetype: string) {
    return renderInChat(
      <ComposerAttachments
        attachments={{
          attachments: [
            {
              key: "a-1",
              fileId: "file-1",
              name,
              size: 2048,
              mimetype,
              uploading: false,
              previewUrl: "blob:preview"
            }
          ],
          removeAttachment: vi.fn()
        }}
      />
    );
  }

  it("previews a composer attachment in a named dialog", async () => {
    renderAttachment("Karta.png", "image/png");
    fireEvent.click(screen.getByRole("button", { name: /^Förhandsvisning: Karta\.png/ }));
    const dialog = await screen.findByRole("dialog", { name: "Karta.png" });
    expect(within(dialog).getByRole("img", { name: "Karta.png" }).getAttribute("src")).toBe(
      "blob:preview"
    );
    await expectNoAxeViolations(dialog);
  });

  it("shows a PDF attachment in a titled frame", async () => {
    renderAttachment("Policy.pdf", "application/pdf");
    fireEvent.click(screen.getByRole("button", { name: /^Förhandsvisning: Policy\.pdf/ }));
    const dialog = await screen.findByRole("dialog", { name: "Policy.pdf" });
    expect(within(dialog).getByTitle("Policy.pdf").getAttribute("src")).toBe("blob:preview");
  });
});
