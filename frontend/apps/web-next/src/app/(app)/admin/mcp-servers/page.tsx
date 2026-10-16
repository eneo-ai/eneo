import { permanentRedirect } from "next/navigation";
import { TOOLS_TAB_HREF } from "@/features/admin/tools/tools-tabs";

/**
 * The MCP servers are a tab of Verktyg now; an old link or bookmark lands on
 * that tab. The server detail route beneath this one stays.
 */
export default function AdminMcpServersRoute() {
  permanentRedirect(TOOLS_TAB_HREF["mcp-servers"]);
}
