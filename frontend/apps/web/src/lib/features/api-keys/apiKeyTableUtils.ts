import type { ApiKeyState, ApiKeyV2 } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import {
  Building2,
  MessageSquare,
  AppWindow,
  Eye,
  Pencil,
  Globe,
  Lock,
  ShieldCheck
} from "lucide-svelte";

type LucideIcon = typeof Building2;

// ---------------------------------------------------------------------------
// Types — shared between user and admin API key tables
// ---------------------------------------------------------------------------

export type AdminApiKey = ApiKeyV2 & {
  owner_user?: { id: string; email?: string | null; username?: string | null } | null;
  created_by_user?: { id: string; email?: string | null; username?: string | null } | null;
  search_match_reasons?: string[] | null;
};

export type ApiKeyUsageEvent = {
  id: string;
  timestamp: string;
  action: string;
  outcome: string;
  ip_address?: string | null;
  user_agent?: string | null;
  request_id?: string | null;
  request_path?: string | null;
  method?: string | null;
  origin?: string | null;
  error_message?: string | null;
};

export type ApiKeyUsageResponse = {
  summary?: {
    total_events: number;
    used_events: number;
    auth_failed_events: number;
    last_seen_at?: string | null;
    last_success_at?: string | null;
    last_failure_at?: string | null;
    sampled_used_events?: boolean;
  };
  items?: ApiKeyUsageEvent[];
  limit?: number;
  next_cursor?: string | null;
};

// "" represents "All states" in filter UIs
export type ApiKeyStateFilterValue = ApiKeyState | "";

// ---------------------------------------------------------------------------
// Status / state helpers
// ---------------------------------------------------------------------------

export function getStatusTooltip(state: string): string {
  switch (state) {
    case "active":
      return m.api_keys_status_active_tooltip();
    case "suspended":
      return m.api_keys_status_suspended_tooltip();
    case "revoked":
      return m.api_keys_status_revoked_tooltip();
    case "expired":
      return m.api_keys_status_expired_tooltip();
    default:
      return m.api_keys_unknown_status();
  }
}

export function getStateStyle(state: string): { label: string; dotClasses: string } {
  switch (state) {
    case "active":
      return { label: m.api_keys_status_active(), dotClasses: "bg-positive-default" };
    case "suspended":
      return { label: m.api_keys_status_suspended(), dotClasses: "bg-warning-default" };
    case "revoked":
      return { label: m.api_keys_status_revoked(), dotClasses: "bg-negative-default" };
    case "expired":
      return { label: m.api_keys_status_expired(), dotClasses: "bg-tertiary" };
    default:
      return { label: m.api_keys_unknown(), dotClasses: "bg-tertiary" };
  }
}

// ---------------------------------------------------------------------------
// Scope helpers
// ---------------------------------------------------------------------------

export function getScopeStyle(scopeType: string): { label: string } {
  switch (scopeType) {
    case "tenant":
      return { label: m.api_keys_scope_tenant() };
    case "space":
      return { label: m.api_keys_scope_space() };
    case "assistant":
      return { label: m.api_keys_scope_assistant() };
    case "app":
      return { label: m.api_keys_scope_app() };
    default:
      return { label: m.api_keys_unknown() };
  }
}

export function getScopeIcon(scopeType: string): LucideIcon {
  switch (scopeType) {
    case "tenant":
    case "space":
      return Building2;
    case "assistant":
      return MessageSquare;
    case "app":
      return AppWindow;
    default:
      return Building2;
  }
}

/**
 * Scope config used by the admin table — includes icon + neutral outline color.
 */
export function getScopeConfig(scopeType: string): {
  label: string;
  icon: LucideIcon;
  color: string;
} {
  const icon = getScopeIcon(scopeType);
  const style = getScopeStyle(scopeType);
  return { label: style.label, icon, color: "border border-default text-muted" };
}

// ---------------------------------------------------------------------------
// Permission helpers
// ---------------------------------------------------------------------------

export type PermissionStyle = {
  label: string;
  icon: LucideIcon;
  badgeClass: string;
};

export function getPermissionStyle(permission: string): PermissionStyle {
  switch (permission) {
    case "read":
      return {
        label: m.api_keys_permission_read(),
        icon: Eye,
        badgeClass: "border-border text-muted bg-secondary/60"
      };
    case "write":
      return {
        label: m.api_keys_permission_write(),
        icon: Pencil,
        badgeClass:
          "text-warning-stronger border-warning-default/40 bg-warning-dimmer/40 dark:bg-warning-dimmer/20"
      };
    case "admin":
      return {
        label: m.api_keys_permission_admin(),
        icon: ShieldCheck,
        badgeClass: "text-destructive border-destructive/40 bg-destructive/10"
      };
    default:
      return {
        label: permission,
        icon: Eye,
        badgeClass: "border-border text-muted bg-secondary/60"
      };
  }
}

// ---------------------------------------------------------------------------
// Key type helpers
// ---------------------------------------------------------------------------

export function getKeyTypeStyle(keyType: string): { label: string; scopeClass: string } {
  return keyType === "pk_"
    ? { label: m.api_keys_public_key(), scopeClass: "label-amethyst" }
    : { label: m.api_keys_secret_key(), scopeClass: "label-blue" };
}

/**
 * Admin variant — uses admin-specific translation keys and includes icon.
 */
export function getKeyTypeConfig(keyType: string): {
  label: string;
  icon: LucideIcon;
  scopeClass: string;
} {
  return keyType === "pk_"
    ? { label: m.api_keys_admin_key_type_public_label(), icon: Globe, scopeClass: "label-amethyst" }
    : { label: m.api_keys_admin_key_type_secret_label(), icon: Lock, scopeClass: "label-blue" };
}

// ---------------------------------------------------------------------------
// Locale-aware formatters
// ---------------------------------------------------------------------------

function resolveLocale(): string {
  return getLocale() === "sv" ? "sv-SE" : "en-US";
}

function resolveShortLocale(): string {
  return getLocale() === "sv" ? "sv" : "en";
}

export function createDateFormatter(): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat(resolveLocale(), {
    dateStyle: "medium",
    timeStyle: "short"
  });
}

export function createRelativeFormatter(): Intl.RelativeTimeFormat {
  return new Intl.RelativeTimeFormat(resolveShortLocale(), { numeric: "auto" });
}

export function createFullNumberFormatter(): Intl.NumberFormat {
  return new Intl.NumberFormat(resolveLocale());
}

export function createCompactNumberFormatter(): Intl.NumberFormat {
  return new Intl.NumberFormat(resolveLocale(), {
    notation: "compact",
    compactDisplay: "short",
    maximumFractionDigits: 1
  });
}

export function formatUsageMetric(
  formatter: Intl.NumberFormat,
  value: number | null | undefined
): string {
  return formatter.format(value ?? 0);
}

export function formatRelativeDate(
  formatter: Intl.DateTimeFormat,
  relFormatter: Intl.RelativeTimeFormat,
  date: string | null | undefined
): string {
  if (!date) return m.api_keys_never();
  const d = new Date(date);
  const now = new Date();
  const diffDays = Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return m.api_keys_today();
  if (diffDays === 1) return m.api_keys_yesterday();
  if (diffDays < 7) return relFormatter.format(-diffDays, "day");
  if (diffDays < 30) return relFormatter.format(-Math.floor(diffDays / 7), "week");
  return formatter.format(d);
}
