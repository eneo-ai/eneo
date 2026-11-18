// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { browserApi } from "@/lib/api/browser";
import { API_BASE } from "@/lib/api/base";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp, testQueryClient } from "@/test/render";
import { loadSourceDocument, SourceDocumentPage, type SourceDocument } from "./source-document";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));

const id = "11111111-1111-4111-8111-111111111111";
const blob: NonNullable<SourceDocument["blob"]> = {
  id,
  metadata: { title: "Taxa.pdf", embedding_model_id: "embedding", size: 1 },
  original_available: true,
  text: "En offentlig rapport"
};
const data: SourceDocument = { id, blob, collection: null, website: null, space: null };
const result = (data: unknown) => ({ data, response: new Response("{}") });
const refusal = (status: number) => ({
  error: { message: "Unavailable" },
  response: new Response("", { status })
});
const clients: ReturnType<typeof testQueryClient>[] = [];
function client() {
  const queryClient = testQueryClient();
  clients.push(queryClient);
  return queryClient;
}
beforeEach(() => {
  api.GET.mockReset();
  api.POST.mockReset();
});
afterEach(() => {
  cleanup();
  for (const queryClient of clients.splice(0)) queryClient.clear();
  vi.restoreAllMocks();
});

describe("copied document references", () => {
  it("shows an accessible document, its collection and its knowledge location", async () => {
    api.GET.mockImplementation(async (path: string) => {
      if (path === "/api/v1/info-blobs/{id}/") return result({ ...blob, group_id: "collection" });
      if (path === "/api/v1/groups/{id}/")
        return result({ id: "collection", name: "Avgifter", space_id: "space" });
      return result({ id: "space", name: "Bygglov", personal: false, organization: false });
    });
    const document = await loadSourceDocument(client(), browserApi, id);
    const { container } = renderInApp(<SourceDocumentPage document={document} />);
    expect(screen.getByRole("heading", { name: "Taxa.pdf" })).toBeTruthy();
    expect(screen.getByText("En offentlig rapport")).toBeTruthy();
    expect(screen.getByText("Samling: Avgifter")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Öppna kunskapen i Bygglov" }).getAttribute("href")
    ).toBe("/spaces/space/knowledge");
    await expectNoAxeViolations(container);
  });

  it.each([403, 404, 422])(
    "does not reveal a document's existence or metadata after %s",
    async (status) => {
      api.GET.mockResolvedValue(refusal(status));
      const document = await loadSourceDocument(client(), browserApi, id);
      expect(document).toEqual({ id, blob: null, collection: null, website: null, space: null });
      const { container } = renderInApp(<SourceDocumentPage document={document} />);
      expect(
        screen.getByRole("heading", { name: "Dokumentet är inte tillgängligt för dig" })
      ).toBeTruthy();
      expect(screen.queryByText("Taxa.pdf")).toBeNull();
      expect(screen.queryByRole("button", { name: "Ladda ner originalfilen" })).toBeNull();
      expect(screen.getByText(`${id} – ${location.origin}/documents/${id}`)).toBeTruthy();
      await expectNoAxeViolations(container);
    }
  );

  it("keeps server failures distinct from a document access refusal", async () => {
    api.GET.mockResolvedValue(refusal(503));
    await expect(loadSourceDocument(client(), browserApi, id)).rejects.toMatchObject({
      status: 503
    });
  });

  it("rechecks invalidated document access instead of showing a previously readable copy", async () => {
    const queryClient = client();
    api.GET.mockResolvedValueOnce(result(blob));
    expect((await loadSourceDocument(queryClient, browserApi, id)).blob?.text).toBe(blob.text);
    await queryClient.invalidateQueries({ queryKey: ["info-blobs", id] });
    api.GET.mockResolvedValueOnce(refusal(403));
    expect((await loadSourceDocument(queryClient, browserApi, id)).blob).toBeNull();
  });

  it("does not let an inaccessible collection hide a readable document", async () => {
    api.GET.mockImplementation(async (path: string) =>
      path === "/api/v1/info-blobs/{id}/"
        ? result({ ...blob, group_id: "collection" })
        : refusal(403)
    );
    const document = await loadSourceDocument(client(), browserApi, id);
    expect(document.blob?.text).toBe(blob.text);
    expect(document.collection).toBeNull();
    expect(document.space).toBeNull();
  });

  it("downloads the original through the existing signed same-origin URL", async () => {
    api.POST.mockResolvedValue(
      result({
        url: `http://backend:8000/api/v1/info-blobs/${id}/original/download/?token=capability`
      })
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderInApp(<SourceDocumentPage document={data} />);
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner originalfilen" }));
    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect((click.mock.contexts[0] as HTMLAnchorElement).getAttribute("href")).toBe(
      `${API_BASE}/api/v1/info-blobs/${id}/original/download/?token=capability`
    );
  });

  it("does not begin a late download after the reader has left the document", async () => {
    let finish!: (value: ReturnType<typeof result>) => void;
    api.POST.mockReturnValue(
      new Promise((resolve) => {
        finish = resolve;
      })
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    const view = renderInApp(<SourceDocumentPage document={data} />);
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner originalfilen" }));
    view.unmount();
    await act(async () =>
      finish(
        result({
          url: `http://backend:8000/api/v1/info-blobs/${id}/original/download/?token=capability`
        })
      )
    );
    expect(click).not.toHaveBeenCalled();
  });

  it("displays extracted text when the original no longer exists", () => {
    renderInApp(
      <SourceDocumentPage document={{ ...data, blob: { ...blob, original_available: false } }} />
    );
    expect(screen.getByText("En offentlig rapport")).toBeTruthy();
    expect(
      screen.getByText(
        "Originalfilen finns inte längre lagrad. Den extraherade texten visas nedan."
      )
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ladda ner originalfilen" })).toBeNull();
  });
});
