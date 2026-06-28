/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

import { goto } from "$app/navigation";
import { resolve } from "$app/paths";
import { createContext } from "$lib/core/context";
import type { Eneo, ResourcePermission, Space, SpaceSparse } from "@eneo/eneo-js";
import { derived, get, writable, type Readable } from "svelte/store";
import { toastError } from "$lib/core/errors";

const [getSpacesManager, setSpacesManager] = createContext<ReturnType<typeof SpacesManager>>(
  "Manages spaces / projects"
);

/**
 * Initialise the SpacesManger in its context.
 * Retrieve it via `getSpacesManager()`
 */
function initSpacesManager(data: SpacesManagerParams) {
  const manager = SpacesManager(data);
  setSpacesManager(manager);
  return manager;
}

type SpacesManagerParams = {
  /** Initialise with a list of existing spaces */
  spaces: SpaceSparse[];
  /** Provide the initial starting space – personal space if user hasn't requested a different one */
  currentSpace: Space;
  eneo: Eneo;
};

function SpacesManager(data: SpacesManagerParams) {
  // Setup variables --------------------------------------------------------
  const { eneo } = data;

  const userSpaces = writable(data.spaces);
  const currentSpace = writable(data.currentSpace);
  const organizationSpaceIdFromList = derived(userSpaces, ($spaces) => {
    return $spaces.find((s) => isOrganizationSpace(s))?.id ?? null;
  });

  const organizationSpaceId = derived([organizationSpaceIdFromList], ([$listId]) => $listId);

  const nonOrgSpaces = derived(userSpaces, ($spaces) =>
    $spaces.filter((s) => !isOrganizationSpace(s))
  );

  // Function definitions --------------------------------------------------------
  /** Will update the current space if a new space is passed in via page data */
  function watchPageData(data: { currentSpace: Space }) {
    if (data.currentSpace.id !== get(currentSpace).id) {
      currentSpace.set(data.currentSpace);
    }
  }

  /** Updates the internal state of accessible spaces and returns the updated list */
  async function refreshSpaces() {
    try {
      const updated = await eneo.spaces.list();
      userSpaces.set(updated);
      return updated;
    } catch (e) {
      console.error("Error updating spaces", e);
    }
  }

  async function refreshCurrentSpace(type?: "applications" | "knowledge") {
    let $currentSpace = get(currentSpace);
    try {
      if (type) {
        switch (type) {
          case "applications": {
            const applications = await eneo.spaces.listApplications($currentSpace);
            $currentSpace = { ...$currentSpace, applications };
            break;
          }
          case "knowledge": {
            const knowledge = await eneo.spaces.listKnowledge($currentSpace);
            $currentSpace = { ...$currentSpace, knowledge };
            break;
          }
        }
      } else {
        $currentSpace = await eneo.spaces.get($currentSpace);
      }
      currentSpace.set($currentSpace);
    } catch (e) {
      console.error("Error updating current space", e);
    }
  }

  /** Will create a new space and return it on success. Will return null on failure and show an alert */
  async function createSpace(space: { name: string }) {
    try {
      const newSpace = await eneo.spaces.create({ name: space.name });
      refreshSpaces();
      return newSpace;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
    return null;
  }

  /** Will update a given space. If no space is specified will update the current space. */
  async function updateSpace(
    update: Parameters<typeof eneo.spaces.update>[0]["update"],
    space?: { id: string } | undefined
  ) {
    const { id } = space ?? get(currentSpace);
    try {
      const updatedSpace = await eneo.spaces.update({ space: { id }, update });
      userSpaces.update((spaces) => {
        const idx = spaces.findIndex((space) => space.id === updatedSpace.id);
        if (idx > -1) {
          spaces[idx] = updatedSpace;
        }
        return spaces;
      });
      // Only update current if no other space was given
      if (space === undefined) {
        currentSpace.set(updatedSpace);
      }
      return updatedSpace;
    } catch (e) {
      toastError(e);
      console.error(e);
    }
  }

  /** Will delete a given space. Will alert on error. */
  async function deleteSpace(space: { id: string }) {
    try {
      await eneo.spaces.delete({ id: space.id });
      await refreshSpaces();
      if (space.id === get(currentSpace).id) {
        goto(resolve("/spaces/list"));
      }
    } catch (e) {
      toastError(e);
      console.error(e);
    }
  }

  async function updateDefaultAssistant({ completionModel }: { completionModel: { id: string } }) {
    const defaultAssistant = get(currentSpace).default_assistant;
    if (!defaultAssistant) return;
    const id = defaultAssistant.id;
    try {
      const updatedAssistant = await eneo.assistants.update({
        assistant: { id },
        update: { completion_model: completionModel }
      });
      currentSpace.update(($currentSpace) => {
        $currentSpace.default_assistant = updatedAssistant;
        return $currentSpace;
      });
    } catch (e) {
      toastError(e);
      console.error(e);
    }
  }

  return Object.freeze({
    state: {
      accessibleSpaces: { subscribe: nonOrgSpaces.subscribe },
      nonOrgSpaces,
      currentSpace: derivedCurrentSpace(currentSpace),
      organizationSpaceId
    },
    refreshSpaces,
    refreshCurrentSpace,
    createSpace,
    updateSpace,
    deleteSpace,
    watchPageData,
    updateDefaultAssistant
  });
}

function isOrganizationSpace(space: SpaceSparse) {
  return space.organization === true;
}

export { initSpacesManager, getSpacesManager };

function derivedCurrentSpace(space: Readable<Space>) {
  return derived(space, ($space) => {
    // Spreading the $space is less performant than assigning the values
    // But makes type inference much easier. let's keep it like that as
    // long as we do not run into performance issues.
    // At that point we should probably also independently refresh the resources
    // (apps, knowledge) with their respective endpoints.

    return {
      ...$space,
      organization: isOrganizationSpace($space),
      routeId: $space.personal
        ? "personal"
        : isOrganizationSpace($space)
          ? "organization"
          : $space.id,
      members: $space.members.items,
      applications: {
        assistants: $space.applications?.assistants.items ?? [],
        groupChats: $space.applications?.group_chats.items ?? [],
        chat: [
          ...($space.applications?.assistants.items ?? []),
          ...($space.applications?.group_chats.items ?? [])
        ].sort((a, b) => a.name.localeCompare(b.name)),
        apps: $space.applications?.apps.items ?? [],
        services: ($space.applications?.services.items ?? []).filter((service) => {
          return !service.name.startsWith("_eneo");
        })
      },
      knowledge: {
        websites: $space.knowledge.websites.items,
        groups: $space.knowledge.groups.items,
        integrationKnowledge: $space.knowledge.integration_knowledge_list.items
      },
      hasPermission(action: ResourcePermission, resource: Resource) {
        switch (resource) {
          case "space":
            return $space.permissions?.includes(action) ?? false;
          case "assistant":
            return $space.applications?.assistants.permissions?.includes(action) ?? false;
          case "group_chat":
            return $space.applications?.group_chats.permissions?.includes(action) ?? false;
          case "default_assistant":
            return $space.default_assistant?.permissions?.includes(action) ?? false;
          case "app":
            return $space.applications?.apps.permissions?.includes(action) ?? false;
          case "service":
            return $space.applications?.services.permissions?.includes(action) ?? false;
          case "collection":
            return $space.knowledge.groups.permissions?.includes(action) ?? false;
          case "website":
            return $space.knowledge.websites.permissions?.includes(action) ?? false;
          case "integrationKnowledge":
            return (
              $space.knowledge.integration_knowledge_list.permissions?.includes(action) ?? false
            );
          case "member":
            return $space.members.permissions?.includes(action) ?? false;
          case "group_member":
            return $space.group_members?.permissions?.includes(action) ?? false;
          default:
            return false;
        }
      }
    };
  });
}

type Resource =
  | "space"
  | "assistant"
  | "default_assistant"
  | "group_chat"
  | "service"
  | "website"
  | "integrationKnowledge"
  | "collection"
  | "member"
  | "group_member"
  | "app";
