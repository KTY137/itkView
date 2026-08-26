import { describe, expect, it, vi } from "vitest";
import {
  readStagedPreviewPreference,
  STAGED_PREVIEW_STORAGE_KEY,
  writeStagedPreviewPreference,
} from "./stagedPreview";

describe("staged preview preference storage", () => {
  it("round-trips supported values and falls back for unknown values", () => {
    window.localStorage.clear();
    writeStagedPreviewPreference("inline");
    expect(window.localStorage.getItem(STAGED_PREVIEW_STORAGE_KEY)).toBe("inline");
    expect(readStagedPreviewPreference()).toBe("inline");

    window.localStorage.setItem(STAGED_PREVIEW_STORAGE_KEY, "unexpected");
    expect(readStagedPreviewPreference()).toBe("tabs");
  });

  it("falls back to tabs when storage reads are blocked", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(readStagedPreviewPreference()).toBe("tabs");
  });

  it("does not break rendering when storage writes are blocked", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });
    expect(() => writeStagedPreviewPreference("off")).not.toThrow();
  });
});
