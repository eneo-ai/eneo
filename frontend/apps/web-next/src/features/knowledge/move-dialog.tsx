"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
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
 * A missing destination shows at its picker on move, which takes focus.
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
  const destinationId = useId();
  const [targetId, setTargetId] = useState<string | undefined>();
  const [submitted, setSubmitted] = useState(false);
  const destinationRef = useRef<HTMLButtonElement>(null);
  const destinationProblem = submitted && !targetId ? t("select_a_space") : null;

  const { data: spaces } = useQuery({ ...spacesListQueryOptions(browserApi), enabled: open });
  const targets = (spaces ?? []).filter((candidate) => candidate.id !== space.id);

  function move() {
    if (pending) return;
    if (!targetId) {
      // Rendered before focus moves, so the field is read with its error.
      flushSync(() => setSubmitted(true));
      destinationRef.current?.focus();
      return;
    }
    onMove(targetId);
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setSubmitted(false);
        onOpenChange(next);
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-2">
          <Label htmlFor={destinationId}>{t("destination")}</Label>
          <Select value={targetId} onValueChange={setTargetId}>
            <SelectTrigger
              ref={destinationRef}
              id={destinationId}
              className="w-full"
              {...fieldProblemProps(destinationId, destinationProblem)}
            >
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
          <FieldProblem id={destinationId} problem={destinationProblem} />
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
          {/* Never disabled: busy, it keeps focus and a second press is ignored. */}
          <Button variant="destructive" aria-busy={pending || undefined} onClick={move}>
            {pending ? t("moving") : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
