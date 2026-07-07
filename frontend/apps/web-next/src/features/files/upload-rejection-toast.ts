import { toast } from "sonner";
import { formatBytes } from "@/lib/format";
import type { UploadRejection, UploadPlanFile } from "./upload-plan";

export function toastUploadRejection<FileLike extends UploadPlanFile>(
  rejection: UploadRejection<FileLike>,
  t: (key: string, values?: Record<string, string | number | Date>) => string,
  shown: { maxFiles: boolean }
) {
  switch (rejection.reason) {
    case "unsupported-type":
      toast.error(`${rejection.file.name}: ${t("file_type_not_supported")}`);
      break;
    case "too-large":
      toast.error(
        `${rejection.file.name}: ${t("file_too_large")} (${formatBytes(rejection.limit ?? 0)})`
      );
      break;
    case "max-files":
      if (!shown.maxFiles) {
        toast.error(t("attachment_error_max_count", { count: rejection.limit ?? 0 }));
        shown.maxFiles = true;
      }
      break;
    case "max-total-size":
      toast.error(
        t("attachment_error_max_total_size", {
          fileName: rejection.file.name,
          maxSize: formatBytes(rejection.limit ?? 0)
        })
      );
      break;
  }
}
