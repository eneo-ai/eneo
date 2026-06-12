"use client";

import { useMutation, useQueryClient, useSuspenseQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { ConfirmDialog } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";
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
        <EmptyState title={t("your_spaces")} description={t("create_new_space")} />
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t("name")}</TableHead>
              <TableHead>{t("description")}</TableHead>
              <TableHead className="w-20 text-right">{t("actions")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sharedSpaces.map((space) => (
              <TableRow key={space.id}>
                <TableCell>
                  <Link
                    href={`/spaces/${spaceRouteId(space)}/overview`}
                    className="font-medium hover:underline"
                  >
                    {space.name}
                  </Link>
                </TableCell>
                <TableCell className="text-muted-foreground max-w-md truncate">
                  {space.description ?? <Badge variant="outline">—</Badge>}
                </TableCell>
                <TableCell className="text-right">
                  {space.permissions?.includes("delete") && <DeleteSpaceButton space={space} />}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </>
  );
}
