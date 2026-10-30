/*
    Copyright (c) 2024 Sundsvalls Kommun
*/

import { goto } from "$app/navigation";
import { resolve } from "$app/paths";
import { createContext } from "$lib/core/context";
import type {
  AssistantSkillBindingInput,
  Eneo,
  ResourcePermission,
  Space,
  SpaceSparse
} from "@eneo/eneo-js";
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
  const organizationSpaceId = derived(currentSpace, ($space) => $space.organization_space_id);

  const nonOrgSpaces = derived(userSpaces, ($spaces) =>
    $spaces.filter((s) => !isOrganizationSpace(s))
  );

  // Function definitions --------------------------------------------------------
  let navigationVersion = 0;
  let refreshSequence = 0;
  let spaceUpdates = 0;
  const refreshVersions = { applications: 0, knowledge: 0 };

  /** Will update the current space if a new space is passed in via page data */
  function watchPageData(data: { currentSpace: Space }) {
    if (data.currentSpace.id !== get(currentSpace).id) {
      navigationVersion += 1;
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

  /** Re-reads the current space, or one part of it; false when the request failed. */
  async function refreshCurrentSpace(type?: "applications" | "knowledge"): Promise<boolean> {
    const requestedSpace = get(currentSpace);
    const navigation = navigationVersion;
    const request = ++refreshSequence;
    const updates = spaceUpdates;
    if (type) refreshVersions[type] = request;
    else {
      refreshVersions.applications = request;
      refreshVersions.knowledge = request;
    }
    const isCurrent = () =>
      navigation === navigationVersion &&
      requestedSpace.id === get(currentSpace).id &&
      (type
        ? refreshVersions[type] === request
        : updates === spaceUpdates &&
          Object.values(refreshVersions).every((version) => version === request));
    try {
      if (type) {
        switch (type) {
          case "applications": {
            const applications = await eneo.spaces.listApplications(requestedSpace);
            if (!isCurrent()) return false;
            currentSpace.update((space) => ({ ...space, applications }));
            break;
          }
          case "knowledge": {
            const knowledge = await eneo.spaces.listKnowledge(requestedSpace);
            if (!isCurrent()) return false;
            currentSpace.update((space) => ({ ...space, knowledge }));
            break;
          }
        }
      } else {
        const space = await eneo.spaces.get(requestedSpace);
        if (!isCurrent()) return false;
        currentSpace.set(space);
      }
      return true;
    } catch (e) {
      console.error("Error updating current space", e);
      return false;
    }
  }

  /** Will update a given space. If no space is specified will update the current space. */
  async function updateSpace(
    update: Parameters<typeof eneo.spaces.update>[0]["update"],
    space?: { id: string } | undefined
  ) {
    const { id } = space ?? get(currentSpace);
    const navigation = navigationVersion;
    try {
      const updatedSpace = await eneo.spaces.update({ space: { id }, update });
      userSpaces.update((spaces) => {
        const idx = spaces.findIndex((space) => space.id === updatedSpace.id);
        if (idx > -1) {
          spaces[idx] = updatedSpace;
        }
        return spaces;
      });
      // The mutation still updates the list, but a late response cannot replace
      // the space reached since it began, including navigation back to this id.
      if (space === undefined && navigation === navigationVersion && id === get(currentSpace).id) {
        // A full re-read still in flight began before this and must not put the old space back.
        spaceUpdates++;
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

  // Skills changes are saved on the default assistant while the user chats, so
  // a message sent right after a change must not race the save: sends wait for
  // this chain (see awaitDefaultAssistantUpdates) and saves run one at a time so
  // a quick A → B → C never lets an older write land last. The model and
  // reasoning choices are conversation settings owned by ChatService.
  let pendingDefaultAssistantUpdate: Promise<void> = Promise.resolve();

  /** Resolves once every queued default-assistant update has settled. */
  function awaitDefaultAssistantUpdates(): Promise<void> {
    return pendingDefaultAssistantUpdate;
  }

  /**
   * Saves the person's own Skills for the personal chat in the same queue, so
   * a message sent right after uses them. `skillBindings` builds the full
   * ordered list when the save's turn comes, from what is saved by then, so
   * a change refused earlier in the queue never travels with a later one. It
   * rejects to its caller, which shows the choice at once and rolls it back
   * itself; the queue still settles. The assistant is passed in, not read
   * when the save runs, so leaving the personal space cannot redirect it.
   */
  function updateDefaultAssistantSkills(
    assistant: { id: string },
    skillBindings: () => Promise<AssistantSkillBindingInput[]>
  ): Promise<void> {
    const run = async () => {
      const updatedAssistant = await eneo.assistants.update({
        assistant,
        update: { skill_bindings: await skillBindings() }
      });
      currentSpace.update(($currentSpace) => {
        if ($currentSpace.default_assistant?.id === assistant.id) {
          $currentSpace.default_assistant = updatedAssistant;
        }
        return $currentSpace;
      });
    };
    const saved = pendingDefaultAssistantUpdate.then(run, run);
    pendingDefaultAssistantUpdate = saved.catch(() => {});
    return saved;
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
    updateSpace,
    deleteSpace,
    watchPageData,
    updateDefaultAssistantSkills,
    awaitDefaultAssistantUpdates
  });
}

function isOrganizationSpace(space: SpaceSparse) {
  return space.organization === true;
}

// SpacesManager is exported for unit tests; components use initSpacesManager.
export { initSpacesManager, getSpacesManager, SpacesManager };

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
          case "skill":
            return $space.skill_permissions?.includes(action) ?? false;
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
  | "skill"
  | "collection"
  | "member"
  | "group_member"
  | "app";
