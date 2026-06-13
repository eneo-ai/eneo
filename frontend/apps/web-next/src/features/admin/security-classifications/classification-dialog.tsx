"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import {
  SECURITY_CLASSIFICATIONS_KEY,
  type SecurityClassification
} from "./security-classifications";

/** Create (new lowest-security level) or rename/redescribe an existing classification. */
export function ClassificationDialog({
  open,
  onOpenChange,
  classification
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Omitted → create mode. */
  classification?: SecurityClassification;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const mode = classification ? "edit" : "create";

  const [name, setName] = useState(classification?.name ?? "");
  const [description, setDescription] = useState(classification?.description ?? "");

  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: SECURITY_CLASSIFICATIONS_KEY });

  const save = useMutation({
    mutationFn: () => {
      if (classification) {
        return unwrap(
          browserApi.PATCH("/api/v1/security-classifications/{id}/", {
            params: { path: { id: classification.id } },
            body: { name, description }
          })
        );
      }
      return unwrap(
        browserApi.POST("/api/v1/security-classifications/", {
          body: { name, description, set_lowest_security: true }
        })
      );
    },
    onSuccess: () => {
      invalidate();
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {mode === "create"
              ? t("create_security_classification")
              : t("edit_security_classification")}
          </DialogTitle>
        </DialogHeader>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) save.mutate();
          }}
        >
          <div className="flex flex-col gap-2">
            <Label htmlFor="classification-name">{t("name")}</Label>
            <Input
              id="classification-name"
              value={name}
              autoFocus
              placeholder={t("recognisable_display_name")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="classification-description">{t("description")}</Label>
            <Textarea
              id="classification-description"
              value={description}
              rows={3}
              placeholder={t("describe_when_classification_chosen")}
              onChange={(event) => setDescription(event.target.value)}
            />
          </div>
        </form>
        <DialogFooter>
          <Button variant="outline" disabled={save.isPending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={save.isPending || !name.trim()} onClick={() => save.mutate()}>
            {save.isPending ? t("loading") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
