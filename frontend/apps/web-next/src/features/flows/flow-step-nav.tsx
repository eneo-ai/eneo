"use client";

import { Button } from "@astryxdesign/core/Button";
import { IconButton } from "@astryxdesign/core/IconButton";
import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { fieldTypeLine, SectionHeading, StepGlyph } from "./flow-definition";
import { stepKindLine } from "./flow-step-summary";
import { formFieldsOf, stepsOf, type FlowDefinition, type StepOriginPublic } from "./types";

/** The panel width from which the navigator shows names, not only numbers. */
export const NAV_FULL_WIDTH = "@min-[1200px]";

/**
 * The left navigator of the maximised step view: back to the overview, the
 * steps with the current one marked, then the run inputs. Full width when
 * the view is wide enough (a container query on the view), a 56 px rail of
 * numbered buttons below that. `locked` (a draft being edited) keeps the
 * reader on the current step.
 */
export function FlowStepNav({
  definition,
  origins = [],
  currentKey,
  onSelect,
  onOverview,
  locked = false,
  lockedNote
}: {
  definition: FlowDefinition;
  /** Where each step comes from; a step changed by hand says so under its name. */
  origins?: StepOriginPublic[];
  currentKey: string | null;
  onSelect: (key: string) => void;
  onOverview: () => void;
  locked?: boolean;
  /** Why the navigator is locked, shown under the steps. */
  lockedNote?: string;
}) {
  const t = useTranslations();
  const steps = stepsOf(definition);
  const fields = formFieldsOf(definition);
  const stepLabel = (index: number, name: string) =>
    t("flow_step_open", { index: index + 1, name });
  const manual = new Set(
    origins.filter((origin) => origin.channel === "api").map((origin) => origin.key)
  );
  return (
    <nav
      aria-label={t("flow_step_nav_label")}
      className="border-ax-border flex w-14 shrink-0 flex-col gap-4 overflow-y-auto border-e px-2 py-3 @min-[1200px]:w-72"
    >
      {/* Full width: names and kinds. */}
      <div className="hidden flex-col gap-4 @min-[1200px]:flex">
        <Button
          label={t("flow_step_overview")}
          variant="ghost"
          size="sm"
          icon={<ArrowLeft className="size-4" />}
          isDisabled={locked}
          onClick={onOverview}
          className="self-start"
        />
        <div className="flex flex-col gap-1.5">
          <SectionHeading>{t("flow_section_steps_short")}</SectionHeading>
          <List density="compact">
            {steps.map((step, index) => (
              <ListItem
                key={step.id ?? step.key}
                label={step.name}
                description={
                  manual.has(step.key)
                    ? `${stepKindLine(step, t)} · ${t("flow_changed_manually_short")}`
                    : stepKindLine(step, t)
                }
                startContent={<StepGlyph step={step} index={index} />}
                isSelected={step.key === currentKey}
                isDisabled={locked && step.key !== currentKey}
                onClick={() => onSelect(step.key)}
                aria-current={step.key === currentKey ? "page" : undefined}
              />
            ))}
          </List>
          {locked && lockedNote && (
            <Text
              type="supporting"
              size="xsm"
              as="p"
              display="block"
              className="m-0 px-2 leading-snug"
            >
              {lockedNote}
            </Text>
          )}
        </div>
        {fields.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <SectionHeading>{t("flow_section_inputs")}</SectionHeading>
            <List density="compact">
              {fields.map((field) => (
                <ListItem
                  key={field.key}
                  label={field.label}
                  description={fieldTypeLine(field, t)}
                />
              ))}
            </List>
          </div>
        )}
      </div>
      {/* Rail: numbers only, every button named. */}
      <div className="flex flex-col items-center gap-1 @min-[1200px]:hidden">
        <IconButton
          label={t("flow_step_overview")}
          tooltip={t("flow_step_overview")}
          icon={<ArrowLeft className="size-4" />}
          variant="ghost"
          size="sm"
          isDisabled={locked}
          onClick={onOverview}
        />
        {steps.map((step, index) => (
          <IconButton
            key={step.id ?? step.key}
            label={stepLabel(index, step.name)}
            tooltip={step.name}
            icon={<StepGlyph step={step} index={index} />}
            variant={step.key === currentKey ? "secondary" : "ghost"}
            size="sm"
            isDisabled={locked && step.key !== currentKey}
            aria-current={step.key === currentKey ? "page" : undefined}
            onClick={() => onSelect(step.key)}
          />
        ))}
      </div>
    </nav>
  );
}
