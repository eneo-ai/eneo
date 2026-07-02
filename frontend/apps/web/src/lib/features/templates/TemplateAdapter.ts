import type { AppTemplate, AssistantTemplate, Eneo, JSONRequestBody } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import {
  appTemplateCategories,
  assistantTemplateCategories,
  getCategoryInfo
} from "./TemplateCategories";

type CommonKeys = keyof AssistantTemplate & keyof AppTemplate;
type RequiredKeys = {
  [K in CommonKeys]: undefined extends AssistantTemplate[K]
    ? never
    : undefined extends AppTemplate[K]
      ? never
      : K;
}[CommonKeys];
type OptionalKeys = Exclude<CommonKeys, RequiredKeys>;

export type GenericTemplate = {
  [K in RequiredKeys]: AssistantTemplate[K] | AppTemplate[K];
} & {
  [K in OptionalKeys]?: AssistantTemplate[K] | AppTemplate[K];
};

// Creating an app from template has the same request body, so we can use the assistant one for both of them
type TemplateCreateRequest = JSONRequestBody<
  "post",
  "/api/v1/spaces/{id}/applications/assistants/"
>;

export type TemplateAdapter = {
  type: "assistants" | "apps";
  getTemplates: () => Promise<GenericTemplate[]>;
  createNew: (params: TemplateCreateRequest) => Promise<{ id: string }>;
  getResourceName: () => { singular: string; singularCapitalised: string };
  getCategorisedTemplates: (templates: GenericTemplate[]) => {
    title: string;
    description: string;
    templates: GenericTemplate[];
  }[];
};

export function createAssistantTemplateAdapter(params: {
  eneo: Eneo;
  currentSpaceId: string;
}): TemplateAdapter {
  const { eneo, currentSpaceId } = params;

  return {
    type: "assistants",
    async getTemplates() {
      return await eneo.templates.list({ filter: "assistants" });
    },
    async createNew({ from_template, name }: TemplateCreateRequest) {
      return await eneo.assistants.create({ spaceId: currentSpaceId, name, from_template });
    },
    getResourceName() {
      const resourceName = m.resource_assistant();
      return {
        singular: resourceName,
        singularCapitalised: resourceName.charAt(0).toUpperCase() + resourceName.slice(1)
      };
    },
    getCategorisedTemplates(templates) {
      // Group templates by category dynamically (no filtering)
      const templatesByCategory = new Map<string, GenericTemplate[]>();

      for (const template of templates) {
        const category = template.category || "misc";
        if (!templatesByCategory.has(category)) {
          templatesByCategory.set(category, []);
        }
        templatesByCategory.get(category)!.push(template);
      }

      // Convert to category sections with titles and descriptions
      return Array.from(templatesByCategory.entries()).map(([category, categoryTemplates]) => {
        const info = getCategoryInfo(category, assistantTemplateCategories);
        return {
          ...info,
          templates: categoryTemplates
        };
      });
    }
  };
}

export function createAppTemplateAdapter(params: {
  eneo: Eneo;
  currentSpaceId: string;
}): TemplateAdapter {
  const { eneo, currentSpaceId } = params;

  return {
    type: "apps",
    async getTemplates() {
      return await eneo.templates.list({ filter: "apps" });
    },
    async createNew({ from_template, name }: TemplateCreateRequest) {
      return await eneo.apps.create({ spaceId: currentSpaceId, name, from_template });
    },
    getResourceName() {
      const resourceName = m.resource_app();
      return {
        singular: resourceName,
        singularCapitalised: resourceName.charAt(0).toUpperCase() + resourceName.slice(1)
      };
    },
    getCategorisedTemplates(templates) {
      // Group templates by category dynamically (no filtering)
      const templatesByCategory = new Map<string, GenericTemplate[]>();

      for (const template of templates) {
        const category = template.category || "misc";
        if (!templatesByCategory.has(category)) {
          templatesByCategory.set(category, []);
        }
        templatesByCategory.get(category)!.push(template);
      }

      // Convert to category sections with titles and descriptions
      return Array.from(templatesByCategory.entries()).map(([category, categoryTemplates]) => {
        const info = getCategoryInfo(category, appTemplateCategories);
        return {
          ...info,
          templates: categoryTemplates
        };
      });
    }
  };
}
