"use client";

import { DropdownMenu } from "@astryxdesign/core/DropdownMenu";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useTranslations } from "use-intl";
import { useState } from "react";
import { toast } from "@/lib/toast";
import { saveBlob } from "@/features/files/signed-file-url";
import type { DocumentExport, DocumentExportFormat } from "./document-export";

// Product names of the formats; the same in every language.
const FORMATS = {
  md: { name: "Markdown", ending: ".md" },
  docx: { name: "Word", ending: ".docx" },
  pdf: { name: "PDF", ending: ".pdf" }
} as const;

/**
 * The formats a Markdown document can be handed over in: as it is, or as Word
 * or PDF rendered by the assistant's document tool. Availability is checked
 * each time the menu opens, for the document on show.
 */
export function ExportMenu({
  fileId,
  title,
  namesImages,
  exporting,
  onSaveOriginal,
  compact
}: {
  fileId: string;
  /** The document's title, which names the exported file. */
  title: string;
  /** The Markdown names images by their Eneo file; saved as it is, it leaves Eneo without them. */
  namesImages: boolean;
  exporting: DocumentExport;
  onSaveOriginal: () => void;
  /** An icon-only trigger, for a narrow header. */
  compact: boolean;
}) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<DocumentExportFormat | null>(null);
  const availability = useQuery({
    queryKey: ["conversations", "document-export", fileId],
    queryFn: () => exporting.availability(),
    enabled: open,
    staleTime: 0,
    retry: false
  });

  async function exportAs(format: DocumentExportFormat) {
    if (busy) return;
    setBusy(format);
    try {
      saveBlob(await exporting.exportAs(format), `${title}${FORMATS[format].ending}`);
    } catch {
      toast.error(t("file_preview_export_failed"));
    } finally {
      setBusy(null);
    }
  }

  const unavailableReason = (reason: string | null | undefined) => {
    if (reason === "format_unsupported") return t("file_preview_export_format_unsupported");
    if (reason === "document_unsupported") return t("file_preview_export_document_unsupported");
    if (reason === "incompatible_tool") return t("file_preview_export_incompatible");
    return t("file_preview_export_unavailable");
  };

  const formatItem = (format: DocumentExportFormat) => {
    const state = availability.data?.[format];
    const template = availability.data?.template;
    return {
      id: format,
      label: FORMATS[format].name,
      endContent: <span className="text-ax-text-secondary text-xs">{FORMATS[format].ending}</span>,
      description: availability.isPending
        ? t("loading")
        : availability.isError
          ? t("file_preview_export_check_failed")
          : state && !state.available
            ? unavailableReason(state.reason)
            : template
              ? t("file_preview_export_template", {
                  name:
                    template.source === "builtin"
                      ? t("document_template_builtin_name")
                      : template.name
                })
              : undefined,
      isDisabled: !state?.available || busy !== null,
      onClick: () => void exportAs(format)
    };
  };

  return (
    <DropdownMenu
      isMenuOpen={open}
      onOpenChange={setOpen}
      placement="below"
      alignment="end"
      menuWidth={288}
      hasChevron={!compact}
      button={{
        label: busy ? t("file_preview_exporting") : t("file_preview_export"),
        variant: "secondary",
        size: "sm",
        icon: <Download className="size-4" />,
        isIconOnly: compact,
        isDisabled: busy !== null
      }}
      items={[
        {
          id: "md",
          label: FORMATS.md.name,
          endContent: <span className="text-ax-text-secondary text-xs">{FORMATS.md.ending}</span>,
          description: namesImages ? t("file_preview_export_markdown_without_images") : undefined,
          onClick: onSaveOriginal
        },
        formatItem("docx"),
        formatItem("pdf")
      ]}
    />
  );
}
