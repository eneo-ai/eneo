import { createFileRoute, redirect } from "@tanstack/react-router";
import { TOOLS_TAB_HREF } from "@/features/admin/tools/tools-tabs";

export const Route = createFileRoute("/_app/admin/mcp-servers/")({
  beforeLoad: () => {
    throw redirect({ href: TOOLS_TAB_HREF["mcp-servers"], replace: true });
  }
});
