"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, LayoutTemplate } from "lucide-react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const nameProblem = submitted && !name.trim() ? t("required_field") : null;

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

  // A missing name shows at the field, which takes focus.
  function createBlank() {
    if (create.isPending) return;
    if (!name.trim()) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      nameRef.current?.focus();
      return;
    }
    create.mutate({ appName: name.trim() });
  }

  return (
    <>
      {settings.using_templates ? (
        <div className="flex">
          <Button className="rounded-r-none" onClick={() => setDialog("blank")}>
            {t("create_app")}
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                size="icon"
                className="rounded-l-none border-l"
                aria-label={t("ui_more_ways_to_create")}
              >
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
          if (!next) {
            setName("");
            setSubmitted(false);
          }
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
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              createBlank();
            }}
          >
            <Label htmlFor="app-name">{t("name")}</Label>
            <Input
              ref={nameRef}
              id="app-name"
              value={name}
              placeholder={`${t("name")}...`}
              onChange={(event) => setName(event.target.value)}
              {...fieldProblemProps("app-name", nameProblem)}
            />
            <FieldProblem id="app-name" problem={nameProblem} />
          </form>
          <DialogFooter>
            <Button variant="outline" disabled={create.isPending} onClick={() => setDialog(null)}>
              {t("cancel")}
            </Button>
            {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
            <Button aria-busy={create.isPending || undefined} onClick={createBlank}>
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
