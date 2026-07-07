"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LayoutTemplate } from "lucide-react";
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
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import type { Schema } from "@/lib/api/models";
import { useAppContext } from "@/components/providers/app-context";
import { useSpace } from "@/features/spaces/use-space";
import { TemplateGalleryDialog } from "@/features/templates/template-gallery-dialog";

export function CreateAppButton() {
  const t = useTranslations();
  const router = useRouter();
  const { settings } = useAppContext();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [dialog, setDialog] = useState<"blank" | "template" | null>(null);
  const [name, setName] = useState("");

  const create = useMutation({
    mutationFn: ({
      appName,
      fromTemplate
    }: {
      appName: string;
      fromTemplate?: Schema<"TemplateCreate">;
    }) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/applications/apps/", {
          params: { path: { id: space.id } },
          body: {
            name: appName,
            ...(fromTemplate ? { from_template: fromTemplate } : {})
          }
        })
      ),
    onSuccess: (app) => {
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setDialog(null);
      router.push(`/spaces/${routeId}/apps/${app.id}/edit`);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <>
      {settings.using_templates ? (
        <div className="flex">
          <Button className="rounded-r-none" onClick={() => setDialog("blank")}>
            {t("create_app")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button size="icon" className="rounded-l-none border-l" aria-label={t("actions")}>
                <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => setDialog("template")}>
                <LayoutTemplate className="size-4" /> {t("start_with_template")}
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      ) : (
        <Button onClick={() => setDialog("blank")}>{t("create_app")}</Button>
      )}
      <Dialog
        open={dialog === "blank"}
        onOpenChange={(next) => {
          if (!next) setName("");
          setDialog(next ? "blank" : null);
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
              if (name.trim()) create.mutate({ appName: name.trim() });
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
            <Button variant="outline" disabled={create.isPending} onClick={() => setDialog(null)}>
              {t("cancel")}
            </Button>
            <Button
              disabled={create.isPending || !name.trim()}
              onClick={() => name.trim() && create.mutate({ appName: name.trim() })}
            >
              {create.isPending ? t("loading") : t("create_app")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <TemplateGalleryDialog
        templateKind="app"
        createLabel={t("create_app")}
        open={dialog === "template"}
        onOpenChange={(next) => setDialog(next ? "template" : null)}
        pending={create.isPending}
        onCreate={(fromTemplate, templateName) =>
          create.mutateAsync({ appName: templateName, fromTemplate }).then(() => undefined)
        }
      />
    </>
  );
}
