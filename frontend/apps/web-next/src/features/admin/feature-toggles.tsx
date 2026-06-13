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

type ToggleKey = "templates" | "audit-logging" | "provisioning";

/** openapi-fetch needs literal paths, so dispatch per toggle (same body/response shape). */
function patchSetting(key: ToggleKey, enabled: boolean) {
  const body = { enabled };
  if (key === "templates") return browserApi.PATCH("/api/v1/settings/templates", { body });
  if (key === "audit-logging") return browserApi.PATCH("/api/v1/settings/audit-logging", { body });
  return browserApi.PATCH("/api/v1/settings/provisioning", { body });
}

/**
 * Tenant feature toggles. Optimistic update with revert-on-error; a successful
 * write refreshes the server layout so the new settings propagate app-wide
 * (e.g. the templates toggle changes the space creation flows).
 */
export function FeatureToggles() {
  const t = useTranslations();
  const router = useRouter();
  const { settings } = useAppContext();

  const [templates, setTemplates] = useState(settings.using_templates ?? false);
  const [auditLogging, setAuditLogging] = useState(settings.audit_logging_enabled ?? false);
  const [provisioning, setProvisioning] = useState(settings.provisioning ?? false);
  const [pending, setPending] = useState(false);

  async function toggle(
    key: ToggleKey,
    next: boolean,
    apply: (value: boolean) => void,
    previous: boolean
  ) {
    apply(next); // optimistic
    setPending(true);
    try {
      await unwrap(patchSetting(key, next));
      router.refresh();
    } catch (error) {
      apply(previous); // revert
      toastApiError(error, t);
    } finally {
      setPending(false);
    }
  }

  return (
    <SettingsGroup title={t("features")}>
      <SettingsRow title={t("enable_templates")} description={t("enable_templates_description")}>
        <Switch
          checked={templates}
          disabled={pending}
          onCheckedChange={(next) => toggle("templates", next, setTemplates, templates)}
        />
      </SettingsRow>
      <SettingsRow
        title={t("enable_audit_logging")}
        description={t("enable_audit_logging_description")}
      >
        <Switch
          checked={auditLogging}
          disabled={pending}
          onCheckedChange={(next) => toggle("audit-logging", next, setAuditLogging, auditLogging)}
        />
      </SettingsRow>
      <SettingsRow
        title={t("enable_provisioning")}
        description={t("enable_provisioning_description")}
      >
        <Switch
          checked={provisioning}
          disabled={pending}
          onCheckedChange={(next) => toggle("provisioning", next, setProvisioning, provisioning)}
        />
      </SettingsRow>
    </SettingsGroup>
  );
}
