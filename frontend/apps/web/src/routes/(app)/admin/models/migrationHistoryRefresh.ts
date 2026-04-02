import { writable } from "svelte/store";

export const migrationHistoryRefreshVersion = writable(0);

export function bumpModelMigrationHistoryVersion() {
  migrationHistoryRefreshVersion.update((version) => version + 1);
}
