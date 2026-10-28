"use client";

import { Button } from "@astryxdesign/core/Button";
import { Collapsible, CollapsibleGroup } from "@astryxdesign/core/Collapsible";
import { Link } from "@astryxdesign/core/Link";
import {
  Check,
  Copy,
  FileBox,
  FileLock,
  FileMinus,
  FileText,
  FileX,
  Lock,
  RefreshCw,
  ScanText,
  TriangleAlert,
  Weight,
  type LucideIcon
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";
import { useClientTimeText } from "@/components/composites/client-time";
import { LoadingState } from "@/components/composites/loading-state";
import { SuccessMark } from "@/components/composites/success-mark";
import { cn } from "@/lib/utils";
import type { IntegrationKnowledge } from "../../knowledge";
import type {
  FileProblemCategory,
  FileProblemGroup,
  SourceProblems,
  SyncFailure
} from "../source-problems";
import { SamePageLink, type InPlaceLink } from "@/components/composites/in-place-link";
import { useCopy } from "@/lib/hooks/use-copy";

const FILES_SHOWN = 10;

const CATEGORIES: Record<FileProblemCategory, { icon: LucideIcon; title: string; advice: string }> =
  {
    no_text_layer: {
      icon: ScanText,
      title: "integration_problem_no_text_layer_title",
      advice: "integration_problem_no_text_layer_advice"
    },
    too_large: {
      icon: Weight,
      title: "integration_problem_too_large_title",
      advice: "integration_problem_too_large_advice"
    },
    too_much_text: {
      icon: FileText,
      title: "integration_problem_too_much_text_title",
      advice: "integration_problem_too_much_text_advice"
    },
    password_protected: {
      icon: FileLock,
      title: "integration_problem_password_protected_title",
      advice: "integration_problem_password_protected_advice"
    },
    corrupt: {
      icon: FileX,
      title: "integration_problem_corrupt_title",
      advice: "integration_problem_corrupt_advice"
    },
    empty: {
      icon: FileMinus,
      title: "integration_problem_empty_title",
      advice: "integration_problem_empty_advice"
    },
    transient: {
      icon: RefreshCw,
      title: "integration_problem_transient_title",
      advice: "integration_problem_transient_advice"
    },
    unsupported: {
      icon: FileBox,
      title: "integration_problem_unsupported_title",
      advice: "integration_problem_unsupported_advice"
    }
  };

const TONES = {
  error: "bg-ax-error-muted text-ax-error",
  warning: "bg-ax-warning-muted text-ax-warning",
  neutral: "bg-ax-muted text-ax-text-secondary"
} as const;

// The group rows carry a title, advice and a count; the label span must be
// able to shrink so long advice wraps instead of pushing the chevron out.
const GROUP_CLASS =
  "[&_.astryx-collapsible-trigger]:gap-3 [&_.astryx-collapsible-trigger>span:first-child]:min-w-0";

const DETAILS_CLASS =
  "[&_.astryx-collapsible-trigger]:text-ax-text-secondary [&_.astryx-collapsible-trigger]:min-h-6 [&_.astryx-collapsible-trigger]:text-xs [&_.astryx-collapsible-trigger]:font-medium pointer-coarse:[&_.astryx-collapsible-trigger]:min-h-11";

function folderLabel(item: Pick<IntegrationKnowledge, "name" | "folder_path">): string {
  return item.folder_path || item.name;
}

function ProblemIcon({ icon: Icon, tone }: { icon: LucideIcon; tone: keyof typeof TONES }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "rounded-ax-inner flex size-8 shrink-0 items-center justify-center",
        TONES[tone]
      )}
    >
      <Icon className="size-4" />
    </span>
  );
}

function CopyAdminLink({ url }: { url: string }) {
  const t = useTranslations();
  const { copy, isCopied } = useCopy();
  return (
    <Button
      size="sm"
      label={isCopied ? t("copied") : t("integration_problem_copy_admin_link")}
      icon={
        isCopied ? (
          <Check className="size-4" aria-hidden="true" />
        ) : (
          <Copy className="size-4" aria-hidden="true" />
        )
      }
      onClick={() => void copy(url)}
    />
  );
}

function CredentialsCard({
  lastSyncedAt,
  isAdmin,
  adminIntegrationsUrl
}: {
  lastSyncedAt: string | null;
  isAdmin: boolean;
  adminIntegrationsUrl: string;
}) {
  const t = useTranslations();
  const lastSynced = useClientTimeText(lastSyncedAt, "date_time");
  return (
    <div className="border-ax-error rounded-ax-container flex gap-3 border p-4">
      <ProblemIcon icon={Lock} tone="error" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className="font-medium">{t("integration_problem_credentials_title")}</h3>
        <p className="text-sm">{t("integration_problem_credentials_description")}</p>
        {lastSynced ? (
          <p className="text-ax-text-secondary text-xs">
            {t("integration_problem_last_successful_sync", { time: lastSynced })}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-3 pt-1">
          <span className="text-sm">
            <span className="font-medium">{t("integration_problem_who_fixes")}</span>{" "}
            {t("integration_problem_who_fixes_admin")}
          </span>
          {isAdmin ? (
            <Button
              size="sm"
              variant="primary"
              label={t("integration_problem_open_admin")}
              href={adminIntegrationsUrl}
            />
          ) : (
            <CopyAdminLink url={adminIntegrationsUrl} />
          )}
        </div>
      </div>
    </div>
  );
}

function FailureCard({
  failure,
  showFolders,
  folderLink
}: {
  failure: SyncFailure;
  showFolders: boolean;
  folderLink: (itemId: string) => InPlaceLink;
}) {
  const t = useTranslations();
  const [first] = failure.items;
  return (
    // A card left alone on its row takes the whole row.
    <div className="border-ax-error rounded-ax-container flex gap-3 border p-4 xl:last:odd:col-span-2">
      <ProblemIcon icon={TriangleAlert} tone="error" />
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <h3 className="font-medium">
          {failure.items.length === 1 && first
            ? t("integration_problem_sync_failed_title", { name: folderLabel(first) })
            : t("integration_problem_sync_failed_many_title", { count: failure.items.length })}
        </h3>
        <p className="text-sm">{t("integration_problem_sync_failed_description")}</p>
        {failure.message ? (
          <Collapsible
            trigger={t("integration_problem_technical_details")}
            defaultIsOpen={false}
            chevronPosition="start"
            className={DETAILS_CLASS}
          >
            <p className="text-ax-text-secondary font-mono text-xs break-words">
              {failure.message}
            </p>
          </Collapsible>
        ) : null}
        {showFolders ? (
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {failure.items.map((item) => (
              <li key={item.id}>
                <Link {...folderLink(item.id)} as={SamePageLink} className="font-medium">
                  {t("integration_problem_open_named_folder", { name: folderLabel(item) })}
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </div>
  );
}

function FileGroupRow({
  group,
  isExpanded,
  onToggleExpanded,
  showFolders,
  folderLink
}: {
  group: FileProblemGroup;
  isExpanded: boolean;
  onToggleExpanded: () => void;
  showFolders: boolean;
  folderLink: (itemId: string) => InPlaceLink;
}) {
  const t = useTranslations();
  const meta = CATEGORIES[group.category];
  const count = group.files.length;
  const shown = isExpanded ? group.files : group.files.slice(0, FILES_SHOWN);
  return (
    <Collapsible
      value={group.category}
      className="px-4"
      trigger={
        <span className="flex min-w-0 items-center gap-3">
          <ProblemIcon
            icon={meta.icon}
            tone={group.severity === "fixable" ? "warning" : "neutral"}
          />
          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-ax-text text-sm font-medium">{t(meta.title)}</span>
            <span className="text-ax-text-secondary text-sm font-normal">{t(meta.advice)}</span>
          </span>
          <span className="shrink-0 text-sm font-medium tabular-nums">
            {count === 1
              ? t("integration_problem_files_one")
              : t("integration_problem_files_other", { count })}
          </span>
        </span>
      }
    >
      <div className="flex flex-col items-start gap-2 ps-11 pb-1">
        <ul className="flex w-full flex-col text-sm">
          {/* The same file name recurs across folders, so the key needs the position. */}
          {shown.map((file, index) => (
            <li
              key={`${index}:${file.item.id}:${file.file}`}
              className={cn(
                "border-ax-border grid items-baseline gap-x-6 gap-y-0.5 border-t py-2",
                showFolders
                  ? "lg:grid-cols-[minmax(0,2fr)_minmax(0,2fr)_minmax(0,3fr)]"
                  : "lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]"
              )}
            >
              <span className="min-w-0 font-medium break-all">{file.file}</span>
              {showFolders ? (
                <Link
                  {...folderLink(file.item.id)}
                  as={SamePageLink}
                  color="secondary"
                  className="min-w-0 justify-self-start break-all"
                >
                  {folderLabel(file.item)}
                </Link>
              ) : null}
              <span className="text-ax-text-secondary min-w-0">{file.detail}</span>
            </li>
          ))}
        </ul>
        {count > FILES_SHOWN ? (
          <Button
            variant="ghost"
            size="sm"
            label={
              isExpanded
                ? t("integration_problem_show_fewer")
                : t("integration_problem_show_all", { count })
            }
            onClick={onToggleExpanded}
          />
        ) : null}
      </div>
    </Collapsible>
  );
}

function FileGroups({
  groups,
  openFirst,
  showFolders,
  folderLink
}: {
  groups: FileProblemGroup[];
  openFirst: boolean;
  showFolders: boolean;
  folderLink: (itemId: string) => InPlaceLink;
}) {
  const [expanded, setExpanded] = useState<ReadonlySet<FileProblemCategory>>(new Set());
  const first = groups[0]?.category;
  function toggle(category: FileProblemCategory) {
    setExpanded((current) => {
      const next = new Set(current);
      if (!next.delete(category)) next.add(category);
      return next;
    });
  }
  return (
    <CollapsibleGroup
      type="multiple"
      hasDividers
      density="spacious"
      defaultValue={openFirst && first ? [first] : []}
      className={cn("border-ax-border rounded-ax-container overflow-hidden border", GROUP_CLASS)}
    >
      {groups.map((group) => (
        <FileGroupRow
          key={group.category}
          group={group}
          isExpanded={expanded.has(group.category)}
          onToggleExpanded={() => toggle(group.category)}
          showFolders={showFolders}
          folderLink={folderLink}
        />
      ))}
    </CollapsibleGroup>
  );
}

function fileCount(groups: readonly FileProblemGroup[]): number {
  return groups.reduce((sum, group) => sum + group.files.length, 0);
}

/**
 * What went wrong across a source's items, worst first: what stops the sync
 * (the sign-in, failed syncs), files that can be fixed, files skipped on
 * purpose. `problems` is null while the skipped lists load.
 */
export function ProblemsView({
  problems,
  isAdmin,
  adminIntegrationsUrl,
  folderLink,
  showFolders,
  onRetry
}: {
  problems: SourceProblems | null;
  isAdmin: boolean;
  adminIntegrationsUrl: string;
  /** Opens a folder's contents. */
  folderLink: (itemId: string) => InPlaceLink;
  /** The source has more than one item, so each file names its folder. */
  showFolders: boolean;
  /** Loads the skipped lists again for the items whose list could not be loaded. */
  onRetry: () => void;
}) {
  const t = useTranslations();
  const id = useId();
  const skippedAsOf = useClientTimeText(problems?.skippedAsOf, "date_time");

  if (problems === null) return <LoadingState rows={3} />;

  const blockingCount =
    (problems.credentials ? 1 : 0) +
    problems.failures.reduce((sum, failure) => sum + failure.items.length, 0);
  const fixableCount = fileCount(problems.fixable);
  const intentionalCount = fileCount(problems.intentional);

  if (
    blockingCount === 0 &&
    fixableCount === 0 &&
    intentionalCount === 0 &&
    problems.unavailable.length === 0
  ) {
    return (
      <div className="flex items-center gap-3 py-6">
        <SuccessMark size="lg" />
        <div className="flex flex-col">
          <p className="font-medium">{t("integration_problems_none_title")}</p>
          <p className="text-ax-text-secondary text-sm">
            {t("integration_problems_none_description")}
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {blockingCount > 0 ? (
        <section aria-labelledby={`${id}-blocking`} className="flex flex-col gap-3">
          <h2
            id={`${id}-blocking`}
            className="text-ax-error text-xs font-semibold tracking-wide uppercase"
          >
            {t("integration_problems_blocking_heading", { count: blockingCount })}
          </h2>
          {problems.credentials ? (
            <CredentialsCard
              lastSyncedAt={problems.credentials.lastSyncedAt}
              isAdmin={isAdmin}
              adminIntegrationsUrl={adminIntegrationsUrl}
            />
          ) : null}
          {problems.failures.length > 0 ? (
            <div className="grid gap-3 xl:grid-cols-2">
              {problems.failures.map((failure) => (
                <FailureCard
                  key={failure.message}
                  failure={failure}
                  showFolders={showFolders}
                  folderLink={folderLink}
                />
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {fixableCount > 0 ? (
        <section aria-labelledby={`${id}-fixable`} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <h2
              id={`${id}-fixable`}
              className="text-ax-warning text-xs font-semibold tracking-wide uppercase"
            >
              {t("integration_problems_fixable_heading", { count: fixableCount })}
            </h2>
            {skippedAsOf ? (
              <p className="text-ax-text-secondary text-xs">
                {t("integration_problems_as_of", { time: skippedAsOf })}
              </p>
            ) : null}
          </div>
          <FileGroups
            groups={problems.fixable}
            openFirst
            showFolders={showFolders}
            folderLink={folderLink}
          />
        </section>
      ) : null}

      {intentionalCount > 0 ? (
        <section aria-labelledby={`${id}-intentional`} className="flex flex-col gap-3">
          <h2
            id={`${id}-intentional`}
            className="text-ax-text-secondary text-xs font-semibold tracking-wide uppercase"
          >
            {t("integration_problems_intentional_heading", { count: intentionalCount })}
          </h2>
          <FileGroups
            groups={problems.intentional}
            openFirst={false}
            showFolders={showFolders}
            folderLink={folderLink}
          />
        </section>
      ) : null}

      {problems.notListed > 0 ? (
        <p className="text-ax-text-secondary text-sm italic">
          {t("skipped_and_n_more", { count: problems.notListed })}
        </p>
      ) : null}
      {problems.unavailable.length > 0 ? (
        <div className="text-ax-text-secondary flex flex-wrap items-center gap-3 text-sm">
          <p>
            {t("integration_problems_unavailable", {
              names: problems.unavailable.map((item) => item.name).join(", ")
            })}
          </p>
          <Button
            size="sm"
            label={t("retry")}
            icon={<RefreshCw className="size-4" aria-hidden="true" />}
            onClick={onRetry}
          />
        </div>
      ) : null}
    </div>
  );
}
