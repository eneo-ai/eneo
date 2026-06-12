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
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { browserApi } from "@/lib/api/browser";
import { spacesListQueryOptions } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";

/**
 * Move a resource to another accessible space. The hint warns about what the
 * move breaks; the transfer itself fails if the target lacks matching models.
 * Extra rows (e.g. the assistant "include knowledge" switch) go in children.
 */
export function MoveResourceDialog({
  open,
  onOpenChange,
  title,
  hint,
  confirmLabel,
  pending,
  onMove,
  children
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  hint?: string;
  confirmLabel: string;
  pending: boolean;
  onMove: (targetSpaceId: string) => void;
  children?: React.ReactNode;
}) {
  const t = useTranslations();
  const { space } = useSpace();
  const [targetId, setTargetId] = useState<string | undefined>();

  const { data: spaces } = useQuery({ ...spacesListQueryOptions(browserApi), enabled: open });
  const targets = (spaces ?? []).filter((candidate) => candidate.id !== space.id);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label>{t("destination")}</Label>
          <Select value={targetId} onValueChange={setTargetId}>
            <SelectTrigger className="w-full">
              <SelectValue placeholder={t("select_ellipsis")} />
            </SelectTrigger>
            <SelectContent>
              {targets.map((target) => (
                <SelectItem key={target.id} value={target.id}>
                  {target.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {children}
          {hint && (
            <p className="text-muted-foreground text-sm">
              <span className="font-medium">{t("hint")}: </span>
              {hint}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={!targetId || pending}
            onClick={() => targetId && onMove(targetId)}
          >
            {pending ? t("moving") : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
