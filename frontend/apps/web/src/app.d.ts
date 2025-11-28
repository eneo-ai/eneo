// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces
import { getFeatureFlags } from "$lib/core/flags.server";
import type { getEnvironmentConfig } from "./lib/core/environment.server";

declare global {
  namespace App {
    interface Error {
      message: string;
      status: number;
      code: IntricErrorCode;
    }
    interface Locals {
      featureFlags: Awaited<ReturnType<typeof getFeatureFlags>>;
      environment: ReturnType<typeof getEnvironmentConfig>;
      id_token: string | null;
      access_token: string | null;
    }
    // interface PageData {}
    interface PageState {
      currentSpace?: Space;
      /** Selected session in an assistant, useful for keeping history with pushState */
      conversation?: { id: string };
      tab?: string;
    }
    // interface Platform {}
  }

  // App version
  declare const __FRONTEND_VERSION__: string;
  declare const __IS_PREVIEW__: boolean | undefined;
  declare const __GIT_BRANCH__: string | undefined;
  declare const __GIT_COMMIT_SHA__: string | undefined;

  // View transition API
  interface ViewTransition {
    updateCallbackDone: Promise<void>;
    ready: Promise<void>;
    finished: Promise<void>;
    skipTransition: () => void;
  }

  interface Document {
    startViewTransition(updateCallback: () => Promise<void>): ViewTransition;
  }

  interface CSSStyleDeclaration {
    viewTransitionName: string;
  }

  interface AriaProps {
    "aria-labelledby"?: string;
    "aria-describedby"?: string;
    "aria-label"?: string;
  }
}

export {};
