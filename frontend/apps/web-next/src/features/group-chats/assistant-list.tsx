"use client";

import { Bot, Pencil, Plus, Trash2 } from "lucide-react";
import { Button as FormButton } from "@astryxdesign/core/Button";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useTranslations } from "use-intl";
import { useRef, useState } from "react";
import { revealProblems } from "@/components/composites/field-problem";
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
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useSpace } from "@/features/spaces/use-space";
import type { GroupChatAssistant } from "./use-group-chat";

function AssistantDescriptionDialog({
  assistant,
  mode,
  open,
  onOpenChange,
  onSave
}: {
  assistant: GroupChatAssistant;
  mode: "add" | "edit";
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSave: (userDescription: string | null) => void;
}) {
  const t = useTranslations();
  const [description, setDescription] = useState(assistant.user_description ?? "");
  const [submitted, setSubmitted] = useState(false);
  const field = useRef<HTMLTextAreaElement>(null);
  const required = !assistant.default_description;
  const problem =
    required && !description.trim()
      ? t(
          mode === "add"
            ? "description_required_to_add_assistant"
            : "description_required_for_assistant"
        )
      : null;

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (problem) {
      revealProblems(() => setSubmitted(true), field.current);
      return;
    }
    onSave(description.trim() || null);
    onOpenChange(false);
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{assistant.handle}</DialogTitle>
        </DialogHeader>
        <form onSubmit={submit} noValidate className="flex flex-col gap-4">
          <TextArea
            ref={field}
            label={t(mode === "add" ? "describe_responsibilities" : "description")}
            description={t(
              mode === "add" ? "add_description_to_help_determine" : "will_help_determine_assistant"
            )}
            value={description}
            rows={4}
            placeholder={assistant.default_description ?? t("enter_a_description")}
            onChange={setDescription}
            isRequired={required}
            status={submitted && problem ? { type: "error", message: problem } : undefined}
            statusVariant="detached"
            width="100%"
          />
          <DialogFooter>
            <FormButton label={t("cancel")} onClick={() => onOpenChange(false)} />
            <FormButton
              type="submit"
              variant="primary"
              label={t(mode === "add" ? "add_to_group" : "save")}
            />
          </DialogFooter>
        </form>
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
  const pickerTrigger = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState<{
    assistant: GroupChatAssistant;
    mode: "add" | "edit";
  } | null>(null);

  const available = (space.applications?.assistants.items ?? [])
    .filter((assistant) => !selected.some((entry) => entry.id === assistant.id))
    .map((assistant): GroupChatAssistant => ({
      id: assistant.id,
      handle: assistant.name,
      default_description: assistant.description ?? null,
      user_description: null
    }));

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
            onClick={() => setEditing({ assistant, mode: "edit" })}
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
            ref={pickerTrigger}
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
                      // The picker disappears; give the dialog a lasting focus-return target.
                      pickerTrigger.current?.focus();
                      setEditing({ assistant, mode: "add" });
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
        <AssistantDescriptionDialog
          key={`${editing.mode}:${editing.assistant.id}`}
          assistant={editing.assistant}
          mode={editing.mode}
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          onSave={(userDescription) =>
            onChange(
              editing.mode === "add"
                ? [...selected, { ...editing.assistant, user_description: userDescription }]
                : selected.map((entry) =>
                    entry.id === editing.assistant.id
                      ? { ...entry, user_description: userDescription }
                      : entry
                  )
            )
          }
        />
      )}
    </div>
  );
}
