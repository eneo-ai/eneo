"use client";

import { Spinner } from "@astryxdesign/core/Spinner";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import {
  FieldProblem,
  fieldProblemProps,
  revealProblems
} from "@/components/composites/field-problem";
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
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { matchesSearch } from "@/lib/search";
import { useJobs } from "@/features/jobs/use-jobs";
import { useSpace } from "@/features/spaces/use-space";
import { EmbeddingModelSelect } from "../../embedding-model-select";
import {
  integrationPreviewQueryOptions,
  type IntegrationPreview,
  type UserIntegration
} from "../queries";
import { blockingError, RefreshError } from "@/components/composites/query-state";
import { ImportPreviewError } from "./preview-state";

type ConfluenceImport = { selected: IntegrationPreview; embeddingModelId: string };

/** Confluence import: pick one space, then import it whole with an embedding model. */
export function ConfluenceImportDialog({
  open,
  onOpenChange,
  onBack,
  integration
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onBack: () => void;
  integration: UserIntegration;
}) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const { trackJob } = useJobs();
  const userIntegrationId = integration.id ?? "";

  // Owned here, not by the form: a pending import outlives a close and reopen.
  const importSpace = useMutation({
    mutationFn: ({ selected, embeddingModelId }: ConfluenceImport) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/knowledge/integrations/add/{user_integration_id}/", {
          params: { path: { id: space.id, user_integration_id: userIntegrationId } },
          body: {
            name: selected.name,
            url: selected.url,
            key: selected.key,
            selected_item_type: selected.type,
            resource_type: "site",
            embedding_model: { id: embeddingModelId }
          }
        })
      ),
    onSuccess: (job) => {
      trackJob(job);
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg">
        {/* DialogContent remounts on every opening, so each import starts over. */}
        <ConfluenceImportForm
          pending={importSpace.isPending}
          onImport={(choice) => importSpace.mutate(choice)}
          onBack={onBack}
          integration={integration}
        />
      </DialogContent>
    </Dialog>
  );
}

function ConfluenceImportForm({
  pending,
  onImport,
  onBack,
  integration
}: {
  pending: boolean;
  onImport: (choice: ConfluenceImport) => void;
  onBack: () => void;
  integration: UserIntegration;
}) {
  const t = useTranslations();
  const { space } = useSpace();

  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<IntegrationPreview | null>(null);
  const [embeddingModelId, setEmbeddingModelId] = useState<string | undefined>(
    space.embedding_models[0]?.id
  );
  const [submitted, setSubmitted] = useState(false);

  const userIntegrationId = integration.id ?? "";
  const preview = useQuery({
    ...integrationPreviewQueryOptions(browserApi, userIntegrationId),
    enabled: userIntegrationId.length > 0
  });

  const spaces = useMemo(() => {
    return (preview.data ?? [])
      .filter((entry) => matchesSearch([entry.name], search))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [preview.data, search]);
  const settingsHref = space.personal ? "/account/integrations" : null;

  const noModels = space.embedding_models.length === 0 || !embeddingModelId;
  const spaceProblem = submitted && !selected ? t("form_problem_choose_confluence_space") : null;

  // Import is never disabled: without an embedding model focus moves to the
  // warning; without a chosen space the problem shows at the list, and focus
  // moves to its first space (or the search, when none is listed).
  function submit() {
    if (noModels || !selected || !embeddingModelId) {
      revealProblems(
        () => setSubmitted(true),
        noModels
          ? "confluence-no-models"
          : (document.querySelector<HTMLElement>("#confluence-spaces button") ??
              "confluence-space-search")
      );
      return;
    }
    onImport({ selected, embeddingModelId });
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>{t("import_knowledge_from_confluence")}</DialogTitle>
      </DialogHeader>

      {space.embedding_models.length === 0 && (
        <p
          id="confluence-no-models"
          tabIndex={-1}
          className="border-warning/30 bg-warning/10 text-warning rounded-md border px-3 py-2 text-sm"
        >
          <span className="font-semibold">{t("warning")}:</span> {t("warning_no_embedding_models")}
        </p>
      )}

      <div className="flex flex-col gap-2">
        <Label htmlFor="confluence-space-search">{t("import_knowledge_from")}</Label>
        <div className="relative">
          <Input
            id="confluence-space-search"
            value={search}
            placeholder={t("find_confluence_space")}
            onChange={(event) => setSearch(event.target.value)}
          />
          <Search className="text-muted-foreground absolute top-1/2 right-3 size-4 -translate-y-1/2" />
        </div>
        <RefreshError queries={[preview]} />
        <div
          id="confluence-spaces"
          role="group"
          aria-label={t("confluence_spaces_label")}
          className="max-h-[40vh] overflow-y-auto rounded-md border p-1"
          {...fieldProblemProps("confluence-spaces", spaceProblem)}
        >
          {userIntegrationId.length === 0 ? (
            <ImportPreviewError
              message={t("integration_preview_connection_missing")}
              onBack={onBack}
              settingsHref={settingsHref}
            />
          ) : blockingError(preview) ? (
            <ImportPreviewError
              error={preview.error}
              message={t("integration_preview_failed")}
              onBack={onBack}
              isRetrying={preview.isFetching}
              onRetry={() => void preview.refetch()}
              settingsHref={settingsHref}
            />
          ) : preview.isPending ? (
            <div
              role="status"
              className="text-muted-foreground flex items-center gap-2 px-2 py-3 text-sm"
            >
              <Spinner size="sm" aria-hidden /> {t("loading_available_spaces")}
            </div>
          ) : spaces.length === 0 ? (
            <p className="text-muted-foreground px-2 py-3 text-sm">
              {t("no_matching_spaces_found")}
            </p>
          ) : (
            spaces.map((entry) => (
              <button
                key={entry.key}
                type="button"
                aria-pressed={selected?.key === entry.key}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${
                  selected?.key === entry.key ? "bg-accent" : "hover:bg-muted/50"
                }`}
                onClick={() => setSelected(entry)}
              >
                <FileText className="text-muted-foreground size-4 shrink-0" />
                <span className="truncate text-sm">{entry.name}</span>
              </button>
            ))
          )}
        </div>
        <FieldProblem id="confluence-spaces" problem={spaceProblem} />
      </div>

      <EmbeddingModelSelect
        models={space.embedding_models}
        value={embeddingModelId}
        onChange={setEmbeddingModelId}
      />

      <DialogFooter>
        <Button variant="outline" onClick={onBack}>
          {t("back")}
        </Button>
        {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
        <Button aria-busy={pending || undefined} onClick={submit}>
          {pending ? t("importing") : t("import_space")}
        </Button>
      </DialogFooter>
    </>
  );
}
