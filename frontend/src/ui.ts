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

/** Tone for an outbox status — green when confirmed, red on failure, muted
 * when cancelled, neutral while in the review pipeline. */
export function statusTone(status: string): "good" | "crit" | "none" {
  if (status === "confirmed") return "good";
  if (status === "failed") return "crit";
  return "none";
}

/** Family-tree role label from a PDB component type. Institute-agnostic; falls
 * back to the raw type for anything not in the common assembly vocabulary. */
export function roleLabel(componentType: string): string {
  const map: Record<string, string> = {
    MODULE: "Module",
    SENSOR: "Sensor",
    HYBRID: "Hybrid",
    HYBRID_ASSEMBLY: "Hybrid",
    HYBRID_FLEX: "Hybrid flex",
    PWB: "Powerboard",
    POWERBOARD: "Powerboard",
    PWB_CARRIER: "PWB carrier",
    ABC: "ABC ASIC",
    ABCSTAR: "ABCStar ASIC",
    HCC: "HCC ASIC",
    HCCSTAR: "HCCStar ASIC",
    AMAC: "AMAC ASIC",
  };
  return map[componentType.toUpperCase()] ?? componentType;
}

/**
 * Coarse component kind from the PDB componentType. Institute-agnostic — for
 * grouping/iconography, never behaviour. `sensor` and `asic` (ABC/HCC/AMAC) are
 * the "never register" kinds (hard rule #2, docs/10-itk-domain-reference.md).
 */
export type ComponentKind =
  | "module"
  | "sensor"
  | "hybrid"
  | "powerboard"
  | "asic"
  | "other";

export function componentKind(componentType: string): ComponentKind {
  const c = componentType.toUpperCase();
  if (c === "MODULE") return "module";
  if (c === "SENSOR") return "sensor";
  if (c.startsWith("HYBRID")) return "hybrid";
  if (c === "PWB" || c === "POWERBOARD" || c === "PWB_CARRIER") return "powerboard";
  if (c === "ABC" || c === "ABCSTAR" || c === "HCC" || c === "HCCSTAR" || c === "AMAC")
    return "asic";
  return "other";
}

/**
 * Decode the compact ITk `type_code` into a human-readable geometry, or null
 * when the pattern is unknown (the caller then shows the raw code). The codes
 * are collaboration-wide conventions, not institute-specific, so this stays a
 * pure pattern decode with graceful fallback — no `R5M0 -> "…"` table (hard
 * rule #4). See docs/10-itk-domain-reference.md.
 *
 *   R<ring>M/H<pos>  endcap module/hybrid  R5M0 -> "Endcap R5, pos 0"
 *   ATLAS<g>R<ring>  endcap sensor         ATLAS18R5 -> "Sensor ATLAS18, Endcap R5"
 *   ATLAS<g>SS/LS    barrel sensor         ATLAS18LS -> "Sensor ATLAS18, Barrel long-strip"
 *   PB[R]<ring>      powerboard            PBR5 -> "Powerboard R5"
 */
export function describeTypeCode(typeCode: string | null | undefined): string | null {
  if (!typeCode) return null;
  const code = typeCode.trim().toUpperCase();

  const endcap = code.match(/^R(\d+)[MH](\d+)$/);
  if (endcap) return `Endcap R${endcap[1]}, pos ${endcap[2]}`;

  const sensor = code.match(/^ATLAS(\d+)(R\d+|SS|LS)$/);
  if (sensor) {
    const [, gen, geo] = sensor;
    if (geo.startsWith("R")) return `Sensor ATLAS${gen}, Endcap ${geo}`;
    return `Sensor ATLAS${gen}, Barrel ${geo === "SS" ? "short-strip" : "long-strip"}`;
  }

  const pwb = code.match(/^PBR?(\d+)?$/);
  if (pwb) return pwb[1] ? `Powerboard R${pwb[1]}` : "Powerboard";

  return null;
}

/**
 * One-line component overview: kind plus decoded geometry, e.g.
 * "Hybrid · Endcap R5, pos 1". Falls back to `kind · rawcode`, then to just the
 * kind, so nothing is ever hidden.
 */
export function describeComponent(c: {
  component_type: string;
  type_code: string | null;
}): string {
  const kind = roleLabel(c.component_type);
  // Treat the mirror's UNKNOWN sentinel as "no code" so it never leaks to the UI.
  const raw = c.type_code && c.type_code !== "UNKNOWN" ? c.type_code : null;
  const geo = describeTypeCode(raw);
  if (geo) {
    // Some decodes already name the kind (Sensor…, Powerboard…) — don't repeat it.
    return geo.toLowerCase().startsWith(kind.toLowerCase()) ? geo : `${kind} · ${geo}`;
  }
  if (raw) return `${kind} · ${raw}`;
  return kind;
}
