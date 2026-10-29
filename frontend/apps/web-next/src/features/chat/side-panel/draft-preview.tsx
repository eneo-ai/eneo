"use client";

import { useTranslations } from "use-intl";
import { useEffect, useRef } from "react";
import { DocumentEditor } from "@/features/workspace/preview/document-editor";
import type { DocumentDraft } from "./document-draft";

/** The document so far; it grows while the assistant writes. */
export function DraftPreview({ draft }: { draft: DocumentDraft }) {
  const t = useTranslations();
  const scroller = useRef<HTMLDivElement>(null);
  // The view keeps to the newest text until the reader scrolls up to read.
  const following = useRef(true);

  function follow() {
    const element = scroller.current;
    if (following.current && element) element.scrollTop = element.scrollHeight;
  }

  // Sheets are laid out with the draft; the editor says when its text is.
  useEffect(follow, [draft]);

  return (
    <div
      ref={scroller}
      onScroll={(event) => {
        const element = event.currentTarget;
        following.current = element.scrollHeight - element.clientHeight - element.scrollTop < 80;
      }}
      className="min-h-0 flex-1 overflow-auto"
    >
      <p className="text-ax-text-secondary px-6 pt-4 text-sm">
        {draft.showingPreviousDraft
          ? t("file_preview_previous_draft")
          : t("file_preview_draft_notice")}
      </p>
      {draft.sheets?.length ? (
        <div className="flex flex-col gap-6 p-6">
          {draft.sheets.map((sheet, index) => (
            <section key={index}>
              <h3 className="mb-2 font-semibold">{sheet.name || t("file_preview_preparing")}</h3>
              {sheet.fromSource ? (
                <p className="text-ax-text-secondary text-sm">{t("file_preview_draft_source")}</p>
              ) : sheet.columns.length ? (
                <>
                  <div className="overflow-x-auto">
                    <table className="w-full border-collapse text-start text-sm">
                      <thead>
                        <tr>
                          {sheet.columns.map((column, i) => (
                            <th
                              key={i}
                              scope="col"
                              className="border-ax-border border p-2 text-start font-semibold"
                            >
                              {column}
                            </th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {sheet.rows.map((row, i) => (
                          <tr key={i}>
                            {row.map((cell, j) => (
                              <td key={j} className="border-ax-border border p-2">
                                {cell}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {sheet.truncated && (
                    <p className="text-ax-text-secondary mt-2 text-sm">
                      {t("file_preview_draft_rows_limited")}
                    </p>
                  )}
                </>
              ) : (
                <p className="text-ax-text-secondary text-sm">{t("file_preview_preparing")}</p>
              )}
            </section>
          ))}
        </div>
      ) : draft.text ? (
        <DocumentEditor markdown={draft.text} onRender={follow} />
      ) : (
        <p className="text-ax-text-secondary p-6 text-sm">{t("file_preview_preparing")}</p>
      )}
    </div>
  );
}
