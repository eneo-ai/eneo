// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { SpaceProvider } from "@/features/spaces/use-space";
import { makeIntegration, makeSpace } from "@/features/spaces/testing/space-fixture";
import { browserApi } from "@/lib/api/browser";
import { replaceUrl } from "@/test/navigation";
import { renderInApp, testQueryClient } from "@/test/render";
import { skippedDocumentsQueryOptions } from "../queries";
import type { IntegrationSource } from "../sources";
import { SourcePage } from "./source-page";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("../use-sync-progress", () => ({
  useSyncProgress: () => ({ progress: {}, queued: new Set(), loaded: true })
}));
vi.mock("./folder-documents", () => ({ FolderDocuments: () => <p>Dokumentvy</p> }));
vi.mock("./activity-view", () => ({ ActivityView: () => <p>Aktivitetsvy</p> }));
afterEach(cleanup);

it("restores the URL's content view after a local tab selection", () => {
  const space = makeSpace({ integrations: [makeIntegration()] });
  const item = space.knowledge.integration_knowledge_list.items[0]!;
  const source: IntegrationSource = {
    kind: "item",
    id: item.id,
    name: item.name,
    integrationType: item.integration_type,
    embeddingModelId: item.embedding_model.id,
    items: [item]
  };
  const queryClient = testQueryClient();
  queryClient.setQueryData(["spaces", "space-1"], space);
  queryClient.setQueryData(
    skippedDocumentsQueryOptions(browserApi, queryClient, space.id, item).queryKey,
    {
      items: [],
      total: 0,
      truncated: false
    }
  );
  const route = "/spaces/space-1/knowledge/integrations/integration-1";
  renderInApp(
    <SpaceProvider routeId="space-1">
      <SourcePage source={source} />
    </SpaceProvider>,
    {
      route,
      queryClient
    }
  );
  expect(screen.getByText("Dokumentvy")).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Aktivitet" }));
  expect(screen.getByText("Aktivitetsvy")).toBeTruthy();
  act(() => replaceUrl(route));
  expect(screen.getByText("Dokumentvy")).toBeTruthy();
});
