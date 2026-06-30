"use client";

import { useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave } from "@/components/composites/use-autosave";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import {
  highestFirst,
  securityClassificationsQueryOptions
} from "@/features/admin/security-classifications/security-classifications";
import { browserApi } from "@/lib/api/browser";
import { MCP_KEY, type McpServer, updateMcpServer } from "../mcp";

const NO_CLASSIFICATION = "__none__";

export function SecurityTab({ server }: { server: McpServer }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const run = useAutosave("mcp-security");
  const { data: security } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));
  const classifications = highestFirst(security.security_classifications);

  const current = server.security_classification?.id ?? NO_CLASSIFICATION;

  function change(value: string) {
    void run(async () => {
      await updateMcpServer(browserApi, server.id, {
        security_classification: value === NO_CLASSIFICATION ? null : { id: value }
      });
      await queryClient.invalidateQueries({ queryKey: MCP_KEY });
    });
  }

  return (
    <SettingsGroup
      id="mcp-security"
      title={t("security_classification")}
      description={t("mcp_security_hint")}
    >
      {!server.security_classification && (
        <p className="bg-warning/10 text-warning border-warning/30 flex items-start gap-2 rounded-lg border px-3 py-2 text-sm">
          <ShieldAlert className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          {t("mcp_quarantine_explainer")}
        </p>
      )}
      <SettingsRow title={t("security_classification")} htmlFor="mcp-classification-select">
        <Select value={current} onValueChange={change}>
          <SelectTrigger id="mcp-classification-select" className="w-full sm:w-80">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NO_CLASSIFICATION}>{t("none")}</SelectItem>
            {classifications.map((classification) => (
              <SelectItem key={classification.id} value={classification.id}>
                {classification.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {server.security_classification?.description && (
          <p className="text-muted-foreground text-sm">
            {server.security_classification.description}
          </p>
        )}
      </SettingsRow>
    </SettingsGroup>
  );
}
