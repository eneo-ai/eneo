"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useRef, useState } from "react";
import { flushSync } from "react-dom";
import { FieldProblem, fieldProblemProps } from "@/components/composites/field-problem";
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
import { Switch } from "@/components/ui/switch";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { useSpace } from "@/features/spaces/use-space";

/**
 * Create a blank service, optionally opening its editor afterwards. A missing
 * name shows at the field on create, which takes focus.
 */
export function CreateServiceButton() {
  const t = useTranslations();
  const router = useRouter();
  const { space, routeId } = useSpace();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [openAfter, setOpenAfter] = useState(true);
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const nameProblem = submitted && !name.trim() ? t("required_field") : null;

  const create = useMutation({
    mutationFn: (serviceName: string) =>
      unwrap(
        browserApi.POST("/api/v1/spaces/{id}/applications/services/", {
          params: { path: { id: space.id } },
          body: { name: serviceName }
        })
      ),
    onSuccess: (service) => {
      void queryClient.invalidateQueries({ queryKey: ["spaces", routeId] });
      setOpen(false);
      setName("");
      if (openAfter) router.push(`/spaces/${routeId}/services/${service.id}?tab=settings`);
    },
    onError: (error) => toastApiError(error, t)
  });

  function createService() {
    if (create.isPending) return;
    if (!name.trim()) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      nameRef.current?.focus();
      return;
    }
    create.mutate(name.trim());
  }

  return (
    <>
      <Button onClick={() => setOpen(true)}>{t("create_service")}</Button>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) {
            setName("");
            setSubmitted(false);
          }
          setOpen(next);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("create_a_new_service")}</DialogTitle>
          </DialogHeader>
          <form
            className="flex flex-col gap-2"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              createService();
            }}
          >
            <Label htmlFor="service-name">{t("name")}</Label>
            <Input
              ref={nameRef}
              id="service-name"
              value={name}
              placeholder={`${t("name")}...`}
              onChange={(event) => setName(event.target.value)}
              {...fieldProblemProps("service-name", nameProblem)}
            />
            <FieldProblem id="service-name" problem={nameProblem} />
          </form>
          <DialogFooter className="sm:justify-between">
            <Label className="flex items-center gap-2 font-normal">
              <Switch checked={openAfter} onCheckedChange={setOpenAfter} />
              {t("open_service_editor_after_creation")}
            </Label>
            <div className="flex gap-2">
              <Button variant="outline" disabled={create.isPending} onClick={() => setOpen(false)}>
                {t("cancel")}
              </Button>
              {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
              <Button aria-busy={create.isPending || undefined} onClick={createService}>
                {create.isPending ? t("creating") : t("create_service")}
              </Button>
            </div>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
