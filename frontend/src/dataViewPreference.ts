/** How much of a component's test data the viewer renders.
 *
 * `full` is every mirrored value the page has. `gate` reduces a module page to
 * the figures a stage decision is actually made on: per stage, the required
 * test and whether it passed, failed or is missing, with its date. Measured
 * values, run lists and plots are left out — not hidden data, but a different
 * question. Someone checking where production stands reads a wall of arrays to
 * find three verdicts; this is that reading, made directly.
 *
 * Viewer-only and browser-local, like the appearance and sync-scope choices:
 * it changes nothing on the server and nothing for anyone else. Authoring
 * needs the values themselves, so itkFlow never offers it.
 */
export const DATA_VIEW_STORAGE_KEY = "itkview.data.view";

export const DATA_VIEWS = ["full", "gate"] as const;
export type DataView = (typeof DATA_VIEWS)[number];

export function readDataViewPreference(): DataView {
  if (typeof window === "undefined") return "full";
  try {
    return window.localStorage.getItem(DATA_VIEW_STORAGE_KEY) === "gate" ? "gate" : "full";
  } catch {
    // A browser refusing site data must still show the complete page.
    return "full";
  }
}

export function writeDataViewPreference(view: DataView): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(DATA_VIEW_STORAGE_KEY, view);
  } catch {
    // Best effort only; the full view remains the safe default.
  }
  for (const listener of [...listeners]) listener(view);
}

type DataViewListener = (view: DataView) => void;
const listeners = new Set<DataViewListener>();

export function subscribeDataViewPreference(listener: DataViewListener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
