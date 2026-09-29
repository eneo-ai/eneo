import { beforeEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({
  building: false,
  privateEnv: {} as Record<string, string>,
  publicEnv: {} as Record<string, string>
}));

vi.mock("$app/environment", () => ({
  browser: false,
  dev: false,
  version: "test",
  get building() {
    return state.building;
  }
}));
vi.mock("$env/dynamic/private", () => ({ env: state.privateEnv }));
vi.mock("$env/dynamic/public", () => ({ env: state.publicEnv }));

const { init } = await import("./hooks.server");

function setEnv(privateEnv: Record<string, string>, publicEnv: Record<string, string> = {}) {
  for (const key of Object.keys(state.privateEnv)) delete state.privateEnv[key];
  for (const key of Object.keys(state.publicEnv)) delete state.publicEnv[key];
  Object.assign(state.privateEnv, privateEnv);
  Object.assign(state.publicEnv, publicEnv);
}

describe("init", () => {
  beforeEach(() => {
    state.building = false;
    setEnv({ ENEO_BACKEND_URL: "https://eneo.example.com" });
  });

  it("starts with a configured environment", () => {
    expect(() => init()).not.toThrow();
  });

  it("refuses to start when only a removed backend URL is set", () => {
    setEnv({ INTRIC_BACKEND_URL: "https://eneo.example.com" });

    expect(() => init()).toThrow(/Rename it to ENEO_BACKEND_URL/);
  });

  it("checks the public variables too", () => {
    setEnv(
      { ENEO_BACKEND_URL: "https://eneo.example.com" },
      { PUBLIC_INTRIC_BACKEND_URL: "https://eneo.example.com" }
    );

    expect(() => init()).toThrow(/Rename it to PUBLIC_ENEO_BACKEND_URL/);
  });

  it("does not check the environment during the build", () => {
    state.building = true;
    setEnv({});

    expect(() => init()).not.toThrow();
  });
});
