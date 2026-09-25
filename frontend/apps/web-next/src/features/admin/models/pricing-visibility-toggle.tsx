"use client";

import { Heading } from "@astryxdesign/core/Heading";
import { Switch } from "@astryxdesign/core/Switch";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

/**
 * Org-wide toggle controlling whether model input/output prices are shown to
 * regular users (in the chat/assistant model pickers). Off by admin choice hides
 * prices both in the UI and in the API responses served to members. Optimistic
 * update with revert-on-error; a successful write refreshes the server layout so
 * the new tenant flag propagates app-wide. The switch stays enabled (and
 * focused) while saving; a second toggle waits for the first write.
 */
export function PricingVisibilityToggle() {
  const t = useTranslations();
  const router = useRouter();
  const { tenant } = useAppContext();
  const headingId = useId();

  const [enabled, setEnabled] = useState(tenant.show_model_pricing ?? true);
  const saving = useRef(false);

  async function toggle(next: boolean) {
    if (saving.current) return;
    saving.current = true;
    const previous = enabled;
    setEnabled(next); // optimistic
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
      saving.current = false;
    }
  }

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
          onChange={(next) => void toggle(next)}
        />
      </div>
    </section>
  );
}
