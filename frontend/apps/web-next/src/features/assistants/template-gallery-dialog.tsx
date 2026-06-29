"use client";

import { useQuery } from "@tanstack/react-query";
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
import { Skeleton } from "@/components/ui/skeleton";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";

/** Pick an assistant template and name it; creation passes from_template. */
export function TemplateGalleryDialog({
  open,
  onOpenChange,
  pending,
  onCreate
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  pending: boolean;
  onCreate: (templateId: string, name: string) => void;
}) {
  const t = useTranslations();
  const [selected, setSelected] = useState<{ id: string; name: string } | null>(null);
  const [name, setName] = useState("");

  const templates = useQuery({
    queryKey: ["assistant-templates-gallery"],
    enabled: open,
    queryFn: async () => (await unwrap(browserApi.GET("/api/v1/templates/assistants/"))).items
  });

  const reset = () => {
    setSelected(null);
    setName("");
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{t("select_a_template")}</DialogTitle>
        </DialogHeader>

        {templates.isPending ? (
          <Skeleton className="h-48 w-full" />
        ) : (templates.data ?? []).length === 0 ? (
          <p className="text-muted-foreground py-6 text-center text-sm">{t("no_results")}</p>
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {(templates.data ?? []).map((template) => (
              <button
                key={template.id}
                type="button"
                onClick={() => {
                  setSelected({ id: template.id, name: template.name });
                  setName((current) => current || template.name);
                }}
                className={`flex flex-col gap-1 rounded-lg border p-3 text-left transition-colors ${
                  selected?.id === template.id ? "border-primary bg-accent" : "hover:bg-muted/50"
                }`}
              >
                <span className="font-medium">{template.name}</span>
                {template.description && (
                  <span className="text-muted-foreground line-clamp-2 text-xs">
                    {template.description}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        {selected && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="template-create-name">{t("name")}</Label>
            <Input
              id="template-create-name"
              value={name}
              autoFocus
              onChange={(event) => setName(event.target.value)}
            />
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" disabled={pending} onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={!selected || !name.trim() || pending}
            onClick={() => selected && onCreate(selected.id, name.trim())}
          >
            {pending ? t("loading") : t("create_assistant")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
