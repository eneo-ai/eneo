"use client";

import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/**
 * Org-wide toggle controlling whether model input/output prices are shown to
 * regular users (in the chat/assistant model pickers). Off by admin choice hides
 * prices both in the UI and in the API responses served to members. Optimistic
 * update with revert-on-error; a successful write refreshes the server layout so
 * the new tenant flag propagates app-wide.
 */
export function PricingVisibilityToggle() {
  const t = useTranslations();
  const router = useRouter();
  const { tenant } = useAppContext();

  const [enabled, setEnabled] = useState(tenant.show_model_pricing ?? true);
  const [pending, setPending] = useState(false);

  async function toggle(next: boolean) {
    const previous = enabled;
    setEnabled(next); // optimistic
    setPending(true);
    try {
      await unwrap(
        browserApi.PUT("/api/v1/admin/settings/model-pricing-visibility", {
          body: { show_model_pricing: next }
        })
      );
      router.refresh();
    } catch (error) {
      setEnabled(previous); // revert
      toastApiError(error, t);
    } finally {
      setPending(false);
    }
  }

  return (
    <SettingsGroup title={t("model_pricing")}>
      <SettingsRow
        title={t("show_model_pricing")}
        description={t("show_model_pricing_description")}
      >
        <Switch
          checked={enabled}
          disabled={pending}
          onCheckedChange={toggle}
          aria-label={t("show_model_pricing")}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
