// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ComposerAttachments } from "./attachments";
import type { Capability } from "@/features/capabilities/capabilities";
import type { ChatCapability } from "./chat-capabilities";
import { ChatTools, type McpServerSummary } from "./mcp-controls";
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

const capabilities: ChatCapability[] = [
  { purpose: "web_search", available: true, reason: null },
  { purpose: "image_generation", available: false, reason: "no_active_provider" }
];

function McpHarness({
  onDisabled = vi.fn(),
  onDisabledCapabilities = vi.fn(),
  withCapabilities = false,
  modelSupportsTools
}: {
  onDisabled?: (ids: Set<string>) => void;
  onDisabledCapabilities?: (purposes: Set<Capability>) => void;
  withCapabilities?: boolean;
  modelSupportsTools?: boolean;
}) {
  const [disabled, setDisabled] = useState<Set<string>>(new Set(["diarium"]));
  const [disabledCapabilities, setDisabledCapabilities] = useState<Set<Capability>>(new Set());
  const [autoAccept, setAutoAccept] = useState(false);
  return (
    <ChatTools
      capabilities={withCapabilities ? capabilities : []}
      disabledCapabilities={disabledCapabilities}
      servers={servers}
      disabledServerIds={disabled}
      autoAcceptTools={autoAccept}
      modelSupportsTools={modelSupportsTools}
      onDisabledCapabilitiesChange={(next) => {
        onDisabledCapabilities(next);
        setDisabledCapabilities(next);
      }}
      onDisabledServerIdsChange={(next) => {
        onDisabled(next);
        setDisabled(next);
      }}
      onAutoAcceptToolsChange={setAutoAccept}
    />
  );
}

describe("ChatTools", () => {
  it("switches servers and tool approval from the tools popover", async () => {
    const onDisabled = vi.fn();
    renderInChat(<McpHarness onDisabled={onDisabled} />);
    const trigger = screen.getByRole("button", { name: "Verktyg: 1 av 2 aktiva" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(trigger);
    const popover = await screen.findByRole("dialog", { name: "Verktyg" });
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

  it("renders every tool unavailable when the model cannot call tools", async () => {
    renderInChat(<McpHarness modelSupportsTools={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Verktyg: 0 av 2 aktiva" }));
    const popover = await screen.findByRole("dialog", { name: "Verktyg" });

    for (const name of ["LOU-register", "Diarium"]) {
      const row = within(popover).getByRole("switch", { name });
      expect(row.hasAttribute("disabled") || row.getAttribute("aria-disabled") === "true").toBe(
        true
      );
      expect((row as HTMLInputElement).checked).toBe(false);
    }
    // The header notice plus one description per row.
    expect(within(popover).getAllByText("Modellen stödjer inte verktygsanrop.")).toHaveLength(3);
    expect(within(popover).queryByRole("button", { name: "Alla av" })).toBeNull();
    expect(within(popover).queryByRole("switch", { name: "Kör verktyg automatiskt" })).toBeNull();
    await expectNoAxeViolations(popover);
  });

  it("lists capabilities as a group of switches above the servers and counts them", async () => {
    const onDisabled = vi.fn();
    const onDisabledCapabilities = vi.fn();
    renderInChat(
      <McpHarness
        withCapabilities
        onDisabled={onDisabled}
        onDisabledCapabilities={onDisabledCapabilities}
      />
    );
    // One available capability on, plus one of two servers.
    fireEvent.click(screen.getByRole("button", { name: "Verktyg: 2 av 4 aktiva" }));
    const popover = await screen.findByRole("dialog", { name: "Verktyg" });

    const groups = within(popover).getAllByRole("list");
    expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual([
      "Funktioner",
      "MCP-servrar"
    ]);
    const web = within(popover).getByRole("switch", { name: "Webbsökning" });
    expect((web as HTMLInputElement).checked).toBe(true);
    fireEvent.click(web);
    expect(onDisabledCapabilities).toHaveBeenLastCalledWith(new Set(["web_search"]));
    expect(screen.getByRole("button", { name: "Verktyg: 1 av 4 aktiva" })).toBeTruthy();

    // Unavailable: off, disabled and described by its reason.
    const image = within(popover).getByRole("switch", { name: "Bildgenerering" });
    expect((image as HTMLInputElement).checked).toBe(false);
    expect(image.hasAttribute("disabled") || image.getAttribute("aria-disabled") === "true").toBe(
      true
    );
    expect(within(popover).getByText("Ingen källa är aktiv.")).toBeTruthy();

    // All on sweeps both groups, skipping what cannot be used.
    fireEvent.click(within(popover).getByRole("button", { name: "Alla på" }));
    expect(onDisabledCapabilities).toHaveBeenLastCalledWith(new Set());
    expect(onDisabled).toHaveBeenLastCalledWith(new Set());
    expect(screen.getByRole("button", { name: "Verktyg: 3 av 4 aktiva" })).toBeTruthy();
    await expectNoAxeViolations(popover);
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
