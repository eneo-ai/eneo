"use client";

import { Button as AstryxButton } from "@astryxdesign/core/Button";
import { useCollator } from "@astryxdesign/core/i18n";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import {
  paginateData,
  pixel,
  proportional,
  Table,
  useTablePagination,
  useTableSortable,
  useTableSortableState,
  type TableColumn,
  type TableSortComparator
} from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Pencil, SearchX, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { Streamdown } from "streamdown";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { formatBytes } from "@/lib/format";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { matchesSearch } from "@/features/spaces/resource-filter";
import type { InfoBlob } from "./knowledge";
import { SpaceTableFrame } from "@/features/spaces/table-frame";

const PAGE_SIZE = 100;

function useInvalidateBlobs() {
  const queryClient = useQueryClient();
  // Blob lists hang off collections/websites; counts live on the space.
  return () =>
    Promise.all(
      ["collections", "websites", "spaces"].map((key) =>
        queryClient.invalidateQueries({ queryKey: [key] })
      )
    );
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
      void invalidateBlobs();
      setShowEdit(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  const remove = useRemovalMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/info-blobs/{id}/", { params: { path: { id: blob.id } } })),
    refresh: invalidateBlobs,
    onRemoved: () => setShowDelete(false)
  });

  return (
    <>
      <MoreMenu
        label={
          blob.metadata.title
            ? t("space_more_actions_for", { name: blob.metadata.title })
            : t("actions")
        }
        alignment="end"
        items={[
          {
            label: t("edit"),
            icon: <Pencil aria-hidden="true" />,
            onClick: () => setShowEdit(true)
          },
          {
            label: t("delete"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive",
            onClick: () => setShowDelete(true)
          }
        ]}
      />

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

/** The file name opens a preview of its extracted text. */
function BlobNameCell({ blob }: { blob: InfoBlob }) {
  const [showPreview, setShowPreview] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setShowPreview(true)}
        className="text-ax-text focus-visible:outline-ring rounded-ax-inner flex min-h-6 max-w-xl items-center gap-2.5 text-left font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
      >
        <span
          aria-hidden="true"
          className="bg-ax-muted text-ax-text-secondary rounded-ax-inner flex size-7 shrink-0 items-center justify-center"
        >
          <FileText className="size-4" />
        </span>
        <span className="break-words">{blob.metadata.title}</span>
      </button>
      {showPreview && (
        <BlobPreviewDialog blob={blob} open={showPreview} onOpenChange={setShowPreview} />
      )}
    </>
  );
}

type BlobSortKey = "name" | "size";

function blobComparators(
  compare: (a: string, b: string) => number
): Record<BlobSortKey, TableSortComparator<InfoBlob>> {
  return {
    name: (a, b) => compare(a.metadata.title ?? "", b.metadata.title ?? ""),
    size: (a, b) => a.metadata.size - b.metadata.size
  };
}

/**
 * Files of a collection or website: a search box, name and size sortable by
 * their headers (unsorted keeps the upload order), and pages of 100 (the
 * pager only shows when there is more than one).
 */
export function BlobTable({ blobs, canEdit }: { blobs: InfoBlob[]; canEdit: boolean }) {
  const t = useTranslations();
  const collator = useCollator();
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(1);

  const filtered = blobs.filter((blob) => matchesSearch([blob.metadata.title], filter));
  const comparators = useMemo(() => blobComparators(collator.compare), [collator]);
  const { sortedData, sortConfig } = useTableSortableState<InfoBlob, BlobSortKey>({
    data: filtered,
    comparators,
    allowUnsortedState: true
  });
  const sortPlugin = useTableSortable<InfoBlob, BlobSortKey>(sortConfig);
  // The list can shrink under the current page (a delete on the last page, a
  // recrawl with fewer pages): show its last page instead of an empty one.
  const pageCount = Math.max(1, Math.ceil(sortedData.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const paginationPlugin = useTablePagination<InfoBlob>({
    page: currentPage,
    onPageChange: setPage,
    totalItems: sortedData.length,
    pageSize: PAGE_SIZE,
    variant: "count",
    align: "end",
    label: t("space_files_pagination_label")
  });

  if (blobs.length === 0) {
    return <EmptyState icon={<FileText />} title={t("no_files_uploaded_yet")} headingLevel={3} />;
  }

  const columns: TableColumn<InfoBlob>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(4),
      sortable: true,
      renderCell: (blob) => <BlobNameCell blob={blob} />
    },
    {
      key: "size",
      header: t("size"),
      width: proportional(1),
      sortable: true,
      renderCell: (blob) => formatBytes(blob.metadata.size)
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(64),
      align: "end",
      renderCell: (blob) => (canEdit ? <BlobActions blob={blob} /> : null)
    }
  ];

  return (
    <div className="flex flex-col gap-3">
      <ResourceFilterInput
        value={filter}
        label={t("space_filter_files_label")}
        placeholder={t("space_filter_files_label")}
        resultCount={filtered.length}
        onChange={(value) => {
          setFilter(value);
          setPage(1);
        }}
      />
      {filtered.length === 0 ? (
        <EmptyState icon={<SearchX />} title={t("no_results_found")} headingLevel={3} isCompact />
      ) : (
        <SpaceTableFrame>
          <Table
            data={paginateData(sortedData, currentPage, PAGE_SIZE)}
            columns={columns}
            idKey="id"
            plugins={{ sort: sortPlugin, pagination: paginationPlugin }}
          />
        </SpaceTableFrame>
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
      void invalidateBlobs();
      setOpen(false);
      setTitle("");
      setText("");
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <AstryxButton label={t("add_text")} isDisabled={disabled} onClick={() => setOpen(true)} />
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
