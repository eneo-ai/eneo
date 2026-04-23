// Copyright (c) 2026 Sundsvalls Kommun
// Licensed under the MIT License.

export type InertNoticeMember = {
  id: string;
  email: string;
  username: string | null;
};

export type InertNoticePayload = {
  groupName: string;
  loginableTotal: number;
  missingCount: number;
  missing: InertNoticeMember[];
  truncated: boolean;
};
