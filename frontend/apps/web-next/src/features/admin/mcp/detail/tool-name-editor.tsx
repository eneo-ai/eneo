import { Button } from "@astryxdesign/core/Button";
import { useMutation } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { TextInput } from "@/components/astryx/text-input";
import { ListError } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { renameMcpTool, type McpServerTool } from "../mcp";

export function ToolNameEditor({
  serverId,
  tool,
  onSaved
}: {
  serverId: string;
  tool: McpServerTool;
  onSaved: () => void;
}) {
  const t = useTranslations();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState("");
  const trigger = useRef<HTMLButtonElement>(null);
  const rename = useMutation({
    mutationFn: () => renameMcpTool(browserApi, serverId, tool.id, name.trim() || null),
    onSuccess: () => {
      setEditing(false);
      onSaved();
    }
  });
  const cancel = () => {
    if (rename.isPending) return;
    trigger.current?.focus();
    setEditing(false);
  };
  return (
    <div className="mt-3 flex flex-col gap-3">
      <Button
        ref={trigger}
        label={t("mcp_rename_tool")}
        aria-label={`${t("mcp_rename_tool")}: ${tool.display_name ?? tool.title ?? tool.name}`}
        aria-expanded={editing}
        size="sm"
        variant="ghost"
        onClick={() => {
          if (editing) return;
          rename.reset();
          setName(tool.display_name ?? "");
          setEditing(true);
        }}
      />
      {editing && (
        <form
          className="flex flex-col gap-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!rename.isPending) rename.mutate();
          }}
        >
          <TextInput
            label={t("mcp_display_name")}
            description={t("mcp_display_name_hint")}
            value={name}
            onChange={setName}
            isReadOnly={rename.isPending}
            hasAutoFocus
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                event.preventDefault();
                cancel();
              }
            }}
          />
          {rename.isError && <ListError error={rename.error} compact />}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" label={t("save")} isLoading={rename.isPending} isInterruptible />
            <Button label={t("cancel")} variant="ghost" onClick={cancel} />
          </div>
        </form>
      )}
    </div>
  );
}
