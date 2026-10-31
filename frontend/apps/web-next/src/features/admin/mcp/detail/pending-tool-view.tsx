import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "use-intl";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { formatBytes } from "@/lib/format";
import { mcpToolViewQueryOptions, type McpServerTool } from "../mcp";

export function PendingToolView({ serverId, tool }: { serverId: string; tool: McpServerTool }) {
  const t = useTranslations();
  const locale = useLocale();
  const facts = useQuery(mcpToolViewQueryOptions(browserApi, serverId, tool));
  const ui = (tool.pending_meta ?? tool.meta)?.ui as { resourceUri?: unknown } | undefined;
  const uri = facts.data?.uri ?? (typeof ui?.resourceUri === "string" ? ui.resourceUri : "");
  return (
    <section className="border-warning/30 mt-3 rounded-lg border p-3">
      <h3 className="text-sm font-medium">
        {t(tool.ui_resource_sha256 ? "mcp_tool_view_changed" : "mcp_tool_view_new")}
      </h3>
      {uri && <p className="font-mono text-xs break-all">{uri}</p>}
      <p className="my-2 text-sm">{t("mcp_tool_view_explanation")}</p>
      <QueryStateBoundary query={facts} rows={2}>
        {(view) => (
          <ul className="list-disc space-y-1 pl-4 text-sm">
            <li>{t("mcp_tool_view_size", { size: formatBytes(view.size_bytes, locale) })}</li>
            <li>
              {view.connect_domains.length ? (
                <>
                  {t("mcp_tool_view_connects")}{" "}
                  <span className="font-mono break-all">{view.connect_domains.join(", ")}</span>
                </>
              ) : (
                t("mcp_tool_view_no_network")
              )}
            </li>
            {view.resource_domains.length > 0 && (
              <li>
                {t("mcp_tool_view_loads_from")}{" "}
                <span className="font-mono break-all">{view.resource_domains.join(", ")}</span>
              </li>
            )}
            {view.frame_domains.length > 0 && (
              <li>
                {t("mcp_tool_view_embeds")}{" "}
                <span className="font-mono break-all">{view.frame_domains.join(", ")}</span>
              </li>
            )}
            {view.permissions.length > 0 && (
              <li>
                {t("permissions")}:{" "}
                <span className="font-mono break-all">{view.permissions.join(", ")}</span>
              </li>
            )}
          </ul>
        )}
      </QueryStateBoundary>
    </section>
  );
}
