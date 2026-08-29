// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-887168c8fe6f
export const STAGED_PREVIEW_STORAGE_KEY = "itkflow.stagedPreview";

export const STAGED_PREVIEW_MODES = ["tabs", "inline", "off"] as const;
export type StagedPreviewMode = (typeof STAGED_PREVIEW_MODES)[number];

function isMode(value: string | null): value is StagedPreviewMode {
  return value !== null && (STAGED_PREVIEW_MODES as readonly string[]).includes(value);
}

/** Safe for blocked storage, privacy mode and server-side rendering. */
export function readStagedPreviewPreference(): StagedPreviewMode {
  if (typeof window === "undefined") return "tabs";
  try {
    const value = window.localStorage.getItem(STAGED_PREVIEW_STORAGE_KEY);
    return isMode(value) ? value : "tabs";
  } catch {
    return "tabs";
  }
}

/** Preference persistence is best effort; rendering must never depend on it. */
export function writeStagedPreviewPreference(mode: StagedPreviewMode): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STAGED_PREVIEW_STORAGE_KEY, mode);
  } catch {
    // Storage can be unavailable in hardened/private browser contexts.
  }
  // Same-tab subscribers (the module page) must see the change immediately:
  // `storage` events only fire in OTHER tabs, so without this the preference
  // applied only after a full reload.
  for (const listener of [...listeners]) listener(mode);
}

type PreferenceListener = (mode: StagedPreviewMode) => void;

const listeners = new Set<PreferenceListener>();

/** Live preference feed for the current tab; returns the unsubscribe. */
export function subscribeStagedPreviewPreference(listener: PreferenceListener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

