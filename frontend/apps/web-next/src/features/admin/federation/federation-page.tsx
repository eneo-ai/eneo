"use client";

import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Heading } from "@astryxdesign/core/Heading";
import { useAnnounce } from "@astryxdesign/core/hooks";
import { MetadataList, MetadataListItem } from "@astryxdesign/core/MetadataList";
import { Text } from "@astryxdesign/core/Text";
import { TextArea } from "@astryxdesign/core/TextArea";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useRef, useState, type SubmitEvent } from "react";
import { TextInput } from "@/components/astryx/text-input";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { EmptyState } from "@/components/composites/empty-state";
import { revealProblems } from "@/components/composites/field-problem";
import { PageHeader } from "@/components/composites/page-header";
import { ListError, QueryStateBoundary } from "@/components/composites/query-state";
import { browserApi } from "@/lib/api/browser";
import { EneoApiError } from "@/lib/api/errors";
import { useFocusRescue } from "@/lib/focus-rescue";
import { ClientSecretField } from "./client-secret-field";
import {
  FEDERATION_KEY,
  federationErrorKey,
  federationQueryOptions,
  patchFederation,
  type FederationPatch,
  type FederationView
} from "./federation";
import {
  changedFields,
  draftFromView,
  FEDERATION_FIELDS,
  parseDomains,
  toPatch,
  validate,
  type FederationDraft,
  type FederationField
} from "./federation-draft";
import { RedirectUris } from "./redirect-uris";

// A wrong value here locks every SSO user out; a label is only a label.
const RISKY: ReadonlySet<FederationField> = new Set([
  "client_id",
  "client_secret",
  "allowed_domains"
]);

const CARD = "bg-ax-card border-ax-border rounded-ax-container border";

/**
 * The organisation's sign-in (SSO) settings for its admins. The operator
 * registers the identity provider; here an admin reads it, copies the
 * redirect URIs and changes the label, client ID, secret and allowed domains
 * in one confirmed save (no autosave: an IdP change is applied atomically).
 */
export function FederationPage() {
  const t = useTranslations();
  const query = useQuery(federationQueryOptions(browserApi));
  const disabled =
    query.error instanceof EneoApiError && query.error.reason === "federation_disabled";

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-6">
      <PageHeader
        title={t("federation_admin_title")}
        description={t("federation_admin_description")}
      />
      {disabled ? (
        <NotConfigured />
      ) : (
        <QueryStateBoundary
          query={query}
          rows={6}
          loadingLabel={t("federation_admin_loading")}
          errorTitle={t("federation_admin_load_error")}
        >
          {(view) =>
            view.configured ? (
              <FederationForm
                view={view}
                reload={async () => {
                  // A failed refetch keeps the cached (stale) data: no reload.
                  const result = await query.refetch();
                  return result.isSuccess ? result.data : undefined;
                }}
              />
            ) : (
              <NotConfigured />
            )
          }
        </QueryStateBoundary>
      )}
    </div>
  );
}

function NotConfigured() {
  const t = useTranslations();
  return (
    <EmptyState
      icon={<KeyRound />}
      title={t("federation_admin_not_configured_title")}
      description={t("federation_admin_not_configured_description")}
    />
  );
}

function OperatorOwned({ view }: { view: FederationView }) {
  const t = useTranslations();
  const headingId = useId();
  return (
    <section aria-labelledby={headingId} className={CARD}>
      <div className="border-ax-border flex flex-col gap-1 border-b px-5 py-4">
        <Heading level={2} id={headingId} className="text-base">
          {t("federation_admin_operator_owned")}
        </Heading>
        <Text type="supporting">{t("federation_admin_operator_owned_help")}</Text>
      </div>
      <div className="px-5 py-4">
        <MetadataList label={{ position: "top" }}>
          <MetadataListItem label={t("federation_admin_discovery")}>
            <span className="break-all">{view.discovery_endpoint ?? "—"}</span>
          </MetadataListItem>
          <MetadataListItem label={t("federation_admin_issuer")}>
            <span className="break-all">{view.issuer ?? "—"}</span>
          </MetadataListItem>
          <MetadataListItem label={t("federation_admin_redirects")}>
            <RedirectUris
              uris={view.redirect_uris ?? []}
              unavailable={view.redirect_uris_problem != null}
            />
          </MetadataListItem>
          <MetadataListItem label={t("federation_admin_scopes")}>
            {(view.scopes ?? []).join(" ") || "—"}
          </MetadataListItem>
          <MetadataListItem label={t("federation_admin_token_auth")}>
            {view.token_endpoint_auth_method ?? "—"}
          </MetadataListItem>
        </MetadataList>
      </div>
    </section>
  );
}

function FederationForm({
  view,
  reload
}: {
  view: FederationView;
  /** Reads the settings again: another admin's values after a conflict. */
  reload: () => Promise<FederationView | undefined>;
}) {
  const t = useTranslations();
  const announce = useAnnounce();
  const queryClient = useQueryClient();
  const headingId = useId();
  // The settings the draft was made from; a background refetch does not
  // replace what the admin is editing (a stale save answers 409 instead).
  const [base, setBase] = useState(view);
  const [draft, setDraft] = useState<FederationDraft>(() => draftFromView(view));
  const [submitted, setSubmitted] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [conflict, setConflict] = useState(false);
  const [reloading, setReloading] = useState(false);
  const [saveError, setSaveError] = useState<unknown>(null);
  const [serverProblems, setServerProblems] = useState<Partial<Record<FederationField, string>>>(
    {}
  );
  const providerRef = useRef<HTMLInputElement>(null);
  const clientIdRef = useRef<HTMLInputElement>(null);
  const secretRef = useRef<HTMLInputElement>(null);
  const domainsRef = useRef<HTMLTextAreaElement>(null);
  const replaceSecretRef = useRef<HTMLButtonElement>(null);
  const rescueFocus = useFocusRescue();
  // The body holds the secret, so it is never the mutation's variables
  // (React Query keeps those in its cache); it lives here until settled.
  const pendingBody = useRef<FederationPatch | null>(null);

  const changed = changedFields(base, draft);
  const problems = validate(draft);
  const problemFor = (field: FederationField) => {
    const own = submitted ? problems[field] : undefined;
    if (own) return t(own.key, own.values);
    return serverProblems[field] ?? null;
  };
  const status = (field: FederationField) => {
    const problem = problemFor(field);
    return problem ? { type: "error" as const, message: problem } : undefined;
  };

  function edit(field: FederationField, changes: Partial<FederationDraft>) {
    setDraft((current) => ({ ...current, ...changes }));
    setServerProblems((current) => {
      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  function startFrom(next: FederationView) {
    setBase(next);
    setDraft(draftFromView(next));
    setSubmitted(false);
    setServerProblems({});
    setSaveError(null);
  }

  const save = useMutation({
    mutationFn: () => patchFederation(browserApi, pendingBody.current!),
    onSettled: () => {
      pendingBody.current = null;
    },
    onSuccess: (saved) => {
      queryClient.setQueryData(FEDERATION_KEY, saved);
      void queryClient.invalidateQueries({ queryKey: FEDERATION_KEY });
      startFrom(saved);
      setConfirming(false);
      // A save from the secret field removes it; the dialog's focus return
      // then has nothing to go to. "Byt hemlighet" stands in its place.
      rescueFocus(() => replaceSecretRef.current);
      announce(t("federation_admin_saved"));
    },
    onError: (error) => {
      setConfirming(false);
      const reason = error instanceof EneoApiError ? error.reason : undefined;
      if (reason === "federation_config_revision_conflict") {
        setConflict(true);
        return;
      }
      if (reason === "federation_not_configured") {
        void queryClient.invalidateQueries({ queryKey: FEDERATION_KEY });
        return;
      }
      const fieldProblems = serverFieldProblems(error, t);
      if (fieldProblems) {
        setServerProblems(fieldProblems);
        announce(Object.values(fieldProblems).join(" "));
        return;
      }
      setSaveError(error);
    }
  });

  function requestSave(event: SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    // Never disabled: the dialog returns focus here after a save, and a
    // disabled button would drop it to the page. Nothing changed, nothing to do.
    if (save.isPending || changed.length === 0) return;
    const first = FEDERATION_FIELDS.find((field) => problems[field]);
    if (first) {
      const fieldRef = {
        provider: providerRef,
        client_id: clientIdRef,
        client_secret: secretRef,
        allowed_domains: domainsRef
      }[first];
      revealProblems(() => setSubmitted(true), fieldRef.current);
      return;
    }
    setSaveError(null);
    setConfirming(true);
  }

  async function reloadAfterConflict() {
    if (reloading) return;
    setReloading(true);
    try {
      const latest = await reload();
      if (latest) {
        startFrom(latest);
        setConflict(false);
        providerRef.current?.focus();
      }
    } finally {
      setReloading(false);
    }
  }

  const changeLines = changed.map((field) => changeLine(field, base, draft, t));

  return (
    <>
      <OperatorOwned view={base} />
      <section aria-labelledby={headingId} className={CARD}>
        <div className="border-ax-border flex flex-col gap-1 border-b px-5 py-4">
          <Heading level={2} id={headingId} className="text-base">
            {t("federation_admin_editable")}
          </Heading>
        </div>
        <form className="flex flex-col gap-5 px-5 py-4" noValidate onSubmit={requestSave}>
          {conflict ? (
            <Banner
              status="warning"
              title={t("federation_admin_conflict_title")}
              description={t("federation_admin_conflict_description")}
              endContent={
                <Button
                  size="sm"
                  label={t("federation_admin_conflict_reload")}
                  isLoading={reloading}
                  isInterruptible
                  onClick={() => void reloadAfterConflict()}
                />
              }
            />
          ) : null}
          <TextInput
            ref={providerRef}
            label={t("federation_admin_provider_label")}
            value={draft.provider}
            onChange={(provider) => edit("provider", { provider })}
            autoComplete="off"
            isRequired
            status={status("provider")}
          />
          <TextInput
            ref={clientIdRef}
            label={t("client_id")}
            value={draft.clientId}
            onChange={(clientId) => edit("client_id", { clientId })}
            autoComplete="off"
            isRequired
            status={status("client_id")}
          />
          <ClientSecretField
            view={base}
            secret={draft.secret}
            onSecretChange={(secret) => edit("client_secret", { secret })}
            problem={problemFor("client_secret")}
            inputRef={secretRef}
            replaceRef={replaceSecretRef}
          />
          <TextArea
            ref={domainsRef}
            label={t("federation_admin_domains")}
            description={t("federation_admin_domains_help")}
            value={draft.domains}
            onChange={(domains) => edit("allowed_domains", { domains })}
            rows={4}
            hasSpellCheck={false}
            status={status("allowed_domains")}
          />
          {saveError != null ? <SaveError error={saveError} /> : null}
          <Button
            type="submit"
            variant="primary"
            label={t("save_changes")}
            className="self-start"
            isLoading={save.isPending}
            isInterruptible
          />
        </form>
      </section>
      <ConfirmDialogControlled
        open={confirming}
        onOpenChange={setConfirming}
        title={t("federation_admin_confirm_title")}
        description={t("federation_admin_confirm_description")}
        confirmLabel={t("federation_admin_confirm_action")}
        variant={changed.some((field) => RISKY.has(field)) ? "destructive" : "default"}
        pending={save.isPending}
        onConfirm={() => {
          if (save.isPending) return;
          pendingBody.current = toPatch(base, draft);
          save.mutate();
        }}
      >
        <div className="flex flex-col gap-2">
          <Text weight="semibold">{t("federation_admin_confirm_changes")}</Text>
          <ul className="list-disc space-y-1 pl-6 text-sm">
            {changeLines.map((line) => (
              <li key={line} className="break-words">
                {line}
              </li>
            ))}
          </ul>
          <Text type="supporting">{t("federation_admin_confirm_recovery")}</Text>
        </div>
      </ConfirmDialogControlled>
    </>
  );
}

/** A failed save: the page's own words for a refusal it knows, else the catalog's. */
function SaveError({ error }: { error: unknown }) {
  const t = useTranslations();
  const known = federationErrorKey(error instanceof EneoApiError ? error.reason : undefined);
  return known ? (
    <ListError error={null} title={t(known)} />
  ) : (
    <ListError error={error} title={t("federation_admin_save_error")} />
  );
}

type Translate = ReturnType<typeof useTranslations>;

const FIELD_LABEL_KEYS: Record<FederationField, string> = {
  provider: "federation_admin_provider_label",
  client_id: "client_id",
  client_secret: "client_secret",
  allowed_domains: "federation_admin_domains"
};

/** One line of the confirmation: the setting from what to what; never the secret. */
function changeLine(
  field: FederationField,
  base: FederationView,
  draft: FederationDraft,
  t: Translate
): string {
  if (field === "client_secret") return t("federation_admin_secret_replaced_change");
  const list = (values: string[]) => values.join(", ") || t("federation_admin_none");
  const [from, to] =
    field === "provider"
      ? [base.provider ?? "", draft.provider.trim()]
      : field === "client_id"
        ? [base.client_id ?? "", draft.clientId.trim()]
        : [list(base.allowed_domains ?? []), list(parseDomains(draft.domains))];
  return t("federation_admin_change", {
    field: t(FIELD_LABEL_KEYS[field]),
    from: from || t("federation_admin_none"),
    to: to || t("federation_admin_none")
  });
}

/**
 * A refusal that belongs at a field: the masked-looking secret, or a 422
 * naming body fields. null for anything else (shown with ListError).
 */
function serverFieldProblems(
  error: unknown,
  t: Translate
): Partial<Record<FederationField, string>> | null {
  if (!(error instanceof EneoApiError)) return null;
  if (error.reason === "federation_secret_looks_masked") {
    return { client_secret: t("federation_admin_secret_masked") };
  }
  if (error.status !== 422 || !Array.isArray(error.details)) return null;
  const problems: Partial<Record<FederationField, string>> = {};
  for (const entry of error.details as { loc?: unknown[] }[]) {
    const field = entry.loc?.[1];
    if (typeof field === "string" && (FEDERATION_FIELDS as readonly string[]).includes(field)) {
      problems[field as FederationField] = t("federation_admin_field_refused");
    }
  }
  return Object.keys(problems).length > 0 ? problems : null;
}
