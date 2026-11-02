import { Paperclip } from "lucide-react";
import { useTranslations } from "use-intl";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { PolicySection } from "./policy-section";
import type { PolicyDraft } from "./use-policy-draft";

export function FilePolicySection({ draft }: { draft: PolicyDraft }) {
  const t = useTranslations();
  return (
    <PolicySection
      id="files"
      title={t("governance_files_heading")}
      description={t("governance_files_section_desc")}
      summary={draft.filesSummary}
      summaryVariant="outline"
      icon={<Paperclip className="size-5" />}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <Label htmlFor="files-large">{t("attachments_open_files_label")}</Label>
          <div id="files-large-help" className="text-muted-foreground mt-1 space-y-2 text-sm">
            <p>
              <span className="font-semibold">{t("attachments_open_files_on_label")}:</span>{" "}
              {t("attachments_open_files_on")}
            </p>
            <p>
              <span className="font-semibold">{t("attachments_open_files_off_label")}:</span>{" "}
              {t("attachments_open_files_off")}
            </p>
            <p>
              <span className="font-semibold">{t("attachments_open_files_example_label")}:</span>{" "}
              {t("attachments_open_files_example")}
            </p>
          </div>
        </div>
        <Switch
          id="files-large"
          checked={draft.openFilesEnabled}
          onCheckedChange={draft.setOpenFiles}
          aria-describedby="files-large-help"
        />
      </div>
    </PolicySection>
  );
}
