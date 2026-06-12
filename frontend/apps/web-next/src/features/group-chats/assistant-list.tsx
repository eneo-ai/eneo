"use client";

import { Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList
} from "@/components/ui/command";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Textarea } from "@/components/ui/textarea";
import { useSpace } from "@/features/spaces/use-space";
import type { GroupChatAssistant } from "./use-group-chat";

function EditDescriptionDialog({
  assistant,
  open,
  onOpenChange,
  onSave
}: {
  assistant: GroupChatAssistant;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (userDescription: string | null) => void;
}) {
  const t = useTranslations();
  const [description, setDescription] = useState(assistant.user_description ?? "");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{assistant.handle}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor="assistant-user-description">{t("description")}</Label>
          <Textarea
            id="assistant-user-description"
            value={description}
            rows={4}
            placeholder={assistant.default_description ?? ""}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            onClick={() => {
              onSave(description.trim() === "" ? null : description.trim());
              onOpenChange(false);
            }}
          >
            {t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * The assistants answering in a group chat: list with per-assistant
 * description override, plus a picker over the space's assistants.
 */
export function GroupChatAssistantList({
  selected,
  onChange
}: {
  selected: GroupChatAssistant[];
  onChange: (next: GroupChatAssistant[]) => void;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const [pickerOpen, setPickerOpen] = useState(false);
  const [editing, setEditing] = useState<GroupChatAssistant | null>(null);

  const available = (space.applications?.assistants.items ?? [])
    .filter((assistant) => !selected.some((entry) => entry.id === assistant.id))
    .map(
      (assistant): GroupChatAssistant => ({
        id: assistant.id,
        handle: assistant.name,
        default_description: assistant.description ?? null,
        user_description: null
      })
    );

  return (
    <div className="flex flex-col gap-2">
      {selected.map((assistant) => (
        <div key={assistant.id} className="flex h-12 items-center gap-2 rounded-xl border px-3">
          <Bot className="text-muted-foreground size-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate text-sm">{assistant.handle}</span>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("edit")}
            onClick={() => setEditing(assistant)}
          >
            <Pencil className="size-4" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={t("delete")}
            onClick={() => onChange(selected.filter((entry) => entry.id !== assistant.id))}
          >
            <Trash2 className="size-4" />
          </Button>
        </div>
      ))}

      <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground hover:bg-muted/50 flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-dashed text-sm font-medium transition-colors"
          >
            <Plus className="size-4" />
            {t("add_assistant")}
          </button>
        </PopoverTrigger>
        <PopoverContent align="start" className="w-(--radix-popover-trigger-width) min-w-80 p-0">
          <Command>
            <CommandInput placeholder={`${t("name")}...`} />
            <CommandList>
              <CommandEmpty>{t("no_results")}</CommandEmpty>
              <CommandGroup>
                {available.map((assistant) => (
                  <CommandItem
                    key={assistant.id}
                    value={assistant.handle}
                    onSelect={() => {
                      onChange([...selected, assistant]);
                      setPickerOpen(false);
                    }}
                  >
                    <Bot className="size-4 shrink-0" />
                    <span className="truncate">{assistant.handle}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>

      {editing && (
        <EditDescriptionDialog
          key={editing.id}
          assistant={editing}
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          onSave={(userDescription) =>
            onChange(
              selected.map((entry) =>
                entry.id === editing.id ? { ...entry, user_description: userDescription } : entry
              )
            )
          }
        />
      )}
    </div>
  );
}
