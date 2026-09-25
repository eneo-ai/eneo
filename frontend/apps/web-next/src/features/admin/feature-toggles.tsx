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

type ToggleKey = "templates" | "audit-logging" | "provisioning" | "whats-new";

/** openapi-fetch needs literal paths, so dispatch per toggle (same body/response shape). */
function patchSetting(key: ToggleKey, enabled: boolean) {
  const body = { enabled };
  if (key === "templates") return browserApi.PATCH("/api/v1/settings/templates", { body });
  if (key === "audit-logging") return browserApi.PATCH("/api/v1/settings/audit-logging", { body });
  if (key === "whats-new") return browserApi.PATCH("/api/v1/settings/whats-new", { body });
  return browserApi.PATCH("/api/v1/settings/provisioning", { body });
}

/**
 * Tenant feature toggles as settings rows: label and description on the left,
 * the switch on the right. Optimistic update with revert-on-error; a successful
 * write refreshes the server layout so the new settings propagate app-wide
 * (e.g. the templates toggle changes the space creation flows). A switch stays
 * enabled (and focused) while its write is in flight; toggling it again waits
 * for that write.
 */
export function FeatureToggles() {
  const t = useTranslations();
  const router = useRouter();
  const { settings } = useAppContext();
  const headingId = useId();

  const [values, setValues] = useState<Record<ToggleKey, boolean>>({
    templates: settings.using_templates ?? false,
    "audit-logging": settings.audit_logging_enabled ?? false,
    provisioning: settings.provisioning ?? false,
    "whats-new": settings.whats_new_enabled !== false
  });
  const inFlight = useRef(new Set<ToggleKey>());

  async function toggle(key: ToggleKey, next: boolean) {
    if (inFlight.current.has(key)) return;
    inFlight.current.add(key);
    const previous = values[key];
    setValues((current) => ({ ...current, [key]: next })); // optimistic
    try {
      await unwrap(patchSetting(key, next));
      router.refresh();
    } catch (error) {
      setValues((current) => ({ ...current, [key]: previous })); // revert
      toastApiError(error, t);
    } finally {
      inFlight.current.delete(key);
    }
  }

  const rows: { key: ToggleKey; label: string; description: string }[] = [
    {
      key: "templates",
      label: t("enable_templates"),
      description: t("enable_templates_description")
    },
    {
      key: "audit-logging",
      label: t("enable_audit_logging"),
      description: t("enable_audit_logging_description")
    },
    {
      key: "provisioning",
      label: t("enable_provisioning"),
      description: t("enable_provisioning_description")
    },
    {
      key: "whats-new",
      label: t("enable_whats_new"),
      description: t("enable_whats_new_description")
    }
  ];

  return (
    <section
      aria-labelledby={headingId}
      className="bg-ax-card border-ax-border rounded-ax-container border"
    >
      <div className="border-ax-border border-b px-5 py-4">
        <Heading level={2} id={headingId} className="text-base">
          {t("features")}
        </Heading>
      </div>
      <ul className="divide-ax-border divide-y">
        {rows.map((row) => (
          <li key={row.key} className="px-5 py-4">
            <Switch
              label={row.label}
              description={row.description}
              labelPosition="start"
              labelSpacing="spread"
              value={values[row.key]}
              onChange={(next) => void toggle(row.key, next)}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
