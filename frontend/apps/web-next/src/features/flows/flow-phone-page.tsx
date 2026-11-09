import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId } from "react";
import { DockedActions } from "@/components/shell/docked-actions";
import { PageBar } from "@/components/shell/page-bar";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { flowQueryOptions } from "./flows-api";
import { SettingsSummary } from "./flow-settings";
import { flowKindLine } from "./flow-labels";
import { FlowRunsList } from "./runs/runs-list";

/**
 * A flow on a phone (version 1: run it and read its runs; building one is for
 * a computer): its name, what it takes and gives, how it is set up (what it
 * is for among that, so the header does not say it too), its runs and "Kör
 * flödet" docked under the thumb (the form it opens is the flow page's). The
 * steps and the flow's chat are not here: nothing offers to edit. FlowPage
 * shows it only on a phone held either way (HANDHELD_QUERY), a phone's layout,
 * so its chrome is the phone's: the page bar and the dock.
 */
export function FlowPhonePage({ flowId, onStart }: { flowId: string; onStart: () => void }) {
  const t = useTranslations();
  const { routeId, space } = useSpace();
  const settingsHeadingId = useId();
  const { data: flow } = useSuspenseQuery(flowQueryOptions(browserApi, flowId));
  const isPublished = flow.published_version != null;
  const canRun = isPublished && flow.permissions.can_run;
  const kind = flowKindLine(flow, t);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageBar until="phone" parent={{ label: t("flows"), href: `/spaces/${routeId}/flows` }} />
      <div className="flex flex-col gap-6 p-4">
        <header className="flex flex-col gap-2">
          <h1 className="text-ax-text text-2xl leading-tight font-semibold break-words">
            {flow.name}
          </h1>
          {kind ? <p className="text-ax-text-secondary m-0 text-sm">{kind}</p> : null}
        </header>
        {!isPublished ? (
          <Banner status="info" title={t("flow_phone_not_published")} collapsible={false} />
        ) : null}
        <section aria-labelledby={settingsHeadingId} className="flex flex-col gap-3">
          <h2 id={settingsHeadingId} className="text-ax-text text-lg font-semibold">
            {t("flows_settings_heading")}
          </h2>
          <SettingsSummary
            flow={flow}
            transcription={{
              models: space.transcription_models,
              services: space.transcription_services ?? []
            }}
            classification={space.security_classification}
          />
        </section>
        {flow.permissions.can_view_runs ? (
          <FlowRunsList
            flowId={flow.id}
            spaceRouteId={routeId}
            publishedVersion={flow.published_version ?? null}
          />
        ) : null}
        {flow.permissions.can_edit ? (
          <p className="text-ax-text-secondary m-0 text-sm">{t("flow_edit_on_desktop")}</p>
        ) : null}
      </div>
      {canRun ? (
        <DockedActions label={t("flow_phone_actions")}>
          <Button
            label={t("flow_runs_start")}
            variant="primary"
            icon={<Play aria-hidden="true" />}
            onClick={onStart}
          />
        </DockedActions>
      ) : null}
    </div>
  );
}
