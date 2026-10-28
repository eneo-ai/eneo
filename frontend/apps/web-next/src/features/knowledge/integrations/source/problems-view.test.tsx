// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { createTranslator } from "next-intl";
import { afterEach, describe, expect, it, vi } from "vitest";
import sv from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { IntegrationKnowledge } from "../../knowledge";
import { buildSourceProblems, type SkippedDocuments } from "../source-problems";
import type { SkipReasonCode } from "../skip-reasons";
import { inPlaceLink } from "@/components/composites/in-place-link";
import { ProblemsView } from "./problems-view";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));

afterEach(cleanup);

const t = createTranslator({ locale: "sv", messages: sv as Record<string, string> });

const ADMIN_URL = "https://eneo.example.se/admin/integrations";
const CREDENTIALS =
  "SharePoint credentials are invalid or expired; an administrator must reconnect the integration";

function item(
  id: string,
  name: string,
  metadata: Partial<NonNullable<IntegrationKnowledge["metadata"]>> = {},
  folderPath: string | null = null
): IntegrationKnowledge {
  return {
    id,
    name,
    folder_path: folderPath,
    metadata: { size: 0, last_sync_status: "success", ...metadata }
  } as IntegrationKnowledge;
}

type Entry = [file: string, code: SkipReasonCode, params?: Record<string, string>];

function skipped(entries: Entry[]): SkippedDocuments {
  return {
    items: entries.map(([file, code, params = {}]) => ({
      file,
      reason: "",
      code,
      params,
      retry: false
    })),
    total: entries.length,
    truncated: false,
    synced_at: "2026-10-14T08:00:00Z"
  };
}

function renderView(
  items: IntegrationKnowledge[],
  skippedByItem: Record<string, SkippedDocuments | null>,
  props: Partial<Parameters<typeof ProblemsView>[0]> = {}
) {
  return renderInApp(
    <ProblemsView
      problems={buildSourceProblems(items, skippedByItem, t)}
      isAdmin={false}
      adminIntegrationsUrl={ADMIN_URL}
      folderLink={(id) => inPlaceLink(`/source?folder=${id}`, () => {})}
      showFolders={false}
      onRetry={() => {}}
      {...props}
    />
  );
}

function groupTrigger(title: string): HTMLElement {
  return screen.getByRole("button", { name: new RegExp(title) });
}

function groupContent(title: string): HTMLElement {
  const content = document.getElementById(groupTrigger(title).getAttribute("aria-controls") ?? "");
  if (!content) throw new Error(`No content for ${title}`);
  return content;
}

describe("ProblemsView", () => {
  it("shows a loading state until the skipped lists arrive", () => {
    renderInApp(
      <ProblemsView
        problems={null}
        isAdmin={false}
        adminIntegrationsUrl={ADMIN_URL}
        folderLink={() => inPlaceLink("/", () => {})}
        showFolders={false}
        onRetry={() => {}}
      />
    );
    expect(screen.getByRole("status").textContent).toContain("Laddar...");
  });

  it("says so when nothing is wrong", () => {
    renderView([item("a", "Avtal")], { a: skipped([]) });
    expect(screen.getByText("Inga problem")).toBeTruthy();
    expect(screen.queryAllByRole("heading")).toEqual([]);
  });

  it("puts what stops the sync first, then the files by cause", async () => {
    const avtal = item(
      "a",
      "Avtal",
      { last_sync_status: "error", last_sync_error: "Graph timeout" },
      "Delade dokument/Avtal"
    );
    const mallar = item("b", "Mallar");
    const { container } = renderView(
      [avtal, mallar],
      {
        a: skipped([
          ["skanning.pdf", "no_text_layer"],
          ["bild.png", "unsupported_type", { label: "image/png" }]
        ]),
        b: skipped([["stor.pdf", "file_too_large", { limit_mb: "50" }]])
      },
      { showFolders: true }
    );

    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual([
      "Stoppar synken · 1",
      "Filer som inte blev sökbara · 2",
      "Hoppas över avsiktligt · 1"
    ]);
    expect(
      screen.getByRole("heading", {
        level: 3,
        name: "Synken av Delade dokument/Avtal misslyckades"
      })
    ).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Öppna Delade dokument/Avtal" }).getAttribute("href")
    ).toBe("/source?folder=a");

    // The first fixable cause starts open; the rest wait for a click.
    expect(groupTrigger("Skannade dokument utan text").getAttribute("aria-expanded")).toBe("true");
    expect(groupTrigger("För stora filer").getAttribute("aria-expanded")).toBe("false");
    expect(groupTrigger("Filtyper som inte används").getAttribute("aria-expanded")).toBe("false");

    const scanned = within(groupContent("Skannade dokument utan text"));
    expect(scanned.getByText("skanning.pdf")).toBeTruthy();
    expect(scanned.getByRole("link", { name: "Delade dokument/Avtal" })).toBeTruthy();
    expect(within(groupContent("För stora filer")).getByText("stor.pdf")).toBeTruthy();

    fireEvent.click(groupTrigger("För stora filer"));
    expect(groupTrigger("För stora filer").getAttribute("aria-expanded")).toBe("true");

    await expectNoAxeViolations(container);
  });

  it("shows the first ten files of a cause and the rest on request", () => {
    const files = Array.from({ length: 12 }, (_, i): Entry => [
      `skanning-${i}.pdf`,
      "no_text_layer"
    ]);
    renderView([item("a", "Avtal")], { a: skipped(files) });

    const content = () => within(groupContent("Skannade dokument utan text"));
    expect(content().getAllByRole("listitem")).toHaveLength(10);

    fireEvent.click(screen.getByRole("button", { name: "Visa alla 12 filer" }));
    expect(content().getAllByRole("listitem")).toHaveLength(12);

    fireEvent.click(screen.getByRole("button", { name: "Visa färre" }));
    expect(content().getAllByRole("listitem")).toHaveLength(10);
  });

  it("sends an administrator to the integrations to fix the sign-in", async () => {
    const items = [
      item("a", "Avtal", {
        last_sync_status: "error",
        last_sync_error: CREDENTIALS,
        last_synced_at: "2026-10-01T08:00:00Z"
      })
    ];
    const { container } = renderView(items, { a: skipped([]) }, { isAdmin: true });

    expect(
      screen.getByRole("heading", { name: "Inloggningen till SharePoint har gått ut" })
    ).toBeTruthy();
    expect(screen.getByText(/^Senaste lyckade synk: /)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Gå till Integrationer" }).getAttribute("href")).toBe(
      ADMIN_URL
    );
    expect(screen.queryByRole("button", { name: /Kopiera/ })).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("lets anyone else copy the link for an administrator", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    renderView([item("a", "Avtal", { last_sync_status: "error", last_sync_error: CREDENTIALS })], {
      a: skipped([])
    });

    expect(screen.queryByRole("link", { name: "Gå till Integrationer" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Kopiera länk till administratören" }));
    expect(writeText).toHaveBeenCalledWith(ADMIN_URL);
    await waitFor(() => expect(screen.getByRole("button", { name: "Kopierad!" })).toBeTruthy());
  });

  it("names the folders whose skipped files could not be loaded and retries them", () => {
    const onRetry = vi.fn();
    renderView([item("a", "Avtal"), item("b", "Mallar")], { a: skipped([]), b: null }, { onRetry });

    expect(screen.getByText("De överhoppade filerna för Mallar kunde inte hämtas.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});
