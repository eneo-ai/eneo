"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { useSuspenseQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useTranslations } from "use-intl";
import { DockedActions } from "@/components/shell/docked-actions";
import { PageBar } from "@/components/shell/page-bar";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { flowQueryOptions } from "./flows-api";
import { flowKindLine } from "./flows-rows";
import { FlowRunsList } from "./runs/runs-list";

/**
 * A flow on a phone (version 1: run it and read its runs; building one is for
 * a computer): its name, what it is for, what it takes and gives, its runs
 * and "Kör flödet" docked under the thumb (the form it opens is the flow
 * page's). The definition and the flow's chat are not here: nothing offers to
 * edit.
 */
export function FlowPhonePage({ flowId, onStart }: { flowId: string; onStart: () => void }) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const { data: flow } = useSuspenseQuery(flowQueryOptions(browserApi, flowId));
  const isPublished = flow.published_version != null;
  const canRun = isPublished && flow.permissions.can_run;
  const kind = flowKindLine(flow, t);

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <PageBar until="md" parent={{ label: t("flows"), href: `/spaces/${routeId}/flows` }} />
      <div className="flex flex-col gap-6 px-4 py-4">
        <header className="flex flex-col gap-2">
          <h1 className="text-ax-text text-2xl leading-tight font-semibold break-words">
            {flow.name}
          </h1>
          {flow.description ? (
            <p className="text-ax-text-secondary m-0 text-base break-words">{flow.description}</p>
          ) : null}
          {kind ? <p className="text-ax-text-secondary m-0 text-sm">{kind}</p> : null}
        </header>
        {!isPublished ? (
          <Banner status="info" title={t("flow_phone_not_published")} collapsible={false} />
        ) : null}
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
