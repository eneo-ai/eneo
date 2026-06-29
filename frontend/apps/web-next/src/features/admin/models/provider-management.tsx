"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { toastApiError } from "@/lib/api/toast";
import {
  type ModelProvider,
  PROVIDERS_KEY,
  deleteProvider,
  modelProvidersQueryOptions,
  updateProvider
} from "./model-providers";
import { MODELS_KEY } from "./models";

function ProviderEditDialog({
  provider,
  open,
  onOpenChange
}: {
  provider: ModelProvider;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [name, setName] = useState(provider.name);
  const [isActive, setIsActive] = useState(provider.is_active);
  const [changingKey, setChangingKey] = useState(false);
  const [apiKey, setApiKey] = useState("");

  const save = useMutation({
    mutationFn: () =>
      updateProvider(browserApi, provider.id, {
        name: name.trim(),
        is_active: isActive,
        ...(changingKey && apiKey ? { credentials: { api_key: apiKey } } : {})
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      toast.success(t("provider_updated_success"));
      onOpenChange(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t("edit_provider")} — {provider.provider_type}
          </DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="provider-edit-name">{t("provider_name")}</Label>
            <Input
              id="provider-edit-name"
              value={name}
              placeholder={t("provider_name_placeholder")}
              onChange={(event) => setName(event.target.value)}
            />
          </div>
          <Label className="flex items-center justify-between gap-2 font-normal">
            {t("provider_is_active")}
            <Switch checked={isActive} onCheckedChange={setIsActive} />
          </Label>
          <div className="flex flex-col gap-1.5">
            <Label>{t("api_key")}</Label>
            {changingKey ? (
              <>
                <Input
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(event) => setApiKey(event.target.value)}
                />
                <Button
                  type="button"
                  variant="link"
                  size="sm"
                  className="w-fit px-0"
                  onClick={() => {
                    setChangingKey(false);
                    setApiKey("");
                  }}
                >
                  {t("cancel_keep_current_key")}
                </Button>
              </>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-muted-foreground font-mono text-xs">
                  {provider.masked_api_key ?? "••••"}
                </span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => setChangingKey(true)}
                >
                  {t("change")}
                </Button>
              </div>
            )}
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button disabled={save.isPending || !name.trim()} onClick={() => save.mutate()}>
            {save.isPending ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ProviderRow({ provider }: { provider: ModelProvider }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [showEdit, setShowEdit] = useState(false);
  const [showDelete, setShowDelete] = useState(false);

  const remove = useMutation({
    mutationFn: () => deleteProvider(browserApi, provider.id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: PROVIDERS_KEY });
      void queryClient.invalidateQueries({ queryKey: MODELS_KEY });
      setShowDelete(false);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Card className="flex items-center justify-between gap-4 p-4">
      <div className="flex min-w-0 flex-col">
        <span className="font-medium">{provider.name}</span>
        <span className="text-muted-foreground text-xs">
          {provider.provider_type}
          {provider.masked_api_key ? ` · ${provider.masked_api_key}` : ""}
        </span>
      </div>
      <div className="flex items-center gap-2">
        {!provider.is_active && <Badge variant="secondary">{t("inactive")}</Badge>}
        <Button variant="outline" size="sm" onClick={() => setShowEdit(true)}>
          {t("edit_provider")}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setShowDelete(true)}>
          {t("delete")}
        </Button>
      </div>
      <ProviderEditDialog provider={provider} open={showEdit} onOpenChange={setShowEdit} />
      <ConfirmDialogControlled
        open={showDelete}
        onOpenChange={setShowDelete}
        title={t("delete_provider")}
        description={`${t("delete_provider_confirm", { name: provider.name })} ${t("delete_provider_warning")}`}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </Card>
  );
}

/** Custom (tenant-created) model providers: edit + delete. */
export function CustomProvidersSection() {
  const t = useTranslations();
  const { data: providers } = useQuery(modelProvidersQueryOptions(browserApi));

  if (!providers || providers.length === 0) return null;

  return (
    <div className="flex flex-col gap-3">
      <span className="text-sm font-medium">{t("custom_providers")}</span>
      {providers.map((provider) => (
        <ProviderRow key={provider.id} provider={provider} />
      ))}
    </div>
  );
}
