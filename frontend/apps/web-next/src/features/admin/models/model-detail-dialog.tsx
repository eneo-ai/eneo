import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { useFormatter, useTranslations } from "use-intl";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { ModelUsageBreakdown } from "./model-usage-breakdown";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Banner } from "@astryxdesign/core/Banner";
import { sanitizeWebHref } from "@/lib/safe-url";
import { modelLifecycle, modelPrice } from "./provider-sections";
import { isEmbeddingFamily } from "./model-metadata-options";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { browserApi } from "@/lib/api/browser";
import { modelDisplayName } from "@/lib/models/model-display-name";
import { useImageOptionLabels } from "./image-model-options";
import {
  type AdminModel,
  type MigratableModelKind,
  type ModelKind,
  modelUsageDetailsQueryOptions,
  modelUsedBy,
  usedByLabel
} from "./models";

/**
 * Model properties and usage, with actions delegated to the dialog owner.
 * Only completion and transcription models have usage endpoints.
 */
export function ModelDetailDialog({
  model,
  kind,
  open,
  onOpenChange,
  onEdit,
  onMigrate
}: {
  model: AdminModel;
  kind: ModelKind;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEdit?: () => void;
  onMigrate?: () => void;
}) {
  const t = useTranslations();
  const lifecycle = modelLifecycle(model);
  const alreadyMigrated = "migrated_to_model_id" in model && Boolean(model.migrated_to_model_id);
  const canMigrate =
    (kind === "completion" || kind === "transcription") && !alreadyMigrated && onMigrate;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{modelDisplayName(model)}</DialogTitle>
        </DialogHeader>
        {lifecycle.kind !== "active" && (
          <Banner
            status="warning"
            collapsible={false}
            title={
              lifecycle.kind === "deprecated"
                ? t("model_label_deprecated")
                : t("model_tooltip_retiring", { date: lifecycle.date })
            }
          >
            {canMigrate && (
              <Button variant="outline" onClick={onMigrate}>
                {t("migrate")}
              </Button>
            )}
          </Banner>
        )}
        {kind !== "completion" && kind !== "transcription" ? (
          <InfoTab model={model} kind={kind} t={t} />
        ) : (
          <Tabs defaultValue="info">
            <TabsList>
              <TabsTrigger value="info">{t("model_detail_tab_info")}</TabsTrigger>
              <TabsTrigger value="usage">{t("model_detail_tab_usage")}</TabsTrigger>
            </TabsList>
            <TabsContent value="info" className="pt-4">
              <InfoTab model={model} kind={kind} t={t} />
            </TabsContent>
            <TabsContent value="usage" className="pt-4">
              <UsageTab modelId={model.id} kind={kind} open={open} />
            </TabsContent>
          </Tabs>
        )}
        {onEdit && (
          <DialogFooter>
            <Button onClick={onEdit}>{t("edit")}</Button>
          </DialogFooter>
        )}
      </DialogContent>
    </Dialog>
  );
}

function InfoTab({
  model,
  kind,
  t
}: {
  model: AdminModel;
  kind: ModelKind;
  t: ReturnType<typeof useTranslations>;
}) {
  const imageLabels = useImageOptionLabels();
  const format = useFormatter();
  const contextWindow =
    "max_input_tokens" in model
      ? model.max_input_tokens
      : "max_input" in model
        ? model.max_input
        : null;
  const outputTokens = "max_output_tokens" in model ? model.max_output_tokens : null;
  const usedBy = modelUsedBy(model);
  const hfLink = sanitizeWebHref("hf_link" in model ? model.hf_link : null);
  // Only the fields a forecast model carries are shown for one.
  const { family, hosting } = model as { family?: string | null; hosting?: string | null };
  const price = modelPrice(model, kind);
  const priceLabel =
    price.kind === "tokens"
      ? t("model_cost_per_million", { input: price.input ?? "—", output: price.output ?? "—" })
      : price.kind === "image"
        ? t("model_cost_chip_per_image", { value: price.value })
        : price.kind === "minute"
          ? t("model_cost_per_minute", { cost: price.value })
          : t("model_cost_unknown");
  const capabilities = [
    "vision" in model && model.vision ? t("capability_vision") : null,
    "reasoning" in model && model.reasoning ? t("capability_reasoning") : null,
    "supports_tool_calling" in model && model.supports_tool_calling
      ? t("model_label_tool_calling")
      : null
  ].filter((value): value is string => value !== null);

  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
      {/* A forecast model's key ("default") is Eneo's own mapping. */}
      {kind !== "forecast" && <Field label={t("model_identifier")} value={model.name} />}
      {family && (
        <Field
          label={t("model_family")}
          value={
            kind === "embedding" && isEmbeddingFamily(family) ? t(`model_family_${family}`) : family
          }
        />
      )}
      {hosting && (
        <Field
          label={t("hosting_region")}
          value={t.has(`hosting_${hosting}`) ? t(`hosting_${hosting}`) : hosting}
        />
      )}
      {typeof contextWindow === "number" && (
        <Field label={t("model_context_label")} value={format.number(contextWindow)} />
      )}
      {typeof outputTokens === "number" && (
        <Field label={t("max_output_tokens")} value={format.number(outputTokens)} />
      )}
      {"dimensions" in model && typeof model.dimensions === "number" && (
        <Field label={t("dimensions")} value={format.number(model.dimensions)} />
      )}
      {kind === "completion" && (
        <Field
          label={t("capabilities")}
          value={
            capabilities.length ? (
              <div className="flex flex-wrap gap-1 pt-0.5">
                {capabilities.map((label) => (
                  <Badge key={label} variant="outline">
                    {label}
                  </Badge>
                ))}
              </div>
            ) : (
              t("none")
            )
          }
        />
      )}
      {kind === "image" && (
        <>
          <Field
            label={t("image_default_size")}
            value={imageLabels.size("default_size" in model ? model.default_size : undefined)}
          />
          <Field
            label={t("image_default_quality")}
            value={imageLabels.quality(
              "default_quality" in model ? model.default_quality : undefined
            )}
          />
        </>
      )}
      {"candidate_factor" in model && (
        <Field label={t("rerank_candidate_factor")} value={String(model.candidate_factor)} />
      )}
      {"max_candidates" in model && (
        <Field label={t("rerank_max_candidates")} value={String(model.max_candidates)} />
      )}
      {price.kind !== "none" && <Field label={t("model_pricing_label")} value={priceLabel} />}
      <Field
        label={t("security_classification")}
        value={model.security_classification?.name ?? t("no_classification")}
      />
      {typeof model.open_source === "boolean" && (
        <Field label={t("open_source")} value={t(model.open_source ? "yes" : "no")} />
      )}
      {model.org && <Field label={t("model_developed_by")} value={model.org} />}
      {model.description && <Field label={t("description")} value={model.description} />}
      {hfLink && (
        <div className="sm:col-span-2">
          <dt className="sr-only">{t("model_huggingface_link")}</dt>
          <dd>
            <a
              href={hfLink}
              target="_blank"
              rel="noopener noreferrer"
              className="text-ax-accent hover:underline"
            >
              {t("model_huggingface_link")}
            </a>
          </dd>
        </div>
      )}
      {usedBy.length > 0 && (
        <div className="sm:col-span-2">
          <dt className="text-muted-foreground text-xs">{usedByLabel(t, usedBy)}</dt>
          {/* A forecast source is named after its Function, which the label has just said. */}
          {kind !== "forecast" && (
            <dd>
              <ul className="flex flex-wrap gap-1 pt-0.5">
                {usedBy.map((source) => (
                  <li key={source.id} className="flex">
                    <Badge variant="outline">{source.name}</Badge>
                  </li>
                ))}
              </ul>
            </dd>
          )}
        </div>
      )}
    </dl>
  );
}

function UsageTab({
  modelId,
  kind,
  open
}: {
  modelId: string;
  kind: MigratableModelKind;
  open: boolean;
}) {
  const details = useQuery({
    ...modelUsageDetailsQueryOptions(browserApi, modelId, kind),
    enabled: open
  });
  return (
    <QueryStateBoundary query={details}>
      {(data) => <ModelUsageBreakdown data={data} />}
    </QueryStateBoundary>
  );
}

function Field({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-muted-foreground text-xs">{label}</dt>
      <dd className="[overflow-wrap:anywhere]">{value}</dd>
    </div>
  );
}
