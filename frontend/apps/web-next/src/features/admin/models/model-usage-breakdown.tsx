import { useId } from "react";
import { useTranslations } from "use-intl";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import type { ModelUsageEntity } from "./models";

/** Labels for the entity types the usage endpoint returns; an unknown one shows as sent. */
const ENTITY_TYPE_KEYS = new Map([
  ["assistant", "assistant"],
  ["app", "app"],
  ["service", "model_usage_type_service"],
  ["assistant_template", "model_usage_type_assistant_template"],
  ["app_template", "model_usage_type_app_template"]
]);

export function ModelUsageBreakdown({
  data
}: {
  data: { items: ModelUsageEntity[]; total: number };
}) {
  const t = useTranslations();
  const titleId = useId();
  const entityTypeLabel = (type: string) => {
    const key = ENTITY_TYPE_KEYS.get(type);
    return key ? t(key) : type;
  };
  if (data.items.length === 0)
    return <p className="text-muted-foreground py-4 text-sm">{t("model_usage_empty")}</p>;
  return (
    <div className="flex flex-col gap-2">
      <p id={titleId} className="text-muted-foreground text-xs">
        {t("model_usage_title")}
      </p>
      <p className="text-muted-foreground text-xs">
        {t("model_usage_shown_count", { shown: data.items.length, total: data.total })}
      </p>
      <div className="overflow-x-auto">
        <Table aria-labelledby={titleId}>
          <TableHeader>
            <TableRow>
              <TableHead>{t("name")}</TableHead>
              <TableHead>{t("migration_impact_type")}</TableHead>
              <TableHead>{t("migration_impact_space")}</TableHead>
              <TableHead>{t("migration_impact_owner")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.map((entity) => (
              <TableRow key={`${entity.entity_type}-${entity.entity_id}`}>
                <TableCell className="text-sm font-medium">{entity.entity_name}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{entityTypeLabel(entity.entity_type)}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {entity.space_name ?? "—"}
                </TableCell>
                <TableCell className="text-muted-foreground text-sm">
                  {entity.owner_name ?? "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
