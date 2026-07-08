/**
 * Small presentational helpers shared across screens: semantic colour-coding
 * for production stages and human-readable roles for the family tree.
 */

/**
 * Colour system for production stages — an *ordered* ramp, not arbitrary
 * categories. The assembly flow ripens from cool to green as it nears the goal
 * (blue → sky → cyan-teal → teal → teal-green), and the two culturally strong
 * status hues stay reserved and OUTSIDE the ramp: green = FINISHED (done), red
 * = FAILED/TRASHED (an exit, never a progress step). Lightness rises toward the
 * end, so "how far along" reads at a glance and survives colour-vision
 * deficiency. Institute-agnostic; unknown stages fall back to neutral.
 */
type StageTone =
  | "good"
  | "crit"
  | "hv"
  | "glue"
  | "stitch"
  | "bonded"
  | "tested"
  | "none";

function stageToneOf(stage: string): StageTone {
  switch (stage) {
    case "FINISHED":
    case "AT_LOADING_SITE":
      return "good";
    case "FAILED":
    case "ABANDONED":
    case "TRASHED":
      return "crit";
    case "HV_TAB_ATTACHED":
      return "hv";
    case "GLUED":
      return "glue";
    case "STITCH_BONDING":
      return "stitch";
    case "BONDED":
      return "bonded";
    case "TESTED":
      return "tested";
    default:
      return "none";
  }
}

const CHIP_BY_TONE: Record<StageTone, string> = {
  good: "chip green",
  crit: "chip red",
  hv: "chip st-hv",
  glue: "chip st-glue",
  stitch: "chip st-stitch",
  bonded: "chip st-bonded",
  tested: "chip st-tested",
  none: "chip stage",
};

/** Chip class for a production stage (see the ramp described above). */
export function stageChipClass(stage: string): string {
  return CHIP_BY_TONE[stageToneOf(stage)];
}

/** Semantic tone of a stage, for CSS accents (data-tone attribute). */
export function stageTone(stage: string): StageTone {
  return stageToneOf(stage);
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
