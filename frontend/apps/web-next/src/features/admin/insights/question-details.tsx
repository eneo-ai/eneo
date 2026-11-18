import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "use-intl";
import type { RefObject } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { useReturnFocus } from "@/components/ui/dialog-focus";
import { browserApi } from "@/lib/api/browser";
import { useCopy } from "@/lib/hooks/use-copy";
import { questionLogQueryOptions, type AssistantInsightQuestion } from "./insights";

export function QuestionDetails({
  question,
  triggerRef,
  onClose
}: {
  question: AssistantInsightQuestion;
  triggerRef: RefObject<HTMLElement | null>;
  onClose: () => void;
}) {
  const t = useTranslations();
  const query = useQuery(questionLogQueryOptions(browserApi, question.id));
  const { copy, isCopied } = useCopy();
  useReturnFocus(true, triggerRef);
  return (
    <Dialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      width="48rem"
    >
      <DialogHeader
        title={t("insights_question_details")}
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
      />
      <div className="flex min-w-0 flex-col gap-4 p-4">
        <dl className="flex flex-col gap-3 text-sm">
          <div>
            <dt className="text-ax-text-secondary">{t("question")}</dt>
            <dd className="wrap-anywhere whitespace-pre-wrap">
              {question.question || t("untitled")}
            </dd>
          </div>
          <div>
            <dt className="text-ax-text-secondary">{t("created")}</dt>
            <dd>
              <ClientTime value={question.created_at} format="date_time" />
            </dd>
          </div>
          <div>
            <dt className="text-ax-text-secondary">{t("insights_session_id")}</dt>
            <dd className="wrap-anywhere">{question.session_id}</dd>
          </div>
        </dl>
        <QueryStateBoundary query={query} rows={3}>
          {(record) => {
            if (record === null) {
              return (
                <p className="text-ax-text-secondary text-sm">{t("insights_question_no_log")}</p>
              );
            }
            const json = JSON.stringify(record, null, 2);
            return (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  className="self-end"
                  label={isCopied ? t("copied") : t("copy")}
                  onClick={() => void copy(json)}
                />
                <pre
                  role="region"
                  aria-label={t("insights_logged_json")}
                  tabIndex={0}
                  className="bg-ax-sunken border-ax-border rounded-ax-container focus-visible:outline-ring max-h-96 overflow-auto border p-3 text-xs focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  {json}
                </pre>
              </>
            );
          }}
        </QueryStateBoundary>
        <Button className="self-end" label={t("done")} onClick={onClose} />
      </div>
    </Dialog>
  );
}
