"use client";

import { Button } from "@astryxdesign/core/Button";
import Link from "@/lib/link";
import { useTranslations } from "use-intl";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";

export function AssistantWidgetSection({ assistantId }: { assistantId: string }) {
  const t = useTranslations();
  const { space, routeId } = useSpace();
  const { can } = useAppContext();
  const href = `/spaces/${routeId}/assistants/${assistantId}/widget`;
  const manages = can("widgets");

  return (
    <SettingsGroup title={t("widget_admin_title")}>
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
