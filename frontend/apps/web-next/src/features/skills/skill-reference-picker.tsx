"use client";

import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Item } from "@astryxdesign/core/Item";
import { Badge } from "@astryxdesign/core/Badge";
import { ArrowLeft, ChevronRight, FileText, Plug } from "lucide-react";
import { CAPABILITIES, getCapability } from "@/features/capabilities/capabilities";
import { SKILL_CATALOG_PAGE_SIZE } from "./skill-binding-catalog";
import { Button } from "@astryxdesign/core/Button";
import { Dialog, DialogHeader } from "@astryxdesign/core/Dialog";
import { useAnnounce, useListFocus } from "@astryxdesign/core/hooks";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import {
  readableInstructions,
  referenceUri,
  type ReferenceCandidate,
  type ReferenceCatalog
} from "@eneo/skill-instructions";
import type { ReferenceSelection } from "@eneo/skill-instructions/editor";
import { useEffect, useId, useRef, useState } from "react";
import { useTranslations } from "use-intl";
import { TextInput } from "@/components/astryx/text-input";
import { getErrorMessage } from "@/lib/api/errors";

type Category = "skills" | "functions" | "mcp";
type Props = {
  catalog: ReferenceCatalog;
  selection: ReferenceSelection;
  inline?: boolean;
  onClose: () => void;
  onSelect: (candidate: ReferenceCandidate) => void;
  onRemove: () => void;
};

export function SkillReferencePicker({
  catalog,
  selection,
  inline = false,
  onClose,
  onSelect,
  onRemove
}: Props) {
  const t = useTranslations();
  const announce = useAnnounce();
  const id = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const initialKind = selection.reference?.target.kind;
  const [category, setCategory] = useState<Category>(
    initialKind === "function" ? "functions" : initialKind?.startsWith("mcp") ? "mcp" : "skills"
  );
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [server, setServer] = useState<ReferenceCandidate | null>(null);
  const [selected, setSelected] = useState<ReferenceCandidate | null>(null);
  const [visible, setVisible] = useState(SKILL_CATALOG_PAGE_SIZE);
  const previewHeading = useRef<HTMLHeadingElement>(null);
  const { listRef, handleKeyDown, handleFocus, focusFirst } = useListFocus({
    itemSelector: "[data-reference-option] button",
    onEscape: onClose
  });

  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);
  useEffect(() => {
    queueMicrotask(() => inputRef.current?.focus());
  }, []);
  const serverId = server?.target.kind === "mcp_server" ? server.target.server_id : null;
  const skills = useInfiniteQuery({
    queryKey: ["skill-instruction-catalogue", catalog.key, search],
    queryFn: ({ pageParam, signal }) => catalog.skills(search, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (page) => page.nextCursor,
    enabled: category === "skills",
    retry: false,
    gcTime: 0
  });
  const connections = useQuery({
    queryKey: ["skill-instruction-connections", catalog.key, serverId],
    queryFn: ({ signal }) => (serverId ? catalog.tools(serverId, signal) : catalog.servers(signal)),
    enabled: category === "mcp",
    retry: false,
    gcTime: 0
  });
  const preview = useQuery({
    queryKey: ["skill-instruction-preview", catalog.key, selected && referenceUri(selected.target)],
    queryFn: ({ signal }) => catalog.preview(selected!, signal),
    enabled: selected?.target.kind === "skill",
    retry: false,
    gcTime: 0
  });
  const items: ReferenceCandidate[] =
    category === "skills"
      ? (skills.data?.pages.flatMap((page) => page.items) ?? [])
      : (category === "functions"
          ? CAPABILITIES.map(({ purpose, bundledSummary }) => ({
              label: t(purpose),
              description: bundledSummary ? t(bundledSummary) : "",
              target: { kind: "function" as const, purpose }
            }))
          : (connections.data ?? [])
        ).filter((item) =>
          `${item.label} ${item.description}`
            .toLocaleLowerCase()
            .includes(query.toLocaleLowerCase())
        );
  const loading =
    category === "skills"
      ? skills.isPending || query.trim() !== search
      : category === "mcp" && connections.isPending;
  const error =
    category === "skills" ? skills.error : category === "mcp" ? connections.error : null;
  const canInsert = selected && (selected.target.kind !== "skill" || preview.isSuccess);
  const announcement =
    selected?.target.kind === "skill"
      ? preview.isPending
        ? t("loading")
        : preview.error
          ? getErrorMessage(preview.error, t)
          : t("skills_reference_preview_ready")
      : loading
        ? t("loading")
        : error
          ? getErrorMessage(error, t)
          : items.length === 0
            ? t("skills_reference_empty")
            : "";
  useEffect(() => {
    if (announcement) announce(announcement);
  }, [announce, announcement]);

  function changeCategory(next: Category) {
    setCategory(next);
    setSelected(null);
    setServer(null);
    setQuery("");
    setSearch("");
    setVisible(SKILL_CATALOG_PAGE_SIZE);
    inputRef.current?.focus();
  }

  useEffect(() => {
    if (selected) previewHeading.current?.focus();
  }, [selected]);

  function select(item: ReferenceCandidate) {
    if (item.target.kind === "function" || item.target.kind === "mcp_tool") onSelect(item);
    else setSelected(item);
  }

  return (
    <Dialog
      isOpen
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      isInline={inline}
      width={selected?.target.kind === "skill" ? "42rem" : "32rem"}
      maxHeight="min(48rem, calc(100dvh - 2rem))"
      purpose="form"
    >
      <DialogHeader
        title={t(selection.reference ? "skills_reference_edit" : "skills_reference_insert")}
        onOpenChange={onClose}
      />
      {selected && (
        <div className="border-ax-border flex shrink-0 flex-col gap-3 border-b px-4 pt-3 pb-4">
          <Button
            variant="ghost"
            size="sm"
            className="mr-auto pointer-coarse:min-h-[44px]"
            label={t("skills_reference_back")}
            icon={<ArrowLeft />}
            onClick={() => {
              setSelected(null);
              requestAnimationFrame(() => inputRef.current?.focus());
            }}
          />
          <div className="flex flex-wrap items-center gap-2">
            <h3
              ref={previewHeading}
              tabIndex={-1}
              id={`${id}-preview`}
              className="min-w-0 text-base font-semibold wrap-anywhere outline-none"
            >
              {selected.label}
            </h3>
            {selected.revisionNumber !== undefined && (
              <Badge
                variant="gray"
                label={t("organization_skills_version", {
                  version: String(selected.revisionNumber)
                })}
              />
            )}
          </div>
        </div>
      )}
      <div className="flex min-h-0 flex-col gap-3 overflow-x-hidden overflow-y-auto overscroll-contain p-4">
        {selected ? (
          <>
            <section aria-labelledby={`${id}-preview`} className="flex min-w-0 flex-col gap-3">
              {selected.description &&
                (selected.target.kind === "skill" ? (
                  <details className="text-sm">
                    <summary className="cursor-pointer py-1 font-medium">
                      {t("skills_description_label")}
                    </summary>
                    <p className="mt-2 leading-relaxed wrap-anywhere whitespace-pre-wrap">
                      {selected.description}
                    </p>
                  </details>
                ) : (
                  <p className="text-sm leading-relaxed wrap-anywhere whitespace-pre-wrap">
                    {selected.description}
                  </p>
                ))}
              <p className="text-ax-text-secondary text-sm leading-relaxed">
                {t(
                  selected.target.kind === "skill"
                    ? "skills_reference_fixed_version"
                    : "skills_reference_tools_hint"
                )}
              </p>
              {selected.target.kind === "skill" && (
                <h4 className="text-sm font-medium">{t("skills_instructions_label")}</h4>
              )}
              {selected.target.kind === "skill" ? (
                preview.isPending ? (
                  <p>{t("loading")}</p>
                ) : preview.error ? (
                  <div>
                    <p>{t("skills_reference_preview_failed")}</p>
                    <p>{getErrorMessage(preview.error, t)}</p>
                    <Button label={t("retry")} onClick={() => void preview.refetch()} />
                  </div>
                ) : (
                  <div className="border-ax-border border-b pb-4 text-base leading-7 wrap-anywhere whitespace-pre-wrap">
                    {readableInstructions(preview.data)}
                  </div>
                )
              ) : (
                <>
                  {selected.enabled === false && (
                    <p className="text-ax-text-secondary text-sm">{t("skills_reference_off")}</p>
                  )}
                  <Button
                    label={t("skills_reference_tools")}
                    onClick={() => {
                      setServer(selected);
                      setSelected(null);
                      setQuery("");
                      setVisible(SKILL_CATALOG_PAGE_SIZE);
                      requestAnimationFrame(() => inputRef.current?.focus());
                    }}
                  />
                </>
              )}
              <details className="text-ax-text-secondary text-xs">
                <summary className="cursor-pointer py-1">{t("skills_reference_details")}</summary>
                <code className="break-all">{referenceUri(selected.target)}</code>
              </details>
            </section>
          </>
        ) : (
          <>
            <SegmentedControl
              value={category}
              onChange={(value) => changeCategory(value as Category)}
              label={t("skills_reference_insert")}
              layout="fill"
            >
              <SegmentedControlItem value="skills" label={t("skills")} />
              <SegmentedControlItem value="functions" label={t("skills_reference_functions")} />
              <SegmentedControlItem value="mcp" label={t("skills_reference_mcps")} />
            </SegmentedControl>
            {server && (
              <Button
                variant="ghost"
                size="sm"
                className="mr-auto"
                label={server.label}
                icon={<ArrowLeft />}
                onClick={() => {
                  setServer(null);
                  setQuery("");
                }}
              />
            )}
            <TextInput
              htmlName="reference-search"
              autoComplete="off"
              ref={inputRef}
              label={t("skills_reference_search")}
              value={query}
              onChange={(value) => {
                setQuery(value);
                setVisible(SKILL_CATALOG_PAGE_SIZE);
              }}
              onKeyDown={(event) => {
                if (event.key === "ArrowDown" && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  focusFirst();
                }
              }}
            />
            {loading ? (
              <p className="text-ax-text-secondary text-sm">{t("loading")}</p>
            ) : error ? (
              <div>
                <p>{getErrorMessage(error, t)}</p>
                <Button
                  label={t("retry")}
                  onClick={() =>
                    void (category === "skills" ? skills.refetch() : connections.refetch())
                  }
                />
              </div>
            ) : (
              <section
                role="group"
                aria-label={t("skills_reference_search")}
                className="flex max-h-64 flex-col gap-1 overflow-y-auto"
                ref={listRef}
              >
                {items.length === 0 && (
                  <p className="text-ax-text-secondary p-3 text-sm">
                    {t("skills_reference_empty")}
                  </p>
                )}
                {items.slice(0, category === "skills" ? items.length : visible).map((item) => {
                  const Icon =
                    item.target.kind === "function"
                      ? getCapability(item.target.purpose)!.icon
                      : item.target.kind === "skill"
                        ? FileText
                        : Plug;
                  return (
                    <Item
                      key={referenceUri(item.target)}
                      data-reference-option
                      className="min-w-0 [overflow-wrap:anywhere]"
                      label={item.label}
                      description={
                        item.enabled === false
                          ? t("skills_reference_off")
                          : item.description || undefined
                      }
                      labelLines={2}
                      descriptionLines={2}
                      density="balanced"
                      startContent={<Icon className="size-4" aria-hidden="true" />}
                      endContent={
                        <span className="text-ax-text-secondary flex items-center gap-2 text-xs">
                          {item.revisionNumber !== undefined && (
                            <span>
                              {t("skills_reference_version_short", {
                                version: item.revisionNumber
                              })}
                            </span>
                          )}
                          {(item.target.kind === "skill" || item.target.kind === "mcp_server") && (
                            <ChevronRight className="size-4" aria-hidden="true" />
                          )}
                        </span>
                      }
                      onKeyDown={handleKeyDown}
                      onFocus={handleFocus}
                      onClick={() => select(item)}
                    />
                  );
                })}
              </section>
            )}
            {category === "skills" && skills.hasNextPage && (
              <Button
                variant="ghost"
                label={t("load_more")}
                isLoading={skills.isFetchingNextPage}
                isInterruptible
                onClick={() => {
                  if (!skills.isFetching) void skills.fetchNextPage();
                }}
              />
            )}
            {category !== "skills" && visible < items.length && (
              <Button
                variant="ghost"
                label={t("load_more")}
                onClick={() => setVisible((count) => count + SKILL_CATALOG_PAGE_SIZE)}
              />
            )}
            <p className="text-ax-text-secondary text-xs leading-5">
              {t(category === "skills" ? "skills_reference_scope" : "skills_reference_tools_hint")}
            </p>
          </>
        )}
      </div>
      <div className="border-ax-border flex shrink-0 flex-wrap justify-end gap-2 border-t p-3">
        {selection.reference && (
          <Button
            label={t("skills_reference_remove")}
            variant="ghost"
            className="mr-auto"
            onClick={onRemove}
          />
        )}
        <Button label={t("cancel")} onClick={onClose} />
        {selected && (
          <Button
            label={t(
              selected.target.kind === "mcp_server"
                ? "skills_reference_whole_mcp"
                : "skills_reference_insert"
            )}
            variant="primary"
            isDisabled={!canInsert}
            onClick={() => {
              if (canInsert) onSelect(selected);
            }}
          />
        )}
      </div>
    </Dialog>
  );
}
