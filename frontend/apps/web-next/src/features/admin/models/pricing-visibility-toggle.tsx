"use client";

import { Heading } from "@astryxdesign/core/Heading";
import { Switch } from "@/components/astryx/switch";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useSettingSwitch } from "@/features/admin/use-setting-switch";

/**
 * Org-wide toggle controlling whether model input/output prices are shown to
 * regular users (in the chat/assistant model pickers). Off by admin choice hides
 * prices both in the UI and in the API responses served to members. Saves as
 * described in `useSettingSwitch`.
 */
export function PricingVisibilityToggle() {
  const t = useTranslations();
  const { tenant } = useAppContext();
  const headingId = useId();

  const [enabled, setEnabled] = useSettingSwitch(
    "model-pricing-visibility",
    tenant.show_model_pricing ?? true,
    (show) =>
      unwrap(
        browserApi.PUT("/api/v1/admin/settings/model-pricing-visibility", {
          body: { show_model_pricing: show }
        })
      )
  );

  return (
    <section
      aria-labelledby={headingId}
      className="bg-ax-card border-ax-border rounded-ax-container border"
    >
      <div className="border-ax-border border-b px-5 py-4">
        <Heading level={2} id={headingId} className="text-base">
          {t("model_pricing")}
        </Heading>
      </div>
      <div className="px-5 py-4">
        <Switch
          label={t("show_model_pricing")}
          description={t("show_model_pricing_description")}
          labelPosition="start"
          labelSpacing="spread"
          value={enabled}
          onChange={setEnabled}
        />
      </div>
    </section>
  );
}
