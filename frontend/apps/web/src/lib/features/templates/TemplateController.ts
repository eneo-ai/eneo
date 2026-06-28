import { createContext } from "$lib/core/context";
import { m } from "$lib/paraglide/messages";
import { toast } from "$lib/components/toast";
import { toastError } from "$lib/core/errors";
import { type GroupSparse, type TemplateAdditionalField } from "@eneo/eneo-js";
import { derived, get, writable } from "svelte/store";
import { type Attachment } from "../attachments/AttachmentManager";
import type { GenericTemplate, TemplateAdapter } from "./TemplateAdapter";

const [getTemplateController, setTemplateController] =
  createContext<ReturnType<typeof createTemplateController>>();

export { getTemplateController, initTemplateController };

type TemplateControllerParams = {
  adapter: TemplateAdapter;
  allTemplates: GenericTemplate[];
};

function initTemplateController(data: TemplateControllerParams) {
  const instance = createTemplateController(data);
  setTemplateController(instance);
  return instance;
}

function createTemplateController(data: TemplateControllerParams) {
  const { adapter } = data;
  const showTemplateGallery = writable(false);
  const showCreateDialog = writable(false);

  const name = writable("");
  const creationMode = writable<"blank" | "template">("blank");
  const selectedTemplate = writable<GenericTemplate | null>(null);
  const allTemplates: GenericTemplate[] = data.allTemplates;

  const selectedCollections = writable<GroupSparse[]>([]);
  const selectedAttachments = writable<Attachment[]>([]);

  const currentStep = writable<"start" | "wizard">("start");
  const hasWizard = derived(
    [creationMode, selectedTemplate],
    ([$creationMode, $selectedTemplate]) => {
      return (
        $selectedTemplate &&
        $creationMode === "template" &&
        ($selectedTemplate.wizard.attachments || $selectedTemplate.wizard.collections)
      );
    }
  );

  const createButtonLabel = derived(
    [hasWizard, currentStep, creationMode],
    ([$hasWizard, $currentStep, $creationMode]) => {
      if ($creationMode === "blank" || !$hasWizard) {
        return `${m.create()} ${adapter.getResourceName().singular}`;
      }

      return $currentStep === "start"
        ? m.next()
        : `${m.create()} ${adapter.getResourceName().singular}`;
    }
  );

  function selectTemplate(template: GenericTemplate) {
    const $name = get(name);
    const $currentTemplate = get(selectedTemplate);
    if ($name === "" || ($currentTemplate && $name === $currentTemplate.name)) {
      name.set(template.name);
    }
    selectedTemplate.set(template);
    showTemplateGallery.set(false);
  }

  async function createOrContinue({
    onResourceCreated
  }: {
    onResourceCreated: (params: { id: string }) => void;
  }) {
    const $name = get(name);
    const $template = get(selectedTemplate);
    const $creationMode = get(creationMode);
    const $currentStep = get(currentStep);
    const $hasWizard = get(hasWizard);
    const $selectedAttachments = get(selectedAttachments);
    const $selectedCollections = get(selectedCollections);

    if (!$name) return; // no name
    if ($creationMode === "blank") {
      // create blank resource
      try {
        const res = await adapter.createNew({ name: $name });
        onResourceCreated(res);
      } catch (e) {
        toastError(e);
      }
      return;
    }

    if (!$template) return; // no template selected

    if ($hasWizard && $currentStep === "start") {
      currentStep.set("wizard");
      return;
    }

    // do stuff in the wizard
    try {
      // 1. check if required things have been provided
      const additional_fields: TemplateAdditionalField[] = [];

      // Collections wizard: required=true means show picker and send data to backend.
      // Non-required means show hint only, no data sent (backend rejects non-required).
      if ($template.wizard.collections) {
        if ($selectedCollections.length > 0 && $template.wizard.collections.required) {
          additional_fields.push({
            type: "groups",
            value: $selectedCollections.map((collection) => {
              return { id: collection.id };
            })
          });
        } else if ($template.wizard.collections.required && $selectedCollections.length === 0) {
          toast.info(m.template_knowledge_recommendation());
        }
      }

      if ($template.wizard.attachments?.required) {
        const isUploadRunning = $selectedAttachments.some((attachment) => !attachment.fileRef);

        if (isUploadRunning) {
          toast.warning(m.template_uploads_in_progress());
          return;
        }

        if ($selectedAttachments.length > 0) {
          additional_fields.push({
            type: "attachments",
            value: $selectedAttachments.map((attachment) => {
              return { id: attachment.fileRef!.id };
            })
          });
        } else {
          toast.warning(m.template_attachments_required());
          return;
        }
      }

      // 2. create resource
      const res = await adapter.createNew({
        from_template: {
          id: $template.id,
          additional_fields
        },
        name: $name
      });
      selectedAttachments.set([]);
      onResourceCreated(res);
    } catch (e) {
      toastError(e);
    }
  }

  function resetForm() {
    name.set("");
    selectedTemplate.set(null);
    currentStep.set("start");
    creationMode.set("blank");
    selectedCollections.set([]);
    selectedAttachments.update(($attachments) => {
      $attachments.forEach((attachment) => attachment.remove());
      return [];
    });
  }

  return {
    state: {
      name,
      showTemplateGallery,
      showCreateDialog,
      createButtonLabel,
      hasWizard,
      currentStep,
      selectedCollections,
      selectedAttachments,
      creationMode: {
        subscribe: creationMode.subscribe,
        set(value: "blank" | "template") {
          if (value === "template" && get(selectedTemplate) === null) {
            setTimeout(() => {
              showTemplateGallery.set(true);
            }, 0);
          }
          creationMode.set(value);
        }
      },
      selectedTemplate
    },
    get resourceName() {
      return adapter.getResourceName();
    },
    allTemplates,
    getCategorisedTemplates: () => {
      return adapter.getCategorisedTemplates(allTemplates);
    },
    createOrContinue,
    selectTemplate,
    resetForm
  };
}
