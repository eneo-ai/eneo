"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import {
  ArrowDownToLine,
  ArrowUpToLine,
  Lock,
  LockOpen,
  MoreHorizontal,
  Pencil,
  Trash2
} from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { PageHeader } from "@/components/composites/page-header";
import { SettingsGroup, SettingsRow } from "@/components/composites/settings-rows";
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle
} from "@/components/ui/alert-dialog";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { ClassificationDialog } from "./classification-dialog";
import {
  SECURITY_CLASSIFICATIONS_KEY,
  highestFirst,
  securityClassificationsQueryOptions,
  type SecurityClassification
} from "./security-classifications";

function ClassificationActions({
  classification,
  isHighest,
  isLowest,
  onMove
}: {
  classification: SecurityClassification;
  isHighest: boolean;
  isLowest: boolean;
  onMove: (direction: "up" | "down") => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () =>
      unwrap(
        browserApi.DELETE("/api/v1/security-classifications/{id}/", {
          params: { path: { id: classification.id } }
        })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon" aria-label={t("actions")}>
            <MoreHorizontal className="size-4" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem disabled={isHighest} onSelect={() => onMove("up")}>
            <ArrowUpToLine className="size-4" /> {t("move_up")}
          </DropdownMenuItem>
          <DropdownMenuItem disabled={isLowest} onSelect={() => onMove("down")}>
            <ArrowDownToLine className="size-4" /> {t("move_down")}
          </DropdownMenuItem>
          <DropdownMenuItem onSelect={() => setShowEdit(true)}>
            <Pencil className="size-4" /> {t("edit")}
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onSelect={() => setShowDelete(true)}>
            <Trash2 className="size-4" /> {t("delete")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <ClassificationDialog
        open={showEdit}
        onOpenChange={setShowEdit}
        classification={classification}
      />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_security_classification")}
        description={t("confirm_delete_classification", { name: classification.name })}
        confirmLabel={remove.isPending ? t("deleting") : t("delete_classification")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}

function EnableToggle({ enabled }: { enabled: boolean }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [confirm, setConfirm] = useState<null | "enable" | "disable">(null);

  const toggle = useMutation({
    mutationFn: (next: boolean) =>
      unwrap(
        browserApi.POST("/api/v1/security-classifications/enable/", { body: { enabled: next } })
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY });
      setConfirm(null);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <SettingsRow
      title={t("security_classification")}
      description={t("enable_security_description")}
    >
      <Label className="flex items-center justify-between gap-2 py-1 font-normal">
        {enabled ? t("enabled") : t("disabled")}
        <Switch
          checked={enabled}
          disabled={toggle.isPending}
          onCheckedChange={(next) => setConfirm(next ? "enable" : "disable")}
        />
      </Label>
      <AlertDialog open={confirm !== null} onOpenChange={(open) => !open && setConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>
              {confirm === "disable"
                ? t("disable_security_classifications")
                : t("enable_security_classifications")}
            </AlertDialogTitle>
            <AlertDialogDescription>
              {confirm === "disable"
                ? t("disable_security_classifications_dialog_description")
                : t("enable_security_classifications_dialog_description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={toggle.isPending}>{t("cancel")}</AlertDialogCancel>
            <Button
              variant={confirm === "disable" ? "destructive" : "default"}
              disabled={toggle.isPending}
              onClick={() => toggle.mutate(confirm === "enable")}
            >
              {confirm === "disable" ? t("disable") : t("enable")}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </SettingsRow>
  );
}

export function SecurityClassificationsPage() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const { data } = useSuspenseQuery(securityClassificationsQueryOptions(browserApi));
  const [showCreate, setShowCreate] = useState(false);

  const ordered = highestFirst(data.security_classifications);

  const reorder = useMutation({
    // The rank endpoint takes ids least-secure first, so reverse the display order.
    mutationFn: (displayOrder: SecurityClassification[]) =>
      unwrap(
        browserApi.PATCH("/api/v1/security-classifications/", {
          body: {
            security_classifications: [...displayOrder].reverse().map((item) => ({ id: item.id }))
          }
        })
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY }),
    onError: (error) => toastApiError(error, t)
  });

  function move(index: number, direction: "up" | "down") {
    const target = direction === "up" ? index - 1 : index + 1;
    const current = ordered[index];
    const swap = ordered[target];
    if (!current || !swap) return;
    const next = [...ordered];
    next[index] = swap;
    next[target] = current;
    reorder.mutate(next);
  }

  return (
    <div className="mx-auto flex w-full max-w-4xl flex-col gap-6">
      <PageHeader title={t("security_classifications")} />

      <SettingsGroup title={t("general")}>
        <EnableToggle enabled={data.security_enabled} />
      </SettingsGroup>

      <SettingsGroup title={t("configuration")}>
        <SettingsRow title={t("classifications")} description={t("classifications_description")}>
          <div className="flex justify-end">
            <Button size="sm" onClick={() => setShowCreate(true)}>
              {t("create_security_classification")}
            </Button>
          </div>
          <div className="relative flex flex-col gap-2">
            <div className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
              <Lock className="size-4" /> {t("highest_security")}
            </div>
            {ordered.length === 0 ? (
              <p className="text-muted-foreground py-6 text-center text-sm">
                {t("no_security_classifications")}
              </p>
            ) : (
              ordered.map((classification, index) => (
                <div
                  key={classification.id}
                  className="border-border bg-card flex items-start justify-between gap-4 rounded-lg border p-4"
                >
                  <div className="flex min-w-0 flex-col gap-1">
                    <span className="font-semibold">{classification.name}</span>
                    {classification.description && (
                      <span className="text-muted-foreground text-sm">
                        {classification.description}
                      </span>
                    )}
                  </div>
                  <ClassificationActions
                    classification={classification}
                    isHighest={index === 0}
                    isLowest={index === ordered.length - 1}
                    onMove={(direction) => move(index, direction)}
                  />
                </div>
              ))
            )}
            <div className="text-muted-foreground flex items-center gap-2 text-sm font-medium">
              <LockOpen className="size-4" /> {t("lowest_security")}
            </div>
          </div>
        </SettingsRow>
      </SettingsGroup>

      <ClassificationDialog open={showCreate} onOpenChange={setShowCreate} />
    </div>
  );
}
