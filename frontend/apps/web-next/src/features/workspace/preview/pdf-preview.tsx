"use client";

import { useTranslations } from "use-intl";
import { useCallback, useEffect } from "react";
import { useHydrated } from "@/lib/hooks/use-hydrated";

/**
 * A PDF in the browser's own viewer, on an object URL of the file's bytes that
 * lives as long as the frame. Browsers without an inline viewer (most phones)
 * would offer the frame's content as a download instead; they get a notice to
 * download the file.
 */
export function PdfPreview({
  blob,
  title,
  onReady,
  onError
}: {
  blob: Blob;
  title: string;
  onReady?: () => void;
  onError?: () => void;
}) {
  const t = useTranslations();
  const hydrated = useHydrated();
  const viewerAvailable = hydrated && navigator.pdfViewerEnabled !== false;

  const attach = useCallback(
    (frame: HTMLIFrameElement | null) => {
      if (!frame) return;
      const url = URL.createObjectURL(blob);
      frame.src = `${url}#navpanes=0&view=FitH`;
      return () => URL.revokeObjectURL(url);
    },
    [blob]
  );

  // The notice is itself the final preview on these devices.
  useEffect(() => {
    if (hydrated && !viewerAvailable) onReady?.();
  }, [hydrated, viewerAvailable, onReady]);

  if (!hydrated) return null;
  if (!viewerAvailable) {
    return (
      <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_unsupported_here")}</p>
    );
  }
  return (
    <iframe
      ref={attach}
      title={title}
      // The frame's first load is its empty document, before the URL is set.
      onLoad={(event) => {
        if (event.currentTarget.getAttribute("src")) onReady?.();
      }}
      onError={onError}
      className="min-h-0 w-full flex-1 border-0"
    />
  );
}
