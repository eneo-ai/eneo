import type { FlowStep, UploadedFile } from "@eneo/eneo-js";
import type { FlowEditor } from "$lib/features/flows/FlowEditor";
import type { Eneo } from "@eneo/eneo-js";
import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
import type { Attachment } from "$lib/features/attachments/AttachmentManager";
import { SvelteMap, SvelteSet } from "svelte/reactivity";
import type { Readable, Writable } from "svelte/store";

export type LoadedAssistant = NonNullable<Awaited<ReturnType<FlowEditor["loadAssistant"]>>>;
export type PromptGuideAvailability = Awaited<
  ReturnType<Eneo["helpAssistants"]["runs"]["availability"]>
>;

/**
 * Manages the assistant lifecycle for the active flow step:
 * loading, saving fields, attachment management, and cleanup.
 */
export class FlowStepAssistantState {
  #flowEditor: FlowEditor;
  #eneo: Eneo;
  #attachmentRules: Writable<Record<string, unknown>>;
  #newAttachments: Readable<Attachment[]>;
  #clearUploads: () => void;
  #getActiveStep: () => FlowStep | null;

  assistant = $state<LoadedAssistant | null>(null);
  loading = $state(false);
  promptGuideAvailability = $state<PromptGuideAvailability | null>(null);

  #lastLoadedId: string | null = null;
  #lastLoadedRevision = -1;
  #loadRequestToken = 0;
  #autoClearedLegacyTemplateByStepId = new SvelteSet<string>();
  #promptGuideAvailabilityByAssistantId = new SvelteMap<string, PromptGuideAvailability | null>();

  runningUploads = $derived(
    (this.#getNewAttachments() ?? []).filter(
      (attachment: { status: string }) => attachment.status !== "completed"
    )
  );

  constructor(opts: {
    flowEditor: FlowEditor;
    eneo: Eneo;
    attachmentRules: Writable<Record<string, unknown>>;
    newAttachments: Readable<Attachment[]>;
    clearUploads: () => void;
    getActiveStep: () => FlowStep | null;
  }) {
    this.#flowEditor = opts.flowEditor;
    this.#eneo = opts.eneo;
    this.#attachmentRules = opts.attachmentRules;
    this.#newAttachments = opts.newAttachments;
    this.#clearUploads = opts.clearUploads;
    this.#getActiveStep = opts.getActiveStep;
  }

  #getNewAttachments() {
    let value: Attachment[] = [];
    this.#newAttachments.subscribe((v) => (value = v))();
    return value;
  }

  cancelUploadsAndClearQueue() {
    this.#getNewAttachments().forEach((upload: { status: string; remove: () => void }) => {
      if (upload.status !== "completed") {
        upload.remove();
      }
    });
    this.#clearUploads();
  }

  async load(assistantId: string) {
    if (!assistantId) return;
    const requestToken = ++this.#loadRequestToken;
    this.loading = true;
    this.#lastLoadedId = assistantId;
    try {
      const loaded = await this.#flowEditor.loadAssistant(assistantId);
      if (requestToken !== this.#loadRequestToken) return;
      const activeStep = this.#getActiveStep();
      if (activeStep?.assistant_id !== assistantId) return;
      this.assistant = loaded;
      void this.#loadPromptGuideAvailability(assistantId, requestToken);
    } catch (error) {
      if (requestToken !== this.#loadRequestToken) return;
      console.error("Failed to load assistant for flow step:", error);
      this.assistant = null;
    } finally {
      if (requestToken === this.#loadRequestToken) {
        this.loading = false;
      }
    }
  }

  async #loadPromptGuideAvailability(assistantId: string, requestToken: number) {
    let availability = this.#promptGuideAvailabilityByAssistantId.get(assistantId);
    if (availability === undefined) {
      try {
        availability = await this.#eneo.helpAssistants.runs.availability({
          kind: "prompt_guide",
          target_id: assistantId
        });
      } catch {
        availability = null;
      }
      this.#promptGuideAvailabilityByAssistantId.set(assistantId, availability);
    }
    if (requestToken !== this.#loadRequestToken) return;
    if (this.#getActiveStep()?.assistant_id !== assistantId) return;
    this.promptGuideAvailability = availability;
  }

  updateField(field: string, value: unknown) {
    this.updateFields({ [field]: value });
  }

  updateFields(changes: Record<string, unknown>, opts?: { immediate?: boolean }) {
    const activeStep = this.#getActiveStep();
    if (!activeStep?.assistant_id) return;
    const loadedAssistantId =
      this.assistant && typeof (this.assistant as { id?: unknown }).id === "string"
        ? (this.assistant as { id: string }).id
        : null;
    if (loadedAssistantId !== null && loadedAssistantId !== activeStep.assistant_id) return;
    if (this.assistant) {
      this.assistant = { ...this.assistant, ...changes };
    }
    if (opts?.immediate) {
      void this.#flowEditor.updateAssistantImmediately(activeStep.assistant_id, changes);
      return;
    }
    void this.#flowEditor.saveAssistant(activeStep.assistant_id, changes);
  }

  onFileUploaded(newFile: UploadedFile) {
    if (!this.assistant) return;
    const currentAttachments = Array.isArray(this.assistant.attachments)
      ? this.assistant.attachments
      : [];
    if (currentAttachments.some((file: UploadedFile) => file.id === newFile.id)) return;
    this.updateField("attachments", [...currentAttachments, newFile]);
  }

  async removeAttachment(file: { id: string }) {
    if (!this.assistant) return;
    const uploadStillQueued = this.#getNewAttachments().find(
      (attachment: { fileRef?: { id: string } }) =>
        attachment.fileRef && attachment.fileRef.id === file.id
    );
    if (uploadStillQueued) {
      try {
        await this.#eneo.files.delete({ fileId: file.id });
      } catch (error) {
        console.error("Failed to delete newly uploaded attachment file", error);
      }
    }
    const currentAttachments = Array.isArray(this.assistant.attachments)
      ? this.assistant.attachments
      : [];
    this.updateField(
      "attachments",
      currentAttachments.filter((attachment: UploadedFile) => attachment.id !== file.id)
    );
  }

  /** Sync attachment rules when assistant changes */
  syncAttachmentRules() {
    const allowed = this.assistant?.allowed_attachments;
    if (allowed) {
      this.#attachmentRules.set(getExplicitAttachmentRules(allowed));
    } else {
      this.#attachmentRules.set({});
    }
  }

  /** React to active step changes — load, unload, or switch assistant */
  syncWithActiveStep(activeStep: FlowStep | null, revision = 0) {
    if (activeStep?.output_mode === "template_fill") {
      this.assistant = null;
      this.#lastLoadedId = null;
      this.#lastLoadedRevision = revision;
      this.loading = false;
      this.promptGuideAvailability = null;
      this.cancelUploadsAndClearQueue();
    } else if (
      activeStep?.assistant_id &&
      (activeStep.assistant_id !== this.#lastLoadedId || revision !== this.#lastLoadedRevision)
    ) {
      const targetId = activeStep.assistant_id;
      this.#lastLoadedId = targetId;
      this.#lastLoadedRevision = revision;
      this.assistant = null;
      this.promptGuideAvailability = null;
      this.loading = true;
      this.cancelUploadsAndClearQueue();
      void (async () => {
        await this.#flowEditor.flushAssistantSaves().catch(() => {});
        if (this.#getActiveStep()?.assistant_id !== targetId) return;
        await this.load(targetId);
      })();
    } else if (!activeStep || !activeStep.assistant_id) {
      this.assistant = null;
      this.promptGuideAvailability = null;
      this.#lastLoadedId = null;
      this.#lastLoadedRevision = revision;
      this.loading = false;
      this.cancelUploadsAndClearQueue();
    }
  }

  /** Cleanup on destroy */
  destroy() {
    this.cancelUploadsAndClearQueue();
    void this.#flowEditor.flushAssistantSaves().catch(() => {});
  }

  get autoClearedLegacyTemplateByStepId() {
    return this.#autoClearedLegacyTemplateByStepId;
  }
}
