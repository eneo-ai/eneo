import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { IconButton } from "@astryxdesign/core/IconButton";
import { pixel, proportional, type TableColumn } from "@astryxdesign/core/Table";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { queryOptions, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy } from "lucide-react";
import { useTranslations } from "use-intl";
import { useId, useRef, useState } from "react";
import { KEYBOARD } from "@/components/astryx/keyboard-hints";
import { Table } from "@/components/astryx/table";
import { TextInput } from "@/components/astryx/text-input";
import { ClientTime } from "@/components/composites/client-time";
import { ConfirmDialogControlled } from "@/components/composites/confirm-dialog";
import { revealProblems } from "@/components/composites/field-problem";
import { QueryStateBoundary } from "@/components/composites/query-state";
import { SecretRevealDialog } from "@/components/composites/secret-reveal";
import { TableFrame } from "@/components/composites/table-frame";
import { browserApi, type EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";
import { toastApiError } from "@/lib/api/toast";
import { useCopy } from "@/lib/hooks/use-copy";
import { toast } from "@/lib/toast";
import { useRemovalMutation } from "@/features/spaces/removal";

export type ConnectedSystem = Schema<"ConnectorInstallationPublic">;

export const CONNECTED_SYSTEMS_KEY = ["admin-connected-systems"];

export function connectedSystemsQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: CONNECTED_SYSTEMS_KEY,
    queryFn: async (): Promise<ConnectedSystem[]> => {
      const page = await unwrap(api.GET("/api/v1/admin/connector-installations/"));
      return page.items;
    }
  });
}

/** What the administrator of the other system registers as Eneo's address. */
function connectorAddress(): string {
  return new URL("/api/v1/connector", window.location.origin).toString();
}

/**
 * Whether the form sends the address on. https everywhere; plain http only
 * when Eneo itself is opened over http, which is a development setup. The
 * backend decides either way: outside development it refuses http, and in
 * development it takes http only for this machine.
 */
function isUsableAddress(address: string): boolean {
  return (
    address.startsWith("https://") ||
    (window.location.protocol === "http:" && address.startsWith("http://"))
  );
}

/** Eneo's own address for the other system, always in view: it is no secret. */
function ConnectorAddress() {
  const t = useTranslations();
  const { copy, isCopied } = useCopy();
  const address = connectorAddress();
  const labelId = useId();
  return (
    <div className="flex flex-col gap-1">
      <span id={labelId} className="text-sm font-medium">
        {t("connected_systems_eneo_address")}
      </span>
      <div className="flex items-start gap-2">
        <code
          aria-labelledby={labelId}
          className="bg-ax-muted rounded-ax-inner min-w-0 flex-1 px-3 py-2 font-mono text-sm break-all select-all"
        >
          {address}
        </code>
        <IconButton
          label={t("connected_systems_copy_address")}
          tooltip={t("connected_systems_copy_address")}
          icon={isCopied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          onClick={() => void copy(address)}
        />
      </div>
    </div>
  );
}

/**
 * Name and address of a system to add. The shared key in the answer goes to
 * `onKey` for the one-time dialog and never into React Query's cache.
 */
function AddSystemForm({ onKey }: { onKey: (name: string, key: string) => void }) {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [address, setAddress] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);
  const addressRef = useRef<HTMLInputElement>(null);
  const problems = {
    name: name.trim() ? null : t("required_field"),
    address: isUsableAddress(address.trim()) ? null : t("connected_systems_address_https")
  };

  const add = useMutation({
    mutationFn: async (body: { name: string; base_url: string }) => {
      const { key, ...system } = await unwrap(
        browserApi.POST("/api/v1/admin/connector-installations/", { body })
      );
      onKey(system.name, key);
      return system;
    },
    onSuccess: () => {
      setName("");
      setAddress("");
      setSubmitted(false);
      void queryClient.invalidateQueries({ queryKey: CONNECTED_SYSTEMS_KEY });
    },
    onError: (error) => toastApiError(error, t)
  });

  function submit(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    if (add.isPending) return;
    if (problems.name || problems.address) {
      revealProblems(
        () => setSubmitted(true),
        problems.name ? nameRef.current : addressRef.current
      );
      return;
    }
    add.mutate({ name: name.trim(), base_url: address.trim() });
  }

  return (
    <form onSubmit={submit} noValidate className="flex flex-col gap-4">
      <TextInput
        ref={nameRef}
        label={t("name")}
        value={name}
        onChange={setName}
        isRequired
        maxLength={120}
        autoComplete="off"
        status={submitted && problems.name ? { type: "error", message: problems.name } : undefined}
        width="100%"
      />
      <TextInput
        ref={addressRef}
        label={t("connected_systems_address")}
        description={t("connected_systems_address_help")}
        value={address}
        onChange={setAddress}
        isRequired
        autoComplete="off"
        {...KEYBOARD.identifier}
        status={
          submitted && problems.address ? { type: "error", message: problems.address } : undefined
        }
        width="100%"
      />
      <div>
        <Button
          type="submit"
          variant="primary"
          label={t("connected_systems_add")}
          isLoading={add.isPending}
          isInterruptible
        />
      </div>
    </form>
  );
}

/**
 * The systems the organisation lets call Eneo for its people: each lists and
 * asks the assistants made available to other clients, as the person signed
 * in there. Adding one shows its shared key once; removing one refuses the key
 * from the next call on.
 */
export function ConnectedSystemsSection() {
  const t = useTranslations();
  const queryClient = useQueryClient();
  const headingId = useId();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const systems = useQuery(connectedSystemsQueryOptions(browserApi));
  const [removing, setRemoving] = useState<ConnectedSystem | null>(null);
  // The title stays after closing, so the closing dialog keeps its name.
  const [revealed, setRevealed] = useState<{ name: string; key: string | null }>({
    name: "",
    key: null
  });

  const remove = useRemovalMutation({
    mutationFn: (system: ConnectedSystem) =>
      unwrap(
        browserApi.DELETE("/api/v1/admin/connector-installations/{id}/", {
          params: { path: { id: system.id } }
        })
      ),
    refresh: () => queryClient.invalidateQueries({ queryKey: CONNECTED_SYSTEMS_KEY }),
    onRemoved: (_data, system) => {
      setRemoving(null);
      toast.success(t("connected_systems_removed", { name: system.name }));
    },
    focusTarget: headingRef
  });

  const columns: TableColumn<ConnectedSystem>[] = [
    {
      key: "name",
      header: t("name"),
      width: proportional(1, { minWidth: 140 }),
      renderCell: (system) => <span className="font-medium break-words">{system.name}</span>
    },
    {
      key: "base_url",
      header: t("connected_systems_address"),
      width: proportional(2, { minWidth: 200 }),
      renderCell: (system) => <span className="break-all">{system.base_url}</span>
    },
    {
      key: "created_at",
      header: t("created"),
      width: pixel(150),
      renderCell: (system) =>
        system.created_at ? <ClientTime value={system.created_at} format="date" /> : "—"
    },
    {
      key: "actions",
      header: <VisuallyHidden>{t("actions")}</VisuallyHidden>,
      width: pixel(120),
      align: "end",
      renderCell: (system) => (
        <Button
          variant="secondary"
          size="sm"
          label={t("remove")}
          aria-label={t("connected_systems_remove_named", { name: system.name })}
          onClick={() => setRemoving(system)}
        />
      )
    }
  ];

  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <h2 id={headingId} ref={headingRef} tabIndex={-1} className="font-semibold">
          {t("connected_systems_title")}
        </h2>
        <p className="text-ax-text-secondary text-sm">{t("connected_systems_description")}</p>
      </div>

      <QueryStateBoundary
        query={systems}
        rows={1}
        loadingLabel={t("loading")}
        errorTitle={t("connected_systems_load_failed")}
      >
        {(listed) =>
          listed.length > 0 ? (
            <TableFrame>
              <Table
                data={listed}
                columns={columns}
                idKey="id"
                aria-labelledby={headingId}
                pinnedColumn="name"
              />
            </TableFrame>
          ) : (
            <p className="text-ax-text-secondary text-sm">{t("connected_systems_empty")}</p>
          )
        }
      </QueryStateBoundary>

      <Card padding={4} className="flex flex-col gap-4">
        <ConnectorAddress />
        <AddSystemForm onKey={(name, key) => setRevealed({ name, key })} />
      </Card>

      <SecretRevealDialog
        title={t("connected_systems_added_title", { name: revealed.name })}
        secret={revealed.key}
        warning={t("connected_systems_key_warning")}
        copyFailedMessage={t("connected_systems_key_copy_failed")}
        onClose={() => setRevealed((current) => ({ ...current, key: null }))}
      />
      <ConfirmDialogControlled
        open={removing !== null}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title={t("connected_systems_remove_title", { name: removing?.name ?? "" })}
        description={t("connected_systems_remove_description")}
        confirmLabel={remove.isPending ? t("removing") : t("remove")}
        pending={remove.isPending}
        onConfirm={() => {
          if (removing) remove.mutate(removing);
        }}
      />
    </section>
  );
}
