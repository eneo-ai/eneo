// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { setRoute } from "@/test/navigation";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

const state = vi.hoisted(() => ({
  space: null as unknown,
  progress: [] as unknown[],
  skipped: {} as Record<string, unknown>,
  documents: {} as Record<string, unknown>
}));

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: (
      path: string,
      options?: { params?: { path?: { integration_knowledge_id?: string } } }
    ) => {
      const itemId = options?.params?.path?.integration_knowledge_id ?? "";
      const data =
        path === "/api/v1/spaces/{id}/knowledge/integrations/sync-progress/"
          ? { items: state.progress }
          : path.endsWith("/documents/skipped/")
            ? (state.skipped[itemId] ?? { items: [], total: 0, truncated: false, synced_at: null })
            : path.endsWith("/documents/")
              ? (state.documents[itemId] ?? {
                  items: [],
                  total_count: 0,
                  limit: 50,
                  offset: 0,
                  total_size: 0
                })
              : { items: [], count: 0 };
      return Promise.resolve({ data, response: new Response("{}") });
    }
  }
}));

import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { WrapperDetail } from "./wrapper-detail.client";

afterEach(() => {
  cleanup();
  state.progress = [];
  state.skipped = {};
  state.documents = {};
});

const folder = { wrapper_id: "w1", wrapper_name: "Byggnad" };

function show(
  items: Record<string, unknown>[],
  route = "/spaces/space-1/knowledge/integrations/wrapper/w1"
) {
  state.space = makeSpace({
    integrations: items.map((item) => makeIntegration({ ...folder, ...item }))
  });
  setRoute(route);
  return renderInApp(<WrapperDetail wrapperId="w1" />);
}

const mall = {
  id: "i1",
  name: "Mallar",
  folder_path: "/Mallar",
  metadata: {
    size: 0,
    last_sync_status: "success",
    last_synced_at: "2026-10-14T08:00:00Z",
    document_count: 12
  }
};
const protokoll = {
  id: "i2",
  name: "Protokoll",
  folder_path: "/Mallar/Protokoll",
  metadata: {
    size: 0,
    last_sync_status: "success",
    last_synced_at: "2026-10-14T08:00:00Z",
    document_count: 3
  }
};

describe("WrapperDetail", () => {
  it("shows the source with its folders, figures and the problems to look at", async () => {
    state.skipped.i1 = {
      items: [
        { file: "scan.pdf", reason: "No text layer (scanned document; OCR is not supported)" }
      ],
      total: 1,
      truncated: false,
      synced_at: "2026-10-14T08:00:00Z"
    };
    const { container } = show([mall, protokoll]);

    expect(screen.getByRole("heading", { level: 1, name: "Byggnad" })).toBeTruthy();
    const nav = screen.getByRole("navigation", { name: "Mappar" });
    expect(
      within(nav)
        .getByRole("link", { name: /Alla mappar/ })
        .getAttribute("aria-current")
    ).toBe("page");
    // The subfolder sits under its parent, which can be collapsed.
    fireEvent.click(within(nav).getByRole("button", { name: "Fäll ihop Mallar" }));
    expect(within(nav).queryByRole("link", { name: /Protokoll/ })).toBeNull();

    const overview = screen.getByRole("table", { name: "Mappar i Byggnad" });
    expect(within(overview).getByRole("link", { name: "Protokoll" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i2"
    );
    const searchable = screen.getByText("Sökbara dokument").closest("div")!;
    expect(within(searchable).getByText("15")).toBeTruthy();
    // The skipped list arrives after the first render.
    const problemsTab = screen.getByRole("tab", { name: /Problem/ });
    expect(await within(problemsTab).findByText("1")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("lists a chosen folder's documents and the files it could not read", async () => {
    state.documents.i1 = {
      items: [
        {
          id: "d1",
          title: "Avtalsmall.docx",
          relative_path: "/Mallar/Avtalsmall.docx",
          size: 2048,
          updated_at: "2026-10-01T08:00:00Z",
          source_metadata: []
        }
      ],
      total_count: 1,
      limit: 50,
      offset: 0,
      total_size: 2048
    };
    state.skipped.i1 = {
      items: [
        { file: "scan.pdf", reason: "No text layer (scanned document; OCR is not supported)" }
      ],
      total: 1,
      truncated: false,
      synced_at: "2026-10-14T08:00:00Z"
    };
    const { container } = show(
      [mall, protokoll],
      "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1"
    );

    const documents = await screen.findByRole("table", { name: "Dokument i Mallar" });
    expect(within(documents).getByRole("button", { name: /Avtalsmall\.docx/ })).toBeTruthy();
    expect(within(documents).getByText("Sökbar")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.click(await screen.findByRole("radio", { name: "Kunde inte läsas 1" }));
    const skipped = screen.getByRole("table", { name: "Filer i Mallar som inte gick att läsa" });
    expect(within(skipped).getByText("scan.pdf")).toBeTruthy();
    expect(
      within(skipped).getByText("Inget textlager (skannat dokument; OCR stöds inte)")
    ).toBeTruthy();
  });

  it("says when folders failed and leads to the problems", () => {
    show([
      mall,
      {
        ...protokoll,
        metadata: {
          ...protokoll.metadata,
          last_sync_status: "error",
          last_sync_error: "Graph timeout"
        }
      }
    ]);

    expect(screen.getByText("Senaste synken av 1 mapp misslyckades")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Visa problem" }).getAttribute("href")).toBe(
      "/spaces/space-1/knowledge/integrations/wrapper/w1?tab=problems"
    );
  });

  it("shows a running sync and, in its folder, the file being read", async () => {
    state.progress = [
      {
        integration_knowledge_id: "i1",
        sync_type: "full",
        phase: "processing",
        started_at: "2026-10-15T10:00:00Z",
        updated_at: "2026-10-15T10:01:00Z",
        total: 40,
        done: 10,
        indexed: 9,
        unchanged: 0,
        skipped: 1,
        deleted: 0,
        current: "Budget 2026.xlsx",
        recent: [{ name: "Plan.docx", outcome: "indexed" }]
      }
    ];
    show([mall, protokoll], "/spaces/space-1/knowledge/integrations/wrapper/w1?folder=i1");

    expect(await screen.findByRole("heading", { name: "Synk pågår" })).toBeTruthy();
    expect(screen.getByRole("progressbar", { name: "Synkförlopp för Byggnad" })).toBeTruthy();
    const live = screen.getByRole("region", { name: "Läses just nu" });
    expect(within(live).getByText("Budget 2026.xlsx")).toBeTruthy();
    expect(within(live).getByText("Plan.docx")).toBeTruthy();
  });
});
