"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Trash2, Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
import { entityAccent } from "@/lib/entity-accent";
import { cn } from "@/lib/utils";
import { spaceRouteId, spacesListQueryOptions, type SpaceSparse } from "@/features/spaces/space";

function CreateSpaceDialog() {
  const t = useTranslations();
  const router = useRouter();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");

  const createSpace = useMutation({
    mutationFn: (body: { name: string }) => unwrap(browserApi.POST("/api/v1/spaces/", { body })),
    onSuccess: (space) => {
      queryClient.invalidateQueries({ queryKey: ["spaces"] });
      setOpen(false);
      setName("");
      router.push(`/spaces/${space.id}/overview`);
    },
    onError: (error) => toastApiError(error, t)
  });

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>{t("create_space")}</Button>
      </DialogTrigger>
      <DialogContent>
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (name.trim()) createSpace.mutate({ name: name.trim() });
          }}
        >
          <DialogHeader>
            <DialogTitle>{t("create_new_space")}</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2">
            <Label htmlFor="space-name">{t("name")}</Label>
            <Input
              id="space-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
              autoFocus
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button type="submit" disabled={!name.trim() || createSpace.isPending}>
              {createSpace.isPending ? t("loading") : t("create_space")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function DeleteSpaceButton({ space }: { space: SpaceSparse }) {
  const t = useTranslations();
  const queryClient = useQueryClient();

  const deleteSpace = useMutation({
    mutationFn: () =>
      unwrap(browserApi.DELETE("/api/v1/spaces/{id}/", { params: { path: { id: space.id } } })),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["spaces"] }),
    onError: (error) => toastApiError(error, t)
  });

  return (
    <ConfirmDialog
      trigger={
        <Button variant="ghost" size="icon" aria-label={t("delete_space")}>
          <Trash2 className="text-destructive size-4" />
        </Button>
      }
      title={t("delete_space")}
      description={t("confirm_delete_space_message", { space: space.name })}
      confirmLabel={deleteSpace.isPending ? t("deleting") : t("confirm_deletion")}
      confirmValue={space.name}
      confirmValueLabel={t("enter_space_name_to_confirm")}
      pending={deleteSpace.isPending}
      onConfirm={() => deleteSpace.mutateAsync().then(() => undefined)}
    />
  );
}

export function SpacesList({ title }: { title: string }) {
  const t = useTranslations();
  const { can } = useAppContext();
  const { data: spaces } = useSuspenseQuery(spacesListQueryOptions(browserApi));

  // Personal and organization spaces have their own surfaces.
  const sharedSpaces = spaces.filter((space) => !space.personal && !space.organization);

  return (
    <>
      <PageHeader title={title}>{can("shared_spaces") && <CreateSpaceDialog />}</PageHeader>
      {sharedSpaces.length === 0 ? (
        <EmptyState title={t("your_spaces")} description={t("create_new_space")}>
          {can("shared_spaces") && (
            <div className="pt-2">
              <CreateSpaceDialog />
            </div>
          )}
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {sharedSpaces.map((space) => (
            <Card
              key={space.id}
              className="group hover:border-primary/40 focus-within:border-ring focus-within:ring-ring/50 relative gap-3 p-5 transition-colors focus-within:ring-[3px]"
            >
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    "flex size-10 shrink-0 items-center justify-center rounded-lg",
                    entityAccent(space.id)
                  )}
                >
                  <Users className="size-5" />
                </span>
                <Link
                  href={`/spaces/${spaceRouteId(space)}/overview`}
                  className="min-w-0 flex-1 font-medium after:absolute after:inset-0 focus-visible:outline-none"
                >
                  <span className="line-clamp-1">{space.name}</span>
                </Link>
              </div>
              <p className="text-muted-foreground line-clamp-2 min-h-10 text-sm">
                {space.description || "—"}
              </p>
              {space.permissions?.includes("delete") && (
                <div className="absolute top-3 right-3 z-10 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                  <DeleteSpaceButton space={space} />
                </div>
              )}
            </Card>
          ))}
        </div>
      )}
    </>
  );
}
