// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { makeSpace } from "@/features/spaces/testing/space-fixture";
import type { Space } from "@/features/spaces/space";
import { renderInApp, testQueryClient } from "@/test/render";
import { GroupChatEditor } from "./group-chat-editor";

vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  return { useSpace: () => useSpaceFromQuery(() => state.space) };
});
const state = vi.hoisted(() => ({ space: null as unknown as Space }));
afterEach(cleanup);

it("offers no helper on its sections: no 'Fråga' in a heading row", () => {
  state.space = makeSpace();
  const queryClient = testQueryClient();
  queryClient.setQueryData(["group-chats", "group-chat-1"], {
    id: "group-chat-1",
    name: "Byggrådet",
    permissions: ["read", "edit", "publish", "insight_toggle"],
    tools: { assistants: [] },
    allow_mentions: false,
    show_response_label: false,
    published: false,
    insight_enabled: false,
    icon_id: null
  });
  renderInApp(<GroupChatEditor groupChatId="group-chat-1" />, {
    queryClient,
    route: "/spaces/space-1/group-chats/group-chat-1/edit"
  });

  expect(screen.getByRole("heading", { name: "Publicering" })).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Fråga/ })).toBeNull();
  expect(document.querySelector("[data-settings-group-end] button")).toBeNull();
});
