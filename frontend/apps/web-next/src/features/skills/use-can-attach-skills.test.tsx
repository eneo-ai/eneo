// @vitest-environment jsdom
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useCanAttachSkills } from "./use-can-attach-skills";

const userPermissions = vi.hoisted(() => ({ current: [] as string[] }));

vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    can: (action: string, resource: string) => action === "read" && resource === "skill"
  })
}));
vi.mock("@/components/providers/app-context", () => ({
  useAppContext: () => ({
    can: (permission: string) => userPermissions.current.includes(permission)
  })
}));

describe("useCanAttachSkills", () => {
  it("allows attaching with Use Skills", () => {
    userPermissions.current = ["skills"];
    expect(renderHook(() => useCanAttachSkills()).result.current).toBe(true);
  });

  it("does not allow attaching with Own Skills alone", () => {
    userPermissions.current = ["personal_chat", "personal_skills"];
    expect(renderHook(() => useCanAttachSkills()).result.current).toBe(false);
  });
});
