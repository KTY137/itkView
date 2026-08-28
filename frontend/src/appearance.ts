export const APPEARANCE_THEME_STORAGE_KEY = "itkview.appearance.theme";
export const APPEARANCE_ACCENT_STORAGE_KEY = "itkview.appearance.accent";

export const APPEARANCE_THEMES = ["system", "light", "dark"] as const;
export type AppearanceTheme = (typeof APPEARANCE_THEMES)[number];

export const APPEARANCE_ACCENTS = ["copper", "blue", "teal", "violet"] as const;
export type AppearanceAccent = (typeof APPEARANCE_ACCENTS)[number];

export type AppearancePreference = {
  theme: AppearanceTheme;
  accent: AppearanceAccent;
};

const DEFAULT_APPEARANCE: AppearancePreference = {
  theme: "system",
  accent: "copper",
};

function includes<T extends string>(values: readonly T[], value: string | null): value is T {
  return value !== null && (values as readonly string[]).includes(value);
}

export function readAppearancePreference(): AppearancePreference {
  if (typeof window === "undefined") return DEFAULT_APPEARANCE;
  try {
    const theme = window.localStorage.getItem(APPEARANCE_THEME_STORAGE_KEY);
    const accent = window.localStorage.getItem(APPEARANCE_ACCENT_STORAGE_KEY);
    return {
      theme: includes(APPEARANCE_THEMES, theme) ? theme : DEFAULT_APPEARANCE.theme,
      accent: includes(APPEARANCE_ACCENTS, accent) ? accent : DEFAULT_APPEARANCE.accent,
    };
  } catch {
    return DEFAULT_APPEARANCE;
  }
}

function resolvedTheme(theme: AppearanceTheme): "light" | "dark" {
  if (theme !== "system") return theme;
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyAppearancePreference(preference: AppearancePreference): void {
  if (typeof document === "undefined" || typeof window === "undefined") return;
  document.documentElement.dataset.theme = resolvedTheme(preference.theme);
  document.documentElement.dataset.themePreference = preference.theme;
  document.documentElement.dataset.accent = preference.accent;
}

export function writeAppearancePreference(preference: AppearancePreference): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(APPEARANCE_THEME_STORAGE_KEY, preference.theme);
    window.localStorage.setItem(APPEARANCE_ACCENT_STORAGE_KEY, preference.accent);
  } catch {
    // Hardened/private browser contexts may block storage. Apply it for this
    // session anyway; appearance must never prevent the application loading.
  }
  applyAppearancePreference(preference);
  for (const listener of [...listeners]) listener(preference);
}

type AppearanceListener = (preference: AppearancePreference) => void;
const listeners = new Set<AppearanceListener>();

export function subscribeAppearancePreference(listener: AppearanceListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

let systemThemeListenerInstalled = false;

/** Apply saved appearance before React paints and follow later OS theme changes. */
export function initializeAppearance(): void {
  if (typeof window === "undefined") return;
  applyAppearancePreference(readAppearancePreference());
  if (systemThemeListenerInstalled || typeof window.matchMedia !== "function") return;
  systemThemeListenerInstalled = true;
  window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => {
    const preference = readAppearancePreference();
    if (preference.theme === "system") applyAppearancePreference(preference);
  });
}
