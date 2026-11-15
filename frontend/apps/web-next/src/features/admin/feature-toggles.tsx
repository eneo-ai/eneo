import { Badge } from "@astryxdesign/core/Badge";
import { Heading } from "@astryxdesign/core/Heading";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { Link } from "@astryxdesign/core/Link";
import { Text } from "@astryxdesign/core/Text";
import { useQueryClient } from "@tanstack/react-query";
import { Switch } from "@astryxdesign/core/Switch";
import {
  LayoutTemplate,
  PartyPopper,
  ScrollText,
  UserRoundPlus,
  Workflow,
  type LucideIcon
} from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useState, type ReactNode } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { useAppContext } from "@/components/providers/app-context";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { sessionKeys } from "@/lib/api/session";
import { TaskWorkersStatus, taskWorkersQuery, workersAnnouncement } from "./task-workers-status";
import { useSettingSwitch } from "./use-setting-switch";

type ToggleKey = "templates" | "audit-logging" | "provisioning" | "whats-new" | "flows";

/** What a confirmation before switching a setting off says. */
type ConfirmOff = { title: string; description: string; confirmLabel: string };

/** openapi-fetch needs literal paths, so dispatch per toggle (same body/response shape). */
function patchSetting(key: ToggleKey, enabled: boolean) {
  const body = { enabled };
  if (key === "templates") return browserApi.PATCH("/api/v1/settings/templates", { body });
  if (key === "audit-logging") return browserApi.PATCH("/api/v1/settings/audit-logging", { body });
  if (key === "whats-new") return browserApi.PATCH("/api/v1/settings/whats-new", { body });
  if (key === "flows") return browserApi.PATCH("/api/v1/settings/flows", { body });
  return browserApi.PATCH("/api/v1/settings/provisioning", { body });
}

function SettingRow({
  setting,
  initial,
  label,
  description,
  icon: Icon,
  tone,
  badge,
  confirmOff,
  children
}: {
  setting: ToggleKey;
  initial: boolean;
  label: string;
  description: string;
  icon: LucideIcon;
  tone: string;
  badge?: string;
  /** Asked before the setting is switched off; Cancel saves nothing. */
  confirmOff?: ConfirmOff;
  /** Shown under the switch. */
  children?: ReactNode;
}) {
  const queryClient = useQueryClient();
  const t = useTranslations();
  const announce = useAnnounce();
  const [confirming, setConfirming] = useState(false);
  const [value, setValue] = useSettingSwitch(
    setting,
    initial,
    (enabled) => unwrap(patchSetting(setting, enabled)),
    setting === "provisioning"
      ? {
          onSaved: async () => {
            await Promise.all([
              queryClient.invalidateQueries({ queryKey: sessionKeys.settings }),
              queryClient.invalidateQueries({ queryKey: sessionKeys.tenant })
            ]);
          }
        }
      : setting === "flows"
        ? {
            // Switched on, the admin sees and hears at once whether the workers run.
            onSaved: async (enabled) => {
              await Promise.all([
                queryClient.invalidateQueries({ queryKey: sessionKeys.settings }),
                enabled && queryClient.invalidateQueries({ queryKey: taskWorkersQuery.queryKey })
              ]);
              const workers = enabled && queryClient.getQueryState(taskWorkersQuery.queryKey);
              if (workers) announce(workersAnnouncement(workers, t));
            }
          }
        : undefined
  );
  return (
    <div className="flex min-w-0 items-start gap-3">
      {/* Decorative. On a phone its 52 px go to the label and description, which beside the
          switch otherwise wrap to four lines at 320 px. */}
      <span
        className={`rounded-ax-element flex size-10 shrink-0 items-center justify-center max-md:hidden ${tone}`}
        aria-hidden="true"
      >
        <Icon className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        {badge ? <Badge variant="warning" label={badge} className="mb-1" /> : null}
        <Switch
          label={label}
          description={description}
          labelPosition="start"
          labelSpacing="spread"
          value={value}
          onChange={(next) => (confirmOff && !next ? setConfirming(true) : setValue(next))}
        />
        {children}
      </div>
      {confirmOff ? (
        <ConfirmDialogControlled
          open={confirming}
          onOpenChange={setConfirming}
          title={confirmOff.title}
          description={confirmOff.description}
          confirmLabel={confirmOff.confirmLabel}
          onConfirm={() => {
            setConfirming(false);
            setValue(false);
          }}
        />
      ) : null}
    </div>
  );
}

/** Beside the Flows switch: the workers Flows need, and how roles get access. */
function FlowsDetails() {
  const t = useTranslations();
  return (
    <>
      <TaskWorkersStatus />
      <Text type="supporting" className="mt-2 block">
        {t.rich("flows_switch_roles", {
          link: (chunks) => (
            <Link href="/admin/roles" hasUnderline className="pointer-coarse:min-h-11">
              {chunks}
            </Link>
          )
        })}
      </Text>
    </>
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

  const rows: {
    key: ToggleKey;
    initial: boolean;
    label: string;
    description: string;
    icon: LucideIcon;
    tone: string;
    badge?: string;
    confirmOff?: ConfirmOff;
    details?: ReactNode;
  }[] = [
    {
      key: "templates",
      initial: settings.using_templates ?? false,
      label: t("enable_templates"),
      description: t("enable_templates_description"),
      icon: LayoutTemplate,
      tone: "bg-ax-purple-muted text-ax-purple"
    },
    {
      key: "audit-logging",
      initial: settings.audit_logging_enabled ?? false,
      label: t("enable_audit_logging"),
      description: t("enable_audit_logging_description"),
      icon: ScrollText,
      tone: "bg-ax-blue-muted text-ax-blue"
    },
    {
      key: "provisioning",
      initial: settings.provisioning ?? false,
      label: t("enable_provisioning"),
      description: t("enable_provisioning_description"),
      icon: UserRoundPlus,
      tone: "bg-ax-teal-muted text-ax-teal"
    },
    {
      key: "whats-new",
      initial: settings.whats_new_enabled !== false,
      label: t("enable_whats_new"),
      description: t("enable_whats_new_description"),
      icon: PartyPopper,
      tone: "bg-ax-orange-muted text-ax-orange"
    },
    {
      key: "flows",
      initial: settings.flows_enabled === true,
      label: t("flows_switch_label"),
      description: t("flows_switch_description"),
      icon: Workflow,
      tone: "bg-ax-green-muted text-ax-green",
      badge: t("flows_switch_alpha"),
      confirmOff: {
        title: t("flows_switch_off_title"),
        description: t("flows_switch_off_description"),
        confirmLabel: t("flows_switch_off_confirm")
      },
      details: <FlowsDetails />
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
              icon={row.icon}
              tone={row.tone}
              badge={row.badge}
              confirmOff={row.confirmOff}
            >
              {row.details}
            </SettingRow>
          </li>
        ))}
      </ul>
    </section>
  );
}
