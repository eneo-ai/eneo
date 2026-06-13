"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";

/**
 * Blank app creation: posts the name then opens the editor. Template-based
 * creation (TemplateCreateApp) is deferred, tracked in the migration ledger.
 */
export function CreateAppButton() {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: (appName: string) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/applications/apps/", {
          params: { path: { id: space.id } },
          body: { name: appName }
        })
      ),
    onSuccess: (app) => {
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setOpen(false);
      router.push(`/spaces/${routeId}/apps/${app.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      <Button onClick={() => setOpen(true)}>{t("create_app")}</Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) setName("");
          setOpen(next);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("create_blank_app")}</DialogTitle>
            <DialogDescription>{t("get_started_creating_new_app")}</DialogDescription>
          </DialogHeader>
          <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim()) create.mutate(name.trim());
            }}
          >
            <Label htmlFor="app-name">{t("name")}</Label>
            <Input
              id="app-name"
              value={name}
              placeholder={`${t("name")}...`}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </form>
          <DialogFooter>
            <Button variant="outline" disabled={create.isPending} onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={create.isPending || !name.trim()}
              onClick={() => name.trim() && create.mutate(name.trim())}
            >
              {create.isPending ? t("loading") : t("create_app")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
