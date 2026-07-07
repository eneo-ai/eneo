"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export function NoCreatePermissionInfo({ resourceType }: { resourceType: string }) {
  const t = useTranslations();
  const message = t("knowledge_create_no_permission", { resourceType });

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          aria-label={message}
          className="text-muted-foreground hover:text-foreground"
        >
          <Info className="size-4" />
        </Button>
      </TooltipTrigger>
      <TooltipContent side="bottom" className="max-w-72">
        {message}
      </TooltipContent>
    </Tooltip>
  );
}
