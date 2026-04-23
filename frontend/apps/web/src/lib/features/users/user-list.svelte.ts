import { PAGINATION } from "$lib/core/constants";
import { createAsyncState } from "$lib/core/helpers/createAsyncState.svelte";
import { getIntric } from "$lib/core/Intric";
import type { Intric, Permission, UserSparse } from "@intric/intric-js";
import { onMount } from "svelte";

const DEBOUNCE_DURATION_MILLISECONDS = 250;

/**
 * Paginated, filterable tenant user list used by pickers.
 *
 * Pass `permission` to narrow the result set to users whose tenant role grants
 * that permission (e.g. the space member picker uses `shared_spaces` so only
 * addable candidates appear). Omit for a capability-neutral list (e.g. the
 * user-groups admin picker, where groups are just bags of users).
 */
export class UserList {
  #intric: Intric;
  #cursor: string | undefined = undefined;
  #limit = PAGINATION.PAGE_SIZE;
  #filter = "";
  #permission: Permission | undefined;
  #debounceTimeout: ReturnType<typeof setTimeout> | undefined = undefined;

  totalCount = $state(0);
  filteredUsers = $state<UserSparse[]>([]);

  constructor(options?: { intric?: Intric; permission?: Permission }) {
    this.#intric = options?.intric ?? getIntric();
    this.#permission = options?.permission;
    onMount(this.loadUsers);
  }

  loadUsers = createAsyncState(async (append = false) => {
    const res = await this.#intric.users.list({
      filter: this.#filter,
      limit: this.#limit,
      cursor: append ? this.#cursor : undefined,
      permission: this.#permission
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
