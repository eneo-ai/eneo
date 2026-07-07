"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Streamdown } from "streamdown";
import { toast } from "sonner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import type { InfoBlob } from "./knowledge";

const PAGE_SIZE = 100;

function useInvalidateBlobs() {
  const queryClient = useQueryClient();
  return () => {
    // Blob lists hang off collections/websites; counts live on the space.
    void queryClient.invalidateQueries({ queryKey: ["collections"] });
    void queryClient.invalidateQueries({ queryKey: ["websites"] });
    void queryClient.invalidateQueries({ queryKey: ["spaces"] });
  };
}

/** Dialog that lazily loads and renders a blob's text content. */
export function BlobPreviewDialog({
  blob,
  open,
  onOpenChange
}: {
  blob: InfoBlob;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const { data, isPending, isError } = useQuery({
    queryKey: ["info-blobs", blob.id],
    queryFn: () =>
      unwrap(browserApi.GET("/api/v1/info-blobs/{id}/", { params: { path: { id: blob.id } } })),
    enabled: open
  });

  async function copyText() {
    if (data?.text) {
      await navigator.clipboard.writeText(data.text);
      toast.success(t("copied_to_clipboard"));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[80vh] flex-col sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{blob.metadata.title ?? blob.id}</DialogTitle>
        </DialogHeader>
        <div className="min-h-0 flex-1 overflow-y-auto rounded-md border p-4 text-sm">
          {isPending ? (
            <p className="text-muted-foreground">{t("loading")}</p>
          ) : isError ? (
            <p className="text-destructive">{t("attachment_error_loading_content")}</p>
          ) : (
            <Streamdown>{data.text ?? ""}</Streamdown>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={copyText} disabled={!data?.text}>
            {t("copy_to_clipboard")}
          </Button>
          <Button onClick={() => onOpenChange(false)}>{t("close")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function BlobActions({ blob }: { blob: InfoBlob }) {
  const t = useTranslations();
  const invalidateBlobs = useInvalidateBlobs();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [title, setTitle] = useState(blob.metadata.title ?? "");

  const rename = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/info-blobs/{id}/", {
          params: { path: { id: blob.id } },
          body: { metadata: { title } }
        })
      ),
    onSuccess: () => {
      invalidateBlobs();
      setShowEdit(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const remove = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/info-blobs/{id}/", { params: { path: { id: blob.id } } })),
    onSuccess: () => {
      invalidateBlobs();
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
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

      <Dialog open={showEdit} onOpenChange={setShowEdit}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("edit_file")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="blob-title">{t("name")}</Label>
            <Input
              id="blob-title"
              value={title}
              onChange={(event) => setTitle(event.target.value)}
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowEdit(false)}>
              {t("cancel")}
            </Button>
            <Button onClick={() => rename.mutate()} disabled={rename.isPending}>
              {rename.isPending ? t("saving") : t("save_changes")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete")}
        description={t("confirm_delete_file", { fileName: blob.metadata.title ?? "" })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

function BlobRow({ blob, canEdit }: { blob: InfoBlob; canEdit: boolean }) {
  const [showPreview, setShowPreview] = useState(false);
  return (
    <TableRow>
      <TableCell>
        <button
          type="button"
          onClick={() => setShowPreview(true)}
          className="flex max-w-md items-center gap-2 truncate font-medium hover:underline"
          title={blob.metadata.title ?? undefined}
        >
          <FileText className="text-muted-foreground size-4 shrink-0" />
          <span className="truncate">{blob.metadata.title}</span>
        </button>
        {showPreview && (
          <BlobPreviewDialog blob={blob} open={showPreview} onOpenChange={setShowPreview} />
        )}
      </TableCell>
      <TableCell className="text-muted-foreground">{formatBytes(blob.metadata.size)}</TableCell>
      <TableCell className="text-right">{canEdit && <BlobActions blob={blob} />}</TableCell>
    </TableRow>
  );
}

export function BlobTable({ blobs, canEdit }: { blobs: InfoBlob[]; canEdit: boolean }) {
  const t = useTranslations();
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return blobs;
    return blobs.filter((blob) => (blob.metadata.title ?? "").toLowerCase().includes(needle));
  }, [blobs, filter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const visible = filtered.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  if (blobs.length === 0) {
    return <EmptyState title={t("no_files_uploaded_yet")} />;
  }

  return (
    <div className="flex flex-col gap-3">
      <Input
        value={filter}
        placeholder={t("filter")}
        className="max-w-xs"
        onChange={(event) => {
          setFilter(event.target.value);
          setPage(0);
        }}
      />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("name")}</TableHead>
            <TableHead>{t("size")}</TableHead>
            <TableHead className="w-16" />
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((blob) => (
            <BlobRow key={blob.id} blob={blob} canEdit={canEdit} />
          ))}
        </TableBody>
      </Table>
      {pageCount > 1 && (
        <div className="flex items-center justify-end gap-2 text-sm">
          <span className="text-muted-foreground">
            {currentPage + 1} / {pageCount}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={currentPage === 0}
            onClick={() => setPage(currentPage - 1)}
          >
            {t("previous")}
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={currentPage >= pageCount - 1}
            onClick={() => setPage(currentPage + 1)}
          >
            {t("next")}
          </Button>
        </div>
      )}
    </div>
  );
}

/** "Add text" — creates an info-blob from pasted text. */
export function AddTextDialog({
  collectionId,
  disabled
}: {
  collectionId: string;
  disabled?: boolean;
}) {
  const t = useTranslations();
  const invalidateBlobs = useInvalidateBlobs();
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.POST("/api/v1/groups/{id}/info-blobs/", {
          params: { path: { id: collectionId } },
          body: { info_blobs: [{ text, metadata: { title } }] }
        })
      ),
    onSuccess: () => {
      invalidateBlobs();
      setOpen(false);
      setTitle("");
      setText("");
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <Button variant="outline" disabled={disabled} onClick={() => setOpen(true)}>
        {t("add_text")}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>{t("add_text")}</DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              if (title && text) create.mutate();
            }}
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="text-title">{t("title")}</Label>
              <Input
                id="text-title"
                value={title}
                required
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <div className="flex flex-col gap-2">
              <Label htmlFor="text-content">{t("content")}</Label>
              <Textarea
                id="text-content"
                value={text}
                required
                rows={12}
                onChange={(event) => setText(event.target.value)}
              />
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              <Button type="submit" disabled={create.isPending || !title || !text}>
                {create.isPending ? t("submitting") : t("submit")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </>
  );
}
