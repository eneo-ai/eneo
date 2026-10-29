"use client";

import { Button } from "@astryxdesign/core/Button";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { QuietBanner } from "@/components/astryx/banner";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "@/features/spaces/use-space";
import { assistantWidgetStatusQueryOptions } from "./queries";

/**
 * The assistant editor's way to its web widget, and the notice that an
 * active widget publishes the assistant to anonymous visitors: whatever is
 * changed in the editor reaches them at once.
 */
export function AssistantWidgetSection({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { can } = useAppContext();
  const status = useQuery(assistantWidgetStatusQueryOptions(browserApi, assistantId));
  const href = `/spaces/${routeId}/assistants/${assistantId}/widget`;
  const manages = can("widgets");

  return (
    <SettingsGroup title={t("widget_admin_title")}>
      {status.data?.serves_active_widget && (
        <QuietBanner
          status="warning"
          title={t("widget_admin_assistant_notice_title")}
          description={t("widget_admin_assistant_notice_body")}
        />
      )}
      <SettingsRow
        title={t("widget_admin_title")}
        description={
          space.organization
            ? t("widget_admin_blocker_organization_space_unsupported")
            : space.personal
              ? t("widget_admin_blocker_personal_space_unsupported")
              : manages
                ? t("widget_admin_link_description")
                : t("widget_admin_activate_admin_only")
        }
      >
        {manages && (
          <div>
            <Button label={t("widget_admin_open")} href={href} as={Link} />
          </div>
        )}
      </SettingsRow>
    </SettingsGroup>
  );
}
