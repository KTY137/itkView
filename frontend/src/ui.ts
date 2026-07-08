/**
 * Small presentational helpers shared across screens: semantic colour-coding
 * for production stages and human-readable roles for the family tree.
 */

/** Chip colour for a production stage — green when done/passing, red on
 * failure, neutral while in progress. Keeps the board scannable at a glance. */
export function stageChipClass(stage: string): string {
  if (stage === "FINISHED" || stage === "TESTED") return "chip green";
  if (stage === "FAILED" || stage === "ABANDONED") return "chip red";
  if (stage === "BONDED" || stage === "STITCH_BONDING") return "chip amber";
  return "chip stage";
}

/** Semantic tone of a stage, for CSS accents (data-tone attribute). */
export function stageTone(stage: string): "good" | "warn" | "crit" | "none" {
  if (stage === "FINISHED" || stage === "TESTED") return "good";
  if (stage === "FAILED" || stage === "ABANDONED") return "crit";
  if (stage === "BONDED" || stage === "STITCH_BONDING") return "warn";
  return "none";
}

/** Family-tree role label from a PDB component type. Institute-agnostic; falls
 * back to the raw type for anything not in the common assembly vocabulary. */
export function roleLabel(componentType: string): string {
  const map: Record<string, string> = {
    MODULE: "Module",
    SENSOR: "Sensor",
    HYBRID: "Hybrid",
    HYBRID_FLEX: "Hybrid flex",
    PWB: "Powerboard",
    POWERBOARD: "Powerboard",
    PWB_CARRIER: "PWB carrier",
  };
  return map[componentType] ?? componentType;
}
