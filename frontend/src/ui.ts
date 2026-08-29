// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-f891c14f4adb
/**
 * Small presentational helpers shared across screens: semantic colour-coding
 * for production stages and human-readable roles for the family tree.
 */
import type { OutboxStatus } from "./api";

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

/**
 * Collaboration-wide ITk acronyms that must stay upper-cased when a SNAKE_CASE
 * stage/test code is humanised (docs/10-itk-domain-reference.md). This is shared
 * ITk vocabulary, not institute config — so it is safe to keep fixed (rule #4).
 */
const ITK_ACRONYMS = new Set([
  "HV", "IV", "LV", "VI", "QC", "PWB", "DAQ", "AMAC", "ABC", "HCC", "TC", "ID", "SN",
]);

/**
 * Human-readable label for a SNAKE_CASE stage/test code, e.g.
 * `HV_TAB_ATTACHED` → "HV Tab Attached", `STITCH_BONDING` → "Stitch Bonding".
 * Institute-agnostic: it only splits on underscores and Title-Cases words,
 * preserving known ITk acronyms. The raw code stays the canonical technical
 * label — callers keep showing it (tooltip / mono sub-label) alongside this.
 */
export function stageLabel(stage: string | null | undefined): string {
  if (!stage) return "";
  return stage
    .trim()
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => {
      const upper = word.toUpperCase();
      if (ITK_ACRONYMS.has(upper)) return upper;
      return upper.charAt(0) + word.slice(1).toLowerCase();
    })
    .join(" ");
}

/** Tone for an outbox status — green when confirmed, red on failure, muted
 * when cancelled, neutral while in the review pipeline. */
export function statusTone(status: string): "good" | "crit" | "none" {
  if (status === "confirmed") return "good";
  if (status === "failed") return "crit";
  return "none";
}

/** Chip class for an outbox action's status. Shared by the Staged-actions
 * panel and the worksheet's ghost sub-rows (review finding M4) so both read
 * the same status the same way instead of keeping two copies in sync. */
export function outboxStatusChipClass(status: OutboxStatus): string {
  if (status === "confirmed") return "chip green";
  if (status === "failed") return "chip red";
  if (status === "cancelled") return "chip muted";
  return "chip amber"; // draft / validated / approved / submitted are in-flight
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

/**
 * Whether a browser will actually paint this attachment in an `<img>`.
 *
 * `is_image` answers "is this an image", which is not the same question. The
 * mirror holds two 36 MB TIFFs from a visual inspection: a truthful
 * `image/tiff` makes `is_image` true, and Chromium — so also the desktop
 * WebView2 shell — renders nothing but a broken tile. Callers use this to show
 * the existing "stored, not displayable" placeholder instead, which is honest
 * about the file being present.
 *
 * The list is what browsers agree on, not everything that is an image.
 */
const DISPLAYABLE_IMAGE_TYPES = new Set([
  "image/jpeg",
  "image/jpg",
  "image/png",
  "image/gif",
  "image/webp",
  "image/bmp",
  "image/avif",
  "image/svg+xml",
]);

export function isDisplayableImage(attachment: {
  is_image: boolean;
  content_type: string | null;
}): boolean {
  if (!attachment.is_image) return false;
  const type = (attachment.content_type ?? "").split(";")[0].trim().toLowerCase();
  return DISPLAYABLE_IMAGE_TYPES.has(type);
}
