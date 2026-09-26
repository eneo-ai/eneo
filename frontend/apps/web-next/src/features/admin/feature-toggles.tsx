"use client";

import { Heading } from "@astryxdesign/core/Heading";
import { Switch } from "@astryxdesign/core/Switch";
import { useTranslations } from "next-intl";
import { useId } from "react";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { useSettingSwitch } from "./use-setting-switch";

type ToggleKey = "templates" | "audit-logging" | "provisioning" | "whats-new";

/** openapi-fetch needs literal paths, so dispatch per toggle (same body/response shape). */
function patchSetting(key: ToggleKey, enabled: boolean) {
  const body = { enabled };
  if (key === "templates") return browserApi.PATCH("/api/v1/settings/templates", { body });
  if (key === "audit-logging") return browserApi.PATCH("/api/v1/settings/audit-logging", { body });
  if (key === "whats-new") return browserApi.PATCH("/api/v1/settings/whats-new", { body });
  return browserApi.PATCH("/api/v1/settings/provisioning", { body });
}

function SettingRow({
  setting,
  initial,
  label,
  description
}: {
  setting: ToggleKey;
  initial: boolean;
  label: string;
  description: string;
}) {
  const [value, setValue] = useSettingSwitch(setting, initial, (enabled) =>
    unwrap(patchSetting(setting, enabled))
  );
  return (
    <Switch
      label={label}
      description={description}
      labelPosition="start"
      labelSpacing="spread"
      value={value}
      onChange={setValue}
    />
  );
}

/**
 * Tenant feature toggles as settings rows: label and description on the left,
 * the switch on the right. Each saves as described in `useSettingSwitch`
 * (e.g. the templates toggle changes the space creation flows app-wide).
 */
export function FeatureToggles() {
  const t = useTranslations();
  const { settings } = useAppContext();
  const headingId = useId();

  const rows: { key: ToggleKey; initial: boolean; label: string; description: string }[] = [
    {
      key: "templates",
      initial: settings.using_templates ?? false,
      label: t("enable_templates"),
      description: t("enable_templates_description")
    },
    {
      key: "audit-logging",
      initial: settings.audit_logging_enabled ?? false,
      label: t("enable_audit_logging"),
      description: t("enable_audit_logging_description")
    },
    {
      key: "provisioning",
      initial: settings.provisioning ?? false,
      label: t("enable_provisioning"),
      description: t("enable_provisioning_description")
    },
    {
      key: "whats-new",
      initial: settings.whats_new_enabled !== false,
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
            <SettingRow
              setting={row.key}
              initial={row.initial}
              label={row.label}
              description={row.description}
            />
          </li>
        ))}
      </ul>
    </section>
  );
}
