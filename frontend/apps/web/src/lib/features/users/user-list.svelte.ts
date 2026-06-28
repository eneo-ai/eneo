import { PAGINATION } from "$lib/core/constants";
import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
import { getEneo } from "$lib/core/Eneo";
import type { Eneo, UserSparse } from "@eneo/eneo-js";
import { onMount } from "svelte";

const DEBOUNCE_DURATION_MILLISECONDS = 250;

export class UserList {
  #eneo: Eneo;
  #cursor: string | undefined = undefined;
  #limit = PAGINATION.PAGE_SIZE;
  #filter = "";
  #debounceTimeout: ReturnType<typeof setTimeout> | undefined = undefined;

  totalCount = $state(0);
  filteredUsers = $state<UserSparse[]>([]);

  constructor(options?: { eneo?: Eneo }) {
    this.#eneo = options?.eneo ?? getEneo();
    onMount(this.loadUsers);
  }

  loadUsers = createAsyncState(async (append = false) => {
    const res = await this.#eneo.users.list({
      filter: this.#filter,
      limit: this.#limit,
      cursor: append ? this.#cursor : undefined
    });
    this.#cursor = res.next_cursor ?? undefined;
    this.totalCount = res.total_count;
    if (append) {
      this.filteredUsers.push(...res.items);
    } else {
      this.filteredUsers = res.items;
    }
  });

  get hasMoreUsers() {
    return this.totalCount - this.filteredUsers.length > 0;
  }

  get isLoadingUsers() {
    return this.loadUsers.isLoading;
  }

  setFilter(value: string) {
    if (value !== this.#filter) {
      this.#filter = value;
      clearTimeout(this.#debounceTimeout);
      this.#debounceTimeout = setTimeout(async () => {
        this.loadUsers();
      }, DEBOUNCE_DURATION_MILLISECONDS);
    }
  }

  loadMore() {
    this.loadUsers(true);
  }
}
