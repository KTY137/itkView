// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-271543edee86
export const SYNC_MODE_STORAGE_KEY = "itkview.sync.mode";

export const SYNC_MODES = ["standard", "lightweight"] as const;
export type SyncMode = (typeof SYNC_MODES)[number];

export function readSyncModePreference(): SyncMode {
  if (typeof window === "undefined") return "standard";
  try {
    const value = window.localStorage.getItem(SYNC_MODE_STORAGE_KEY);
    return value === "lightweight" ? "lightweight" : "standard";
  } catch {
    return "standard";
  }
}

export function writeSyncModePreference(mode: SyncMode): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SYNC_MODE_STORAGE_KEY, mode);
  } catch {
    // Best effort only; standard sync remains the safe default.
  }
  for (const listener of [...listeners]) listener(mode);
}

type SyncModeListener = (mode: SyncMode) => void;
const listeners = new Set<SyncModeListener>();

export function subscribeSyncModePreference(listener: SyncModeListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
