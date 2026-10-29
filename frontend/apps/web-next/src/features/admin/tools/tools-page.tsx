"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useTranslations } from "use-intl";
import { PageHeader } from "@/components/composites/page-header";
import { McpServersPage } from "../mcp/mcp-page";
import { CapabilityProvidersPage } from "./capability-providers-page";
import { TOOLS_TAB_HREF, type ToolsTab } from "./tools-tabs";

// Links navigate; the TabList only needs the value to mark the current tab.
function ignoreSelection() {}

/**
 * Verktyg: one page for what assistants can do and where their tools run.
 * Funktioner lists each function with its sources (the provider built into
 * Eneo offered first); MCP-servrar lists the servers spaces and assistants
 * connect, with the function sources on request. The tabs are links, so a
 * tab has an address and the browser's back button works.
 */
export function ToolsPage({ tab }: { tab: ToolsTab }) {
  const t = useTranslations();
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 pb-16">
      <PageHeader title={t("tools")} tour="admin-tools" />
      <TabList
        value={tab}
        onChange={ignoreSelection}
        size="lg"
        overflow="scroll"
        aria-label={t("tools")}
      >
        <Tab value="functions" href={TOOLS_TAB_HREF.functions} label={t("tools_functions")} />
        <Tab value="mcp-servers" href={TOOLS_TAB_HREF["mcp-servers"]} label={t("mcp_servers")} />
      </TabList>
      {tab === "functions" ? <CapabilityProvidersPage embedded /> : <McpServersPage embedded />}
    </div>
  );
}
