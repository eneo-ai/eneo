"use client";

import { useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Bell,
  BellOff,
  CalendarClock,
  Eye,
  MoreHorizontal,
  Pencil,
  Play,
  RefreshCw,
  Trash2
} from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
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

type Dialog = "details" | "edit" | "rotate" | "extend" | "suspend" | "revoke" | "purge" | null;

/**
 * Everything a user or an admin does with one key, from its row's menu, as in
 * the Svelte app's ApiKeyActionMenu: details and usage, edit, rotate, change
 * the expiry, follow its expiry reminders (users), suspend or revoke with an
 * optional reason, reactivate, and delete a revoked or expired key for good.
 * Destructive steps confirm and name the key. From the user's own pages a
 * personal key someone else owns is shown but not managed.
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
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { user } = useAppContext();
  const reasonId = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [detailsTab, setDetailsTab] = useState<ApiKeyDetailsTab>("overview");
  const [reason, setReason] = useState("");
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

  const label = (user: string, adminKey: string) => t(admin ? adminKey : user);

  function open(next: Dialog) {
    setReason("");
    setDialog(next);
  }
  function close(next: boolean) {
    if (!next) setDialog(null);
  }
  // Each takes the key out of the state it is listed under (or out of every
  // list): focus goes to the next row, or the list, once the lists refresh.
  const removal = {
    refresh: () => invalidateApiKeys(queryClient),
    onRemoved: () => setDialog(null),
    anchor: trigger
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
  const reactivate = useRemovalMutation({
    ...removal,
    mutationFn: () => reactivateApiKey(browserApi, mode, apiKey.id)
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

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            ref={trigger}
            variant="ghost"
            size="icon"
            aria-label={t("ui_more_actions_for", { name: apiKey.name })}
          >
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem
            onSelect={() => {
              setDetailsTab("overview");
              open("details");
            }}
          >
            <Eye className="size-4" /> {t("api_keys_view_action")}
          </DropdownMenuItem>
          <DropdownMenuItem
            onSelect={() => {
              setDetailsTab("usage");
              open("details");
            }}
          >
            {t("api_keys_admin_tab_usage")}
          </DropdownMenuItem>
          <DropdownMenuItem disabled={!canManage} onSelect={() => open("edit")}>
            <Pencil className="size-4" /> {t("api_keys_admin_action_edit")}
          </DropdownMenuItem>
          {state === "active" && (
            <DropdownMenuItem disabled={!canManage} onSelect={() => open("rotate")}>
              <RefreshCw className="size-4" />{" "}
              {label("api_keys_action_rotate", "api_keys_admin_action_rotate")}
            </DropdownMenuItem>
          )}
          {!ended && (
            <DropdownMenuItem disabled={!canManage} onSelect={() => open("extend")}>
              <CalendarClock className="size-4" />{" "}
              {label("api_keys_action_extend", "api_keys_admin_action_extend")}
            </DropdownMenuItem>
          )}
          {!admin &&
            (followedViaScope ? (
              <DropdownMenuItem disabled>
                <Bell className="size-4" /> {t("api_keys_notifications_followed_via_scope")}
              </DropdownMenuItem>
            ) : (
              !ended && (
                <DropdownMenuItem
                  onSelect={() => {
                    if (!follows.toggle.isPending) {
                      follows.toggle.mutate({
                        targetType: "key",
                        targetId: apiKey.id,
                        follow: !followed
                      });
                    }
                  }}
                >
                  {followed ? <BellOff className="size-4" /> : <Bell className="size-4" />}{" "}
                  {followed
                    ? t("api_keys_notifications_unfollow_action")
                    : t("api_keys_notifications_follow_action")}
                </DropdownMenuItem>
              )
            ))}
          {state === "active" && (
            <DropdownMenuItem disabled={!canManage} onSelect={() => open("suspend")}>
              <Ban className="size-4" />{" "}
              {label("api_keys_action_suspend", "api_keys_admin_action_suspend")}
            </DropdownMenuItem>
          )}
          {state === "suspended" && (
            <DropdownMenuItem
              disabled={!canManage}
              onSelect={() => {
                if (!reactivate.isPending) reactivate.mutate();
              }}
            >
              <Play className="size-4" />{" "}
              {label("api_keys_action_reactivate", "api_keys_admin_action_reactivate")}
            </DropdownMenuItem>
          )}
          {state !== "revoked" && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                disabled={!canManage}
                onSelect={() => open("revoke")}
              >
                <Ban className="size-4" />{" "}
                {label("api_keys_action_revoke", "api_keys_admin_action_revoke")}
              </DropdownMenuItem>
            </>
          )}
          {ended && (
            <>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                variant="destructive"
                disabled={!canManage}
                onSelect={() => open("purge")}
              >
                <Trash2 className="size-4" />{" "}
                {label("api_keys_action_purge", "api_keys_admin_action_purge")}
              </DropdownMenuItem>
            </>
          )}
        </DropdownMenuContent>
      </DropdownMenu>

      <ApiKeyDetailsDialog
        apiKey={apiKey}
        mode={mode}
        tab={detailsTab}
        scopeName={scopeName}
        open={dialog === "details"}
        onOpenChange={close}
      />
      <EditApiKeyDialog apiKey={apiKey} mode={mode} open={dialog === "edit"} onOpenChange={close} />
      <RotateApiKeyDialog
        apiKey={apiKey}
        mode={mode}
        open={dialog === "rotate"}
        onOpenChange={close}
        onRotated={onRotated}
      />
      <ExtendExpirationDialog
        apiKey={apiKey}
        mode={mode}
        open={dialog === "extend"}
        onOpenChange={close}
      />
      <ConfirmDialogControlled
        open={dialog === "suspend"}
        onOpenChange={close}
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
      <ConfirmDialogControlled
        open={dialog === "revoke"}
        onOpenChange={close}
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
      <ConfirmDialogControlled
        open={dialog === "purge"}
        onOpenChange={close}
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
    </>
  );
}
