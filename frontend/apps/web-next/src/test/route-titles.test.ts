// @vitest-environment jsdom
import { createMemoryHistory, type AnyRoute } from "@tanstack/react-router";
import { createTranslator } from "use-intl";
import { expect, it } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { routeTree } from "@/routeTree.gen";
import { createAppRouter } from "@/router";
import { testQueryClient } from "./render";

const TITLE_EXCEPTIONS: Record<string, string> = {
  "/": "Redirects to the viewer's personal space.",
  "/spaces/": "Redirects to the space list.",
  "/spaces/$spaceId/": "Redirects to the space's chat or overview.",
  "/spaces/$spaceId/knowledge/integrations/": "Redirects to the space's knowledge page.",
  "/admin/mcp-servers/": "Redirects to the MCP servers tab on the tools page.",
  "/admin/": "Inherits Administration from the admin layout.",
  "/spaces/$spaceId/overview": "Inherits the space name from the space layout.",
  "/spaces/$spaceId/chat": "Inherits the space name from the space layout.",
  "/dashboard/$assistantId/{-$sessionId}":
    "Inherits Eneo from the root, as the dashboard chat does today."
};

// Initializing the real router resolves fullPath; no loaders or API calls run.
createAppRouter(
  { queryClient: testQueryClient(), t: createTranslator({ locale: "sv", messages }) },
  { routeTree, history: createMemoryHistory() }
);

function leafRoutes(route: AnyRoute): AnyRoute[] {
  const children: AnyRoute[] = Object.values(route.children ?? {});
  return children.length ? children.flatMap(leafRoutes) : [route];
}

const leaves = leafRoutes(routeTree).map((route) => ({ path: route.fullPath, route }));

it.each(leaves.filter(({ path }) => !Object.hasOwn(TITLE_EXCEPTIONS, path)))(
  "$path owns its page title",
  ({ route }) => {
    expect(route.options.head).toBeTypeOf("function");
  }
);

it.each(Object.entries(TITLE_EXCEPTIONS))(
  "%s remains a reasoned exception for a leaf without its own title",
  (path, reason) => {
    const leaf = leaves.find((entry) => entry.path === path);
    expect(leaf, `Stale title exception: ${path}`).toBeDefined();
    expect(reason.trim()).not.toBe("");
    expect(
      leaf?.route.options.head,
      `Title exception is no longer needed: ${path}`
    ).toBeUndefined();
  }
);
