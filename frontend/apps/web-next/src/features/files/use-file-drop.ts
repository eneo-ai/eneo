"use client";

import { useTranslations } from "next-intl";
import { useRef, useState, type DragEvent } from "react";
import { toast } from "@/lib/toast";
import { collectDroppedFiles } from "./collect-dropped-files";

/** Only file drags concern a drop zone; dragged text or links pass through. */
const hasFiles = (event: DragEvent) => event.dataTransfer?.types?.includes("Files") ?? false;

/**
 * The one drag-and-drop behaviour for a file drop zone: spread `handlers` on
 * the zone and highlight it while `dragging`. Dropped folders are expanded,
 * and a drop without files does nothing. A disabled zone still claims a file
 * drag, so the browser does not open the file in place of the app.
 * `onError` reports a drop that could not be read (default: an upload error toast).
 */
export function useFileDrop(
  onFiles: (files: File[]) => void,
  { enabled = true, onError }: { enabled?: boolean; onError?: (error: unknown) => void } = {}
) {
  const t = useTranslations();
  const [dragging, setDragging] = useState(false);
  // dragenter/dragleave fire for every child element crossed, so count the
  // nesting depth instead of trusting a single leave event.
  const depth = useRef(0);

  return {
    dragging: enabled && dragging,
    handlers: {
      onDragEnter: (event: DragEvent) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        depth.current += 1;
        setDragging(true);
      },
      onDragOver: (event: DragEvent) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = enabled ? "copy" : "none";
      },
      onDragLeave: (event: DragEvent) => {
        if (!hasFiles(event)) return;
        depth.current = Math.max(0, depth.current - 1);
        if (depth.current === 0) setDragging(false);
      },
      onDrop: (event: DragEvent) => {
        if (!hasFiles(event)) return;
        event.preventDefault();
        depth.current = 0;
        setDragging(false);
        if (!enabled) return;
        void collectDroppedFiles(event.dataTransfer)
          .then((files) => {
            if (files.length > 0) onFiles(files);
          })
          .catch(onError ?? (() => toast.error(t("file_upload_error"))));
      }
    }
  };
}
