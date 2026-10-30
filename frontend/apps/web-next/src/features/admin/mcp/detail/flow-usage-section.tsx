"use client";

import { Collapsible } from "@astryxdesign/core/Collapsible";
import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, Workflow } from "lucide-react";
import { useTranslations } from "use-intl";
import { LoadingState } from "@/components/composites/loading-state";
import { ListError } from "@/components/composites/query-state";
import { useAppContext } from "@/components/providers/app-context";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { browserApi } from "@/lib/api/browser";
import { mcpServerFlowUsageQueryOptions, mcpServerToolsQueryOptions } from "../mcp";

/**
 * Which published flows call the server's tools, so an administrator sees
 * what switching the server or a tool off breaks. Shown when the tenant has
 * flows switched on (the endpoint is behind the flows gate), whatever the
 * administrator's own flow permissions.
 */
export function FlowUsageSection({ serverId }: { serverId: string }) {
  const { settings } = useAppContext();
  return settings.flows_enabled === true ? <FlowUsage serverId={serverId} /> : null;
}

function FlowUsage({ serverId }: { serverId: string }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const usage = useQuery(mcpServerFlowUsageQueryOptions(browserApi, serverId));
  const tools = useQuery(mcpServerToolsQueryOptions(browserApi, serverId));
  // A flow links to its page only where that page opens for the admin: it
  // needs flows_manage and a space the admin belongs to. Unreadable spaces
  // only cost the links.
  const canOpenFlows = can("flows_manage");
  const spaces = useQuery({ ...spacesListQueryOptions(browserApi), enabled: canOpenFlows });
  const memberSpaceIds = new Set((spaces.data ?? []).map((space) => space.id));

  // A published flow may still call a tool the server no longer lists.
  const toolLabel = (toolId: string) => {
    const tool = tools.data?.find((candidate) => candidate.id === toolId);
    return tool ? tool.title || tool.name : t("flow_admin_usage_tool_not_listed");
  };

  if (usage.isPending) return <LoadingState rows={1} label={t("flow_admin_usage_loading")} />;
  if (usage.isError) {
    return (
      <ListError
        title={t("flow_admin_usage_failed")}
        error={usage.error}
        isRetrying={usage.isFetching}
        onRetry={() => void usage.refetch()}
      />
    );
  }
  const found = usage.data;
  if (found.total_count === 0) {
    return (
      <Text type="supporting" size="sm" as="p" display="block" className="m-0">
        {t("flow_admin_usage_none")}
      </Text>
    );
  }

  return (
    <div className="border-ax-border rounded-ax-container border px-3 py-1">
      <Collapsible
        defaultIsOpen={false}
        trigger={
          <span className="flex items-center gap-2 text-sm font-medium">
            <Workflow className="size-4 shrink-0" aria-hidden="true" />
            {t("flow_admin_usage_count", { count: found.total_count })}
          </span>
        }
      >
        <div className="flex flex-col gap-2 pb-2">
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_admin_usage_hint")}
          </Text>
          <List density="compact" hasDividers header={t("flow_admin_usage_list")}>
            {found.items.map((flow) => {
              const opens = canOpenFlows && memberSpaceIds.has(flow.space_id);
              return (
                <ListItem
                  key={flow.flow_id}
                  label={flow.flow_name}
                  href={opens ? `/spaces/${flow.space_id}/flows/${flow.flow_id}` : undefined}
                  endContent={
                    opens ? (
                      <ChevronRight className="text-ax-text-secondary size-4" aria-hidden="true" />
                    ) : undefined
                  }
                  description={
                    <span className="flex flex-col">
                      <span>
                        {t("flow_admin_usage_meta", {
                          space: flow.space_name,
                          version: flow.published_version
                        })}
                      </span>
                      <span>
                        {t("flow_admin_usage_tools", {
                          tools: flow.tool_ids.map(toolLabel).join(", ")
                        })}
                      </span>
                    </span>
                  }
                />
              );
            })}
          </List>
          {found.total_count > found.items.length ? (
            <Text type="supporting" size="sm" as="p" display="block" className="m-0">
              {t("flow_admin_usage_shown", {
                shown: found.items.length,
                total: found.total_count
              })}
            </Text>
          ) : null}
        </div>
      </Collapsible>
    </div>
  );
}
