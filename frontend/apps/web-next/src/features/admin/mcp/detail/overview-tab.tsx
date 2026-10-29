"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "use-intl";
import { useCallback, useEffect, useRef, useState } from "react";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAutosave, useAutosaveField } from "@/components/composites/use-autosave";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { MCP_KEY, type McpServer, type McpServerUpdatePayload, updateMcpServer } from "../mcp";
import { initials } from "../mcp-helpers";
import { TagInput } from "../tag-input";

const trim = (value: string) => value.trim();

export function OverviewTab({ server }: { server: McpServer }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const save = useCallback(
    async (body: McpServerUpdatePayload) => {
      await updateMcpServer(browserApi, server.id, body);
      await queryClient.invalidateQueries({ queryKey: MCP_KEY });
    },
    [server.id, queryClient]
  );

  const nameField = useAutosaveField({
    key: "mcp-name",
    value: server.name,
    normalize: trim,
    validate: (value) => value.length > 0,
    save: (value) => save({ name: value })
  });

  const descriptionField = useAutosaveField({
    key: "mcp-description",
    value: server.description ?? "",
    normalize: trim,
    save: (value) => save({ description: value || null })
  });

  const urlField = useAutosaveField({
    key: "mcp-url",
    value: server.http_url,
    normalize: trim,
    validate: (value) => value.length > 0,
    save: (value) => save({ http_url: value })
  });

  const iconField = useAutosaveField({
    key: "mcp-icon",
    value: server.icon_url ?? "",
    normalize: trim,
    save: (value) => save({ icon_url: value || null })
  });

  const docsField = useAutosaveField({
    key: "mcp-docs",
    value: server.documentation_url ?? "",
    normalize: trim,
    save: (value) => save({ documentation_url: value || null })
  });

  // Tags save on each add/remove (a discrete edit), not on blur.
  const runTags = useAutosave("mcp-tags");
  const [tags, setTags] = useState<string[]>(server.tags ?? []);
  const serverTagsKey = (server.tags ?? []).join("\u0000");
  const lastServerKey = useRef(serverTagsKey);
  useEffect(() => {
    if (lastServerKey.current !== serverTagsKey) {
      lastServerKey.current = serverTagsKey;
      setTags(server.tags ?? []);
    }
  }, [serverTagsKey, server.tags]);
  const commitTags = (next: string[]) => {
    setTags(next);
    void runTags(() => save({ tags: next.length > 0 ? next : null }));
  };

  return (
    <div className="flex flex-col gap-6">
      <SettingsGroup id="mcp-name" title={t("general")}>
        <SettingsRow title={t("name")} htmlFor="mcp-name-input">
          <Input
            id="mcp-name-input"
            value={nameField.value}
            aria-invalid={nameField.value.trim().length === 0}
            onChange={(event) => nameField.setValue(event.target.value)}
            onBlur={() => nameField.commit()}
          />
        </SettingsRow>
        <SettingsRow title={t("description")} htmlFor="mcp-description-input">
          <Textarea
            id="mcp-description-input"
            rows={2}
            value={descriptionField.value}
            onChange={(event) => descriptionField.setValue(event.target.value)}
            onBlur={() => descriptionField.commit()}
          />
        </SettingsRow>
        <SettingsRow title={t("url")} description={t("mcp_url_edit_hint")} htmlFor="mcp-url-input">
          <Input
            id="mcp-url-input"
            type="url"
            value={urlField.value}
            aria-invalid={urlField.value.trim().length === 0}
            onChange={(event) => urlField.setValue(event.target.value)}
            onBlur={() => urlField.commit()}
          />
        </SettingsRow>
      </SettingsGroup>

      <SettingsGroup title={t("mcp_section_presentation")}>
        <SettingsRow title={t("mcp_tags")} description={t("mcp_tags_hint")}>
          <div id="mcp-tags">
            <TagInput value={tags} onChange={commitTags} placeholder={t("mcp_tags_placeholder")} />
          </div>
        </SettingsRow>
        <SettingsRow title={t("mcp_icon_url")} htmlFor="mcp-icon-input">
          <div className="flex items-center gap-3">
            <Avatar className="size-9 rounded-md">
              {iconField.value.trim() ? <AvatarImage src={iconField.value.trim()} alt="" /> : null}
              <AvatarFallback className="rounded-md text-xs font-medium">
                {initials(server.name)}
              </AvatarFallback>
            </Avatar>
            <Input
              id="mcp-icon-input"
              type="url"
              placeholder="https://"
              value={iconField.value}
              onChange={(event) => iconField.setValue(event.target.value)}
              onBlur={() => iconField.commit()}
            />
          </div>
        </SettingsRow>
        <SettingsRow title={t("mcp_documentation_url")} htmlFor="mcp-docs-input">
          <Input
            id="mcp-docs-input"
            type="url"
            placeholder="https://"
            value={docsField.value}
            onChange={(event) => docsField.setValue(event.target.value)}
            onBlur={() => docsField.commit()}
          />
          {server.documentation_url && (
            <a
              href={server.documentation_url}
              target="_blank"
              rel="noopener noreferrer"
              className="text-muted-foreground hover:text-foreground inline-flex w-fit items-center gap-1 text-sm"
            >
              <ExternalLink className="size-3.5" aria-hidden="true" />
              {t("mcp_open_documentation")}
            </a>
          )}
        </SettingsRow>
      </SettingsGroup>
    </div>
  );
}
