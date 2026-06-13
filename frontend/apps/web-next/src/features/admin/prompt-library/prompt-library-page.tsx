"use client";

import {
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
  useSuspenseQuery
} from "@tanstack/react-query";
import { MoreHorizontal, Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";

type Entry = Schema<"PromptLibraryEntrySparse">;
const KEY = ["admin-prompt-library"];

export function promptLibraryQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: KEY,
    queryFn: async (): Promise<Entry[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/prompt-library/"));
      return page.items;
    }
  });
}

function EntryForm({
  entryId,
  initial,
  onDone
}: {
  entryId?: string;
  initial: { name: string; description: string; text: string };
  onDone: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [name, setName] = useState(initial.name);
  const [description, setDescription] = useState(initial.description);
  const [text, setText] = useState(initial.text);

  const save = useMutation({
    mutationFn: async (): Promise<void> => {
      const body = { name: name.trim(), description: description.trim() || null, text };
      if (entryId) {
        await unwrap(
          browserApi.PUT("/api/v1/admin/prompt-library/{id}/", {
            params: { path: { id: entryId } },
            body
          })
        );
      } else {
        await unwrap(browserApi.POST("/api/v1/admin/prompt-library/", { body }));
      }
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY });
      onDone();
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>{entryId ? t("edit") : t("governance_prompt_create")}</DialogTitle>
      </DialogHeader>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-2">
          <Label htmlFor="prompt-name">{t("name")}</Label>
          <Input id="prompt-name" value={name} onChange={(event) => setName(event.target.value)} />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="prompt-description">{t("description")}</Label>
          <Input
            id="prompt-description"
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="prompt-text">{t("prompt")}</Label>
          <Textarea
            id="prompt-text"
            rows={8}
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" disabled={save.isPending} onClick={onDone}>
          {t("cancel")}
        </Button>
        <Button
          disabled={save.isPending || !name.trim() || !text.trim()}
          onClick={() => save.mutate()}
        >
          {save.isPending ? t("loading") : t("save")}
        </Button>
      </DialogFooter>
    </DialogContent>
  );
}

function EntryDialog({
  open,
  onOpenChange,
  entryId
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Omitted → create mode. */
  entryId?: string;
}) {
  // Edit mode loads the full entry (the list is sparse and lacks the text);
  // the form mounts fresh (keyed) once the initial values are known.
  const { data: full } = useQuery({
    queryKey: [...KEY, entryId],
    enabled: open && Boolean(entryId),
    queryFn: () =>
      unwrap(
        browserApi.GET("/api/v1/admin/prompt-library/{id}/", {
          params: { path: { id: entryId as string } }
        })
      )
  });

  const ready = !entryId || Boolean(full);
  const initial = {
    name: full?.name ?? "",
    description: full?.description ?? "",
    text: full?.text ?? ""
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      {open && ready && (
        <EntryForm
          key={full?.id ?? "new"}
          entryId={entryId}
          initial={initial}
          onDone={() => onOpenChange(false)}
        />
      )}
    </Dialog>
  );
}

function EntryRow({ entry }: { entry: Entry }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/admin/prompt-library/{id}/", {
          params: { path: { id: entry.id } }
        })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: KEY });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <TableRow>
      <TableCell className="font-medium">{entry.name}</TableCell>
      <TableCell className="text-muted-foreground">{entry.description}</TableCell>
      <TableCell className="w-12">
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" aria-label={t("actions")}>
              <MoreHorizontal className="size-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={() => setShowEdit(true)}>
              <Pencil className="size-4" /> {t("edit")}
            </DropdownMenuItem>
            <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
              <Trash2 className="size-4" /> {t("delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </TableCell>
      <EntryDialog open={showEdit} onOpenChange={setShowEdit} entryId={entry.id} />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete")}
        description={t("governance_prompt_delete_confirm", { name: entry.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </TableRow>
  );
}

export function PromptLibraryPage() {
  const t = useTranslations();
  const { data: entries } = useSuspenseQuery(promptLibraryQueryOptions(browserApi));
  const [showCreate, setShowCreate] = useState(false);

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("governance_tab_prompts")}>
        <Button onClick={() => setShowCreate(true)}>
          <Plus className="size-4" /> {t("governance_prompt_create")}
        </Button>
      </PageHeader>
      {entries.length === 0 ? (
        <EmptyState title={t("governance_prompts_empty")} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("name")}</TableHead>
              <TableHead>{t("description")}</TableHead>
              <TableHead className="w-12" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {entries.map((entry) => (
              <EntryRow key={entry.id} entry={entry} />
            ))}
          </TableBody>
        </Table>
      )}
      <EntryDialog open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
