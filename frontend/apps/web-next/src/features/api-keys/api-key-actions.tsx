import type { DropdownMenuOption } from "@astryxdesign/core/DropdownMenu";
import { MoreMenu } from "@astryxdesign/core/MoreMenu";
import { useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Bell,
  BellOff,
  CalendarClock,
  Eye,
  Pencil,
  Play,
  RefreshCw,
  Trash2
} from "lucide-react";
import { useTranslations } from "use-intl";
import { createContext, use, useId, useRef, useState, type ReactNode, type RefObject } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { createResourceActions } from "@/components/composites/resource-action-scope";
import { useAppContext } from "@/components/providers/app-context";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useRemovalMutation } from "@/features/spaces/removal";
import { browserApi } from "@/lib/api/browser";
import { ApiKeyDetailsDialog, type ApiKeyDetailsTab } from "./api-key-details";
import { ExtendExpirationDialog, KeyCard, RotateApiKeyDialog } from "./api-key-dialogs";
import { EditApiKeyDialog } from "./api-key-form";
import {
  canManageApiKey,
  invalidateApiKeys,
  purgeApiKey,
  reactivateApiKey,
  revokeApiKey,
  suspendApiKey,
  type ApiKey,
  type ApiKeyMode
} from "./api-keys";
import { useNotificationFollows } from "./notification-follows";

type KeyDialog = "details" | "edit" | "rotate" | "extend" | "suspend" | "revoke" | "purge";

/**
 * A key as its menu opened a dialog for it: the tab the details open on, the
 * scope's name, and the menu's button, by which a removal finds the next row.
 */
type OpenedKey = {
  apiKey: ApiKey;
  tab: ApiKeyDetailsTab;
  scopeName?: string;
  anchor: RefObject<HTMLElement | null>;
};

const { ResourceActionScope, useOpenResourceAction } = createResourceActions<
  OpenedKey,
  KeyDialog
>();

/** Whose labels and endpoints the menus and dialogs use, and where a rotated key's secret goes. */
const KeyScopeContext = createContext<{
  mode: ApiKeyMode;
  onRotated: (secret: string) => void;
}>({ mode: "user", onRotated: () => {} });

/** A label in the user's words, or the admin's. */
function useModeLabel(mode: ApiKeyMode) {
  const t = useTranslations();
  return (user: string, adminKey: string) => t(mode === "admin" ? adminKey : user);
}

/** The dialogs of a key's menu, held above the rows and the table that open them. */
function ApiKeyActionDialog({
  kind,
  resource: { apiKey, tab, scopeName, anchor },
  onClose
}: {
  kind: KeyDialog;
  resource: OpenedKey;
  onClose: () => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { mode, onRotated } = use(KeyScopeContext);
  const label = useModeLabel(mode);
  const reasonId = useId();
  const [reason, setReason] = useState("");
  const onOpenChange = (open: boolean) => {
    if (!open) onClose();
  };

  // Each takes the key out of the state it is listed under (or out of every
  // list): focus goes to the next row, or the list, once the lists refresh.
  const removal = {
    refresh: () => invalidateApiKeys(queryClient),
    onRemoved: onClose,
    anchor
  };
  const suspend = useRemovalMutation({
    ...removal,
    mutationFn: () => suspendApiKey(browserApi, mode, apiKey.id, reason)
  });
  const revoke = useRemovalMutation({
    ...removal,
    mutationFn: () => revokeApiKey(browserApi, mode, apiKey.id, reason)
  });
  const purge = useRemovalMutation({
    ...removal,
    mutationFn: () => purgeApiKey(browserApi, mode, apiKey.id)
  });

  const reasonField = (
    <div className="flex flex-col gap-4">
      <KeyCard apiKey={apiKey} />
      <div className="flex flex-col gap-2">
        <Label htmlFor={reasonId}>
          {label("api_keys_action_reason_optional", "api_keys_admin_reason_optional")}
        </Label>
        <Input id={reasonId} value={reason} onChange={(event) => setReason(event.target.value)} />
      </div>
    </div>
  );

  switch (kind) {
    case "details":
      return (
        <ApiKeyDetailsDialog
          apiKey={apiKey}
          mode={mode}
          tab={tab}
          scopeName={scopeName}
          open
          onOpenChange={onOpenChange}
        />
      );
    case "edit":
      return <EditApiKeyDialog apiKey={apiKey} mode={mode} open onOpenChange={onOpenChange} />;
    case "rotate":
      return (
        <RotateApiKeyDialog
          apiKey={apiKey}
          mode={mode}
          open
          onOpenChange={onOpenChange}
          onRotated={onRotated}
        />
      );
    case "extend":
      return (
        <ExtendExpirationDialog apiKey={apiKey} mode={mode} open onOpenChange={onOpenChange} />
      );
    case "suspend":
      return (
        <ConfirmDialogControlled
          open
          onOpenChange={onOpenChange}
          title={label("api_keys_action_suspend_title", "api_keys_admin_suspend_title")}
          description={label(
            "api_keys_action_suspend_description",
            "api_keys_admin_suspend_description"
          )}
          confirmLabel={label("api_keys_action_suspend", "api_keys_admin_action_suspend")}
          pending={suspend.isPending}
          onConfirm={() => {
            if (!suspend.isPending) suspend.mutate();
          }}
        >
          {reasonField}
        </ConfirmDialogControlled>
      );
    case "revoke":
      return (
        <ConfirmDialogControlled
          open
          onOpenChange={onOpenChange}
          title={label("api_keys_action_revoke_title", "api_keys_admin_revoke_title")}
          description={label(
            "api_keys_action_revoke_description",
            "api_keys_admin_revoke_description"
          )}
          confirmLabel={label("api_keys_action_revoke", "api_keys_admin_action_revoke")}
          pending={revoke.isPending}
          onConfirm={() => {
            if (!revoke.isPending) revoke.mutate();
          }}
        >
          {reasonField}
        </ConfirmDialogControlled>
      );
    case "purge":
      return (
        <ConfirmDialogControlled
          open
          onOpenChange={onOpenChange}
          title={t("api_keys_purge_dialog_title")}
          description={t("api_keys_purge_dialog_description")}
          confirmLabel={t("api_keys_purge_confirm")}
          pending={purge.isPending}
          onConfirm={() => {
            if (!purge.isPending) purge.mutate();
          }}
        >
          <KeyCard apiKey={apiKey} />
        </ConfirmDialogControlled>
      );
  }
}

/**
 * Above a list of keys: what their menus open, in `mode`. On a turn across
 * 768 px the rows and the table swap, and an open dialog stays with what was
 * typed or chosen in it. `focusTarget` is where focus goes when the menu that
 * opened one is gone.
 */
export function ApiKeyActionScope({
  mode,
  onRotated,
  focusTarget,
  children
}: {
  mode: ApiKeyMode;
  /** The rotated key's new secret, for the one-time reveal. */
  onRotated: (secret: string) => void;
  focusTarget: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <KeyScopeContext value={{ mode, onRotated }}>
      <ResourceActionScope Dialog={ApiKeyActionDialog} focusTarget={focusTarget}>
        {children}
      </ResourceActionScope>
    </KeyScopeContext>
  );
}

/**
 * Everything a user or an admin does with one key, from its row's menu, as in
 * the Svelte app's ApiKeyActionMenu: details and usage, edit, rotate, change
 * the expiry, follow its expiry reminders (users), suspend or revoke with an
 * optional reason, reactivate, and delete a revoked or expired key for good.
 * Destructive steps confirm and name the key. From the user's own pages a
 * personal key someone else owns is shown but not managed. Its dialogs are
 * the `ApiKeyActionScope`'s above it.
 */
export function ApiKeyMenu({
  apiKey,
  scopeName,
  ref
}: {
  apiKey: ApiKey;
  scopeName?: string;
  ref?: RefObject<HTMLButtonElement | null>;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { user } = useAppContext();
  const open = useOpenResourceAction();
  const { mode } = use(KeyScopeContext);
  const label = useModeLabel(mode);
  const ownTrigger = useRef<HTMLButtonElement>(null);
  const trigger = ref ?? ownTrigger;
  const admin = mode === "admin";
  const canManage = canManageApiKey(apiKey, mode, user.id);
  const { state } = apiKey;
  const ended = state === "revoked" || state === "expired";
  const follows = useNotificationFollows({ enabled: !admin });
  const followed = follows.follows("key", apiKey.id);
  // A followed space, assistant or app covers its keys.
  const followedViaScope =
    !followed &&
    apiKey.scope_type !== "tenant" &&
    apiKey.scope_id != null &&
    follows.follows(apiKey.scope_type, apiKey.scope_id);

  const show = (kind: KeyDialog, tab: ApiKeyDetailsTab = "overview") =>
    open(kind, { apiKey, tab, scopeName, anchor: trigger });
  // Takes the key out of the state it is listed under: focus goes to the next
  // row, or the list, once the lists refresh.
  const reactivate = useRemovalMutation({
    refresh: () => invalidateApiKeys(queryClient),
    anchor: trigger,
    mutationFn: () => reactivateApiKey(browserApi, mode, apiKey.id)
  });

  const items: DropdownMenuOption[] = [
    {
      label: t("api_keys_view_action"),
      icon: <Eye aria-hidden="true" />,
      onClick: () => show("details")
    },
    {
      label: t("api_keys_admin_tab_usage"),
      onClick: () => show("details", "usage")
    },
    {
      label: t("api_keys_admin_action_edit"),
      icon: <Pencil aria-hidden="true" />,
      isDisabled: !canManage,
      onClick: () => show("edit")
    },
    ...(state === "active"
      ? [
          {
            label: label("api_keys_action_rotate", "api_keys_admin_action_rotate"),
            icon: <RefreshCw aria-hidden="true" />,
            isDisabled: !canManage,
            onClick: () => show("rotate")
          }
        ]
      : []),
    ...(!ended
      ? [
          {
            label: label("api_keys_action_extend", "api_keys_admin_action_extend"),
            icon: <CalendarClock aria-hidden="true" />,
            isDisabled: !canManage,
            onClick: () => show("extend")
          }
        ]
      : []),
    ...(admin
      ? []
      : followedViaScope
        ? [
            {
              label: t("api_keys_notifications_followed_via_scope"),
              icon: <Bell aria-hidden="true" />,
              isDisabled: true
            }
          ]
        : !ended
          ? [
              {
                label: followed
                  ? t("api_keys_notifications_unfollow_action")
                  : t("api_keys_notifications_follow_action"),
                icon: followed ? <BellOff aria-hidden="true" /> : <Bell aria-hidden="true" />,
                onClick: () => {
                  if (!follows.toggle.isPending) {
                    follows.toggle.mutate({
                      targetType: "key",
                      targetId: apiKey.id,
                      follow: !followed
                    });
                  }
                }
              }
            ]
          : []),
    ...(state === "active"
      ? [
          {
            label: label("api_keys_action_suspend", "api_keys_admin_action_suspend"),
            icon: <Ban aria-hidden="true" />,
            isDisabled: !canManage,
            onClick: () => show("suspend")
          }
        ]
      : []),
    ...(state === "suspended"
      ? [
          {
            label: label("api_keys_action_reactivate", "api_keys_admin_action_reactivate"),
            icon: <Play aria-hidden="true" />,
            isDisabled: !canManage,
            onClick: () => {
              if (!reactivate.isPending) reactivate.mutate();
            }
          }
        ]
      : []),
    ...(state !== "revoked"
      ? [
          { type: "divider" as const },
          {
            label: label("api_keys_action_revoke", "api_keys_admin_action_revoke"),
            icon: <Ban aria-hidden="true" />,
            variant: "destructive" as const,
            isDisabled: !canManage,
            onClick: () => show("revoke")
          }
        ]
      : []),
    ...(ended
      ? [
          { type: "divider" as const },
          {
            label: label("api_keys_action_purge", "api_keys_admin_action_purge"),
            icon: <Trash2 aria-hidden="true" />,
            variant: "destructive" as const,
            isDisabled: !canManage,
            onClick: () => show("purge")
          }
        ]
      : [])
  ];

  return (
    <MoreMenu
      ref={trigger}
      label={t("ui_more_actions_for", { name: apiKey.name })}
      alignment="end"
      items={items}
    />
  );
}

/**
 * A key's menu with its own dialogs, for a page whose rows keep their layout
 * (the admin's table). A list that swaps rows and a table puts
 * `ApiKeyActionScope` above them and `ApiKeyMenu` in each instead.
 */
export function ApiKeyActions({
  apiKey,
  mode,
  onRotated,
  scopeName
}: {
  apiKey: ApiKey;
  mode: ApiKeyMode;
  /** The rotated key's new secret, for the one-time reveal. */
  onRotated: (secret: string) => void;
  scopeName?: string;
}) {
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <ApiKeyActionScope mode={mode} onRotated={onRotated} focusTarget={trigger}>
      <ApiKeyMenu ref={trigger} apiKey={apiKey} scopeName={scopeName} />
    </ApiKeyActionScope>
  );
}
