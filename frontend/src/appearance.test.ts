import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyAppearancePreference,
  readAppearancePreference,
  writeAppearancePreference,
} from "./appearance";
import {
  readSyncModePreference,
  writeSyncModePreference,
} from "./syncPreferences";

describe("browser appearance and sync preferences", () => {
  afterEach(() => {
    window.localStorage.clear();
    delete document.documentElement.dataset.theme;
    delete document.documentElement.dataset.themePreference;
    delete document.documentElement.dataset.accent;
    vi.restoreAllMocks();
  });

  it("applies and persists an explicit dark accent theme", () => {
    writeAppearancePreference({ theme: "dark", accent: "teal" });

    expect(readAppearancePreference()).toEqual({ theme: "dark", accent: "teal" });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("dark");
    expect(document.documentElement.dataset.accent).toBe("teal");
  });

  it("resolves the system preference without changing the saved choice", () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({ matches: true })));
    applyAppearancePreference({ theme: "system", accent: "copper" });

    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(document.documentElement.dataset.themePreference).toBe("system");
  });

  it("defaults safely and persists lightweight sync mode", () => {
    expect(readSyncModePreference()).toBe("standard");
    writeSyncModePreference("lightweight");
    expect(readSyncModePreference()).toBe("lightweight");
  });
});
