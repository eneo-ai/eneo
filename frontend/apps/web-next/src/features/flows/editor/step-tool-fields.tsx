"use client";

import { Button } from "@astryxdesign/core/Button";
import { Selector } from "@astryxdesign/core/Selector";
import { Text } from "@astryxdesign/core/Text";
import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { TextInput } from "@astryxdesign/core/TextInput";
import { ListError } from "@/components/composites/query-state";
import { LoadingState } from "@/components/composites/loading-state";
import { FieldMessage, problemStatus, VariablePicker } from "./editor-fields";
import { toolOptionsQueryOptions } from "./editor-api";
import {
  argumentText,
  argumentValue,
  toolArguments,
  withArgument,
  type ToolConfig
} from "./step-configs";
import type { ToolOption } from "./step-types";
import type { VariableGroup } from "./step-variables";

function toolKey(tool: Pick<ToolConfig, "mcp_server_id" | "tool_id">): string {
  return `${tool.mcp_server_id}:${tool.tool_id}`;
}

/** Why a listed tool cannot be used now, in the reader's words. */
export function toolRefusalText(
  refusal: NonNullable<ToolOption["refusal"]>,
  t: ReturnType<typeof useTranslations>
): string {
  const key = `flow_step_editor_tool_refusal_${refusal}`;
  return t.has(key) ? t(key) : t("flow_step_editor_tool_refusal_other");
}

function ArgumentField({
  name,
  type,
  description,
  required,
  value,
  onChange,
  groups
}: {
  name: string;
  type: string | null;
  description: string | null;
  required: boolean;
  value: unknown;
  onChange: (value: unknown) => void;
  groups: VariableGroup[];
}) {
  const t = useTranslations();
  const text = argumentText(value);
  const parsed = argumentValue(text, type);
  const composed = /\{\{/.test(text) && !/^\s*\{\{[^{}]+\}\}\s*$/.test(text);
  return (
    <div className="flex flex-col gap-2">
      <TextInput
        label={name}
        description={[description, type ? t("flow_step_editor_tool_argument_type", { type }) : null]
          .filter(Boolean)
          .join(" ")}
        value={text}
        onChange={(next) => {
          const result = argumentValue(next, type);
          onChange(result.ok ? result.value : next);
        }}
        isRequired={required}
        isOptional={!required}
        autoComplete="off"
        status={problemStatus(
          composed
            ? t("flow_step_editor_tool_argument_composed")
            : !parsed.ok
              ? t("flow_step_editor_tool_argument_not_json", { type: type ?? "" })
              : null
        )}
      />
      <div>
        <VariablePicker
          groups={groups}
          label={t("flow_step_editor_tool_argument_read", { name })}
          onInsert={(token) => onChange(`{{${token}}}`)}
        />
      </div>
    </div>
  );
}

/**
 * The tool a step reads its input from, and a value per argument: a fixed
 * value or one whole reference to a run value. Values are stored as written
 * and are not secret; a server's credential stays with the server.
 */
export function ToolFields({
  flowId,
  tool,
  onChange,
  groups,
  problem
}: {
  flowId: string;
  tool: ToolConfig | null;
  onChange: (tool: ToolConfig | null) => void;
  groups: VariableGroup[];
  problem?: string;
}) {
  const t = useTranslations();
  const options = useQuery(toolOptionsQueryOptions(flowId));
  if (options.isPending)
    return <LoadingState label={t("flow_step_editor_tools_loading")} rows={2} />;
  if (options.isError) {
    return <ListError error={options.error} onRetry={() => void options.refetch()} />;
  }
  const items = options.data.items;
  const chosen = tool ? (items.find((item) => toolKey(item) === toolKey(tool)) ?? null) : null;
  const servers = [...new Set(items.map((item) => item.mcp_server_id))];
  const declared = toolArguments(chosen?.input_schema);
  const declaredNames = new Set(declared.map((argument) => argument.name));
  const others = tool ? Object.keys(tool.arguments).filter((name) => !declaredNames.has(name)) : [];

  const selectorOptions = servers.map((serverId) => {
    const serverTools = items.filter((item) => item.mcp_server_id === serverId);
    return {
      type: "section" as const,
      title: serverTools[0]?.mcp_server_name ?? serverId,
      options: serverTools.map((item) => ({
        value: toolKey(item),
        label: item.tool_name,
        description: item.refusal
          ? toolRefusalText(item.refusal, t)
          : (item.tool_description ?? undefined)
      }))
    };
  });
  if (tool && !chosen) {
    selectorOptions.unshift({
      type: "section",
      title: t("flow_step_editor_tool_saved"),
      options: [
        {
          value: toolKey(tool),
          label: t("flow_step_editor_tool_unavailable"),
          description: t("flow_step_editor_tool_unavailable_description")
        }
      ]
    });
  }

  return (
    <div className="flex flex-col gap-4">
      {items.length === 0 && !tool ? (
        <Text type="supporting" size="sm" as="p" display="block" className="m-0">
          {t("flow_step_editor_tools_none")}
        </Text>
      ) : (
        <Selector
          label={t("flow_step_editor_tool")}
          description={t("flow_step_editor_tool_description")}
          options={selectorOptions}
          value={tool ? toolKey(tool) : undefined}
          placeholder={t("flow_step_editor_tool_placeholder")}
          hasSearch={items.length > 8}
          isRequired
          onChange={(value) => {
            const item = items.find((candidate) => toolKey(candidate) === value);
            if (!item) return;
            if (tool && toolKey(tool) === value) return;
            onChange({ mcp_server_id: item.mcp_server_id, tool_id: item.tool_id, arguments: {} });
          }}
          status={problemStatus(problem)}
          width="100%"
        />
      )}
      {chosen?.refusal && (
        <Text type="supporting" size="sm" as="p" display="block" className="text-ax-warning m-0">
          {toolRefusalText(chosen.refusal, t)}
        </Text>
      )}
      {tool && declared.length > 0 && (
        <fieldset className="m-0 flex min-w-0 flex-col gap-4 border-0 p-0">
          <legend className="mb-2 p-0">
            <Text type="label">{t("flow_step_editor_tool_arguments")}</Text>
          </legend>
          <Text type="supporting" size="sm" as="p" display="block" className="m-0">
            {t("flow_step_editor_tool_arguments_description")}
          </Text>
          {declared.map((argument) => (
            <ArgumentField
              key={argument.name}
              name={argument.name}
              type={argument.type}
              description={argument.description}
              required={argument.required}
              value={tool.arguments[argument.name]}
              onChange={(value) =>
                onChange({ ...tool, arguments: withArgument(tool.arguments, argument.name, value) })
              }
              groups={groups}
            />
          ))}
        </fieldset>
      )}
      {tool && others.length > 0 && (
        <div className="flex flex-col gap-2">
          <Text type="label" as="p" display="block" className="m-0">
            {t("flow_step_editor_tool_other_arguments")}
          </Text>
          <ul className="m-0 flex list-none flex-col gap-1 p-0">
            {others.map((name) => (
              <li key={name} className="flex flex-wrap items-center gap-2">
                <Text type="code" size="xsm">
                  {name}
                </Text>
                <Button
                  label={t("flow_step_editor_tool_argument_remove", { name })}
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 className="size-4" aria-hidden="true" />}
                  onClick={() =>
                    onChange({ ...tool, arguments: withArgument(tool.arguments, name, undefined) })
                  }
                />
              </li>
            ))}
          </ul>
        </div>
      )}
      {items.length === 0 && !tool && <FieldMessage message={problem} />}
    </div>
  );
}
