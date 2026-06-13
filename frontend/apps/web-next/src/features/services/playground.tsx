"use client";

import { useMutation } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { browserApi } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import { toastApiError } from "@/lib/api/toast";

function stringifyOutput(output: unknown): string {
  if (typeof output === "string") return output;
  return JSON.stringify(output, null, 2);
}

/** Run a service against an ad-hoc input and show its output. */
export function ServicePlayground({ serviceId }: { serviceId: string }) {
  const t = useTranslations();
  const [input, setInput] = useState("");
  const [output, setOutput] = useState("");

  const run = useMutation({
    mutationFn: async (text: string) => {
      const result = await unwrap(
        browserApi.POST("/api/v1/services/{id}/run/", {
          params: { path: { id: serviceId } },
          body: { input: text }
        })
      );
      return stringifyOutput(result.output);
    },
    onSuccess: (result) => setOutput(result),
    onError: (error) => toastApiError(error, t)
  });

  return (
    <div className="grid h-full grid-cols-1 gap-4 md:grid-cols-2">
      <div className="flex flex-col gap-3">
        <Label htmlFor="service-input">{t("input")}</Label>
        <Textarea
          id="service-input"
          value={input}
          rows={12}
          className="flex-1"
          onChange={(event) => setInput(event.target.value)}
        />
        <Button
          className="self-end"
          disabled={run.isPending || input.trim().length === 0}
          onClick={() => run.mutate(input)}
        >
          {run.isPending ? t("running") : t("run_this_service")}
        </Button>
      </div>
      <div className="flex flex-col gap-3">
        <Label>{t("output")}</Label>
        <div className="border-border bg-muted/40 min-h-48 flex-1 overflow-y-auto rounded-lg border p-4 font-mono text-sm whitespace-pre-wrap">
          {run.isPending ? t("loading") : output}
        </div>
        <Button
          variant="outline"
          className="self-end"
          disabled={!output}
          onClick={() => {
            void navigator.clipboard.writeText(output);
            toast.success(t("copied"));
          }}
        >
          <Copy className="size-4" />
          {t("copy_response")}
        </Button>
      </div>
    </div>
  );
}
