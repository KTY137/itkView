// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-8b6d1cdd3681
/**
 * Data-entry layout: the order and the grouping an operator recognises.
 *
 * WHY. The generated test form renders whatever order the PDB definition
 * happens to list. For `GLUE_WEIGHT` that order is
 * `GW_SENSOR, GW_GLUE_H2, GW_HYBRID1, GW_GLUE_PB, GW_HYBRID2, GW_GLUE_H1,
 * GW_MODULE_H1H2, …` — every derived glue weight interleaved with the scale
 * readings it is derived from, and every `order` field in the definition set
 * to `1`, so there is nothing to sort by either. The production sheet this
 * app replaces collects the same raw fields in process order: the parts are
 * weighed first, then the assembly. Its formula result is read-only; itkFlow
 * likewise removes that code from `TestForm` and renders the server verdict.
 *
 * WHERE THE ORDER COMES FROM. Not from a table in this file — no field code,
 * module type or institute name may be a literal here (CLAUDE.md rule 4). It
 * comes from institute profile data that already exists and is already
 * validated server-side: `glue_weight_inputs` names, per step, the codes that
 * are `subtract`ed, the code that is `measured`, and the `result_code` the
 * derivation is stored under. That is exactly the sheet's sequence:
 *
 *   subtracted readings … → the total that was measured → server result
 *
 * because a subtracted code is a part weighed *before* assembly and the
 * measured code is the assembly weighed *after*. Reading the order out of the
 * formula means an institute that weighs a different chain gets its own
 * order for free, and the order can never contradict the arithmetic.
 *
 * Tool fields (`test_tool_fields`) are pulled out of the generated form
 * entirely: a jig is chosen from the registry, never typed. The mirrored
 * evidence shows what typing costs — one institute's 28 `MODULE_BOW` runs
 * carry three spellings of the same jig, and its 17 wire-bonding runs four
 * spellings of one machine.
 *
 * Everything here is pure. Fetching lives in `dataEntryProfile.ts`; rendering
 * lives in the panels. `TestForm` stays the only renderer of schema fields
 * and the only authority on which definition key holds the measurement block
 * — this module asks it via `measurementFields` rather than keeping a second
 * copy of that precedence rule.
 */
import type {
  TestSchemaDefinition,
  TestSchemaField,
  TestSchemaFieldCollection,
  Tool,
} from "./api";
import { measurementFields, requiredCodes } from "./TestForm";

/** The two blocks of a submitted run, named as `TestForm` names them. */
export type FieldSection = "properties" | "results";

/** One field of a definition, reduced to what a layout decision needs. */
export type LayoutField = {
  section: FieldSection;
  code: string;
  label: string;
  description: string | null;
  required: boolean;
  defaultValue: unknown;
};

/** One ordered band of fields, mirroring a band of the production sheet. */
export type FieldGroup = {
  /** Stable identity — the institute's own step key, or `"other"`. */
  key: string;
  /**
   * Heading text, verbatim institute data (like `assembly_tool_slots[].label`)
   * — never translated, never invented. `null` for the trailing group that
   * holds whatever the profile did not claim: an unnamed remainder must not
   * grow a heading that implies the institute meant it.
   */
  title: string | null;
  fields: LayoutField[];
};

/** One field that is a reference to a registry tool rather than a value. */
export type ToolField = LayoutField & {
  /** Registry kinds this field accepts; empty = any kind. */
  kinds: string[];
  /** The band it belongs to, so the panel can head it like the sheet does. */
  groupKey: string;
  groupTitle: string | null;
};

export type FieldLayoutPlan = {
  groups: FieldGroup[];
  toolFields: ToolField[];
  /**
   * The definition to hand `TestForm`: raw fields reordered per `groups`,
   * with `toolFields` and server-derived result codes removed. Emitted as
   * `{properties, results}` because `TestForm` treats a populated `results`
   * as the measurement block regardless of the key the PDB spelled it under.
   */
  definition: TestSchemaDefinition;
};

/** One derivation step of `glue_weight_inputs`, as the layout reads it. */
export type LayoutStep = {
  key: string;
  label: string | null;
  testType: string;
  /** Ordered: subtracted readings, then the measured total, then the result. */
  codes: string[];
  /** Exact component-type overrides, resolved by the same PDB type code as the backend. */
  byTypeCode: Record<string, { codes: string[]; resultCode: string | null }>;
  /** Server-computed output; never rendered as an editable raw reading. */
  resultCode: string | null;
};

export type ToolFieldSpec = {
  code: string;
  kinds: string[];
  /**
   * The band this field belongs under, as a `glue_weight_inputs` step key.
   *
   * The sheet keeps its tooling rows *inside* the gluing band they belong to
   * (`Hybrid glue jigs used` and `Module jig used` sit under
   * "Gluing Hybrids"; `Powerboard glue jig, pickup tool` under "Gluing
   * Powerboard"), and no derivation formula names a jig — so without this the
   * band could never be recovered from the formula alone. An unknown key
   * degrades to the unnamed remainder rather than inventing a heading.
   */
  step: string | null;
};

/** Institute-configured layout inputs, already parsed and fail-closed. */
export type DataEntryLayout = {
  steps: LayoutStep[];
  /** Keyed by upper-case test type. */
  toolFields: Record<string, ToolFieldSpec[]>;
};

export const EMPTY_LAYOUT: DataEntryLayout = { steps: [], toolFields: {} };

// ---- Profile parsing (fail closed, never guess) ------------------------------
//
// `institute_settings.normalize_institute_settings_update` is the only writer
// of well-formed values, but a reader must never throw on stored data that
// predates validation or was patched directly. A malformed block reads as
// "no layout configured", which degrades to the definition's own order — the
// behaviour before this module existed. It never half-applies.

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * A PDB test-type or field code, e.g. `GLUE_WEIGHT`, `GW_MODULE_H1PB`.
 * Mirrors `institute_settings._TEST_TYPE_RE`/`_RESULT_CODE_RE`: the reader
 * rejects exactly what the writer rejects, so a profile edited around the
 * validator cannot half-apply here either.
 */
const PDB_CODE_RE = /^[A-Z][A-Z0-9_]{0,63}$/u;

function cleanCode(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim().toUpperCase();
  return PDB_CODE_RE.test(trimmed) ? trimmed : null;
}

function cleanLabel(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

function cleanStringList(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const out: string[] = [];
  for (const entry of value) {
    if (typeof entry !== "string") return null;
    const trimmed = entry.trim();
    if (trimmed === "" || out.includes(trimmed)) return null;
    out.push(trimmed);
  }
  return out;
}

type ParsedLayoutFormula = {
  measured: string;
  subtract: string[];
  resultCode: string | null;
  codes: string[];
};

function parseLayoutFormula(
  value: Record<string, unknown>,
  defaults?: ParsedLayoutFormula,
): ParsedLayoutFormula | null {
  const measured = cleanCode(value.measured ?? defaults?.measured);
  if (measured === null) return null;

  const rawSubtract =
    value.subtract === undefined
      ? (defaults?.subtract ?? [])
      : cleanStringList(value.subtract);
  if (rawSubtract === null) return null;
  const subtract = rawSubtract.map((entry) => cleanCode(entry));
  if (subtract.some((code) => code === null)) return null;
  const normalizedSubtract = subtract as string[];
  if (
    normalizedSubtract.includes(measured) ||
    new Set(normalizedSubtract).size !== normalizedSubtract.length
  ) {
    return null;
  }

  const rawResultCode =
    value.result_code === undefined ? (defaults?.resultCode ?? null) : value.result_code;
  const resultCode = rawResultCode === null ? null : cleanCode(rawResultCode);
  if (
    (rawResultCode !== null && resultCode === null) ||
    resultCode === measured ||
    (resultCode !== null && normalizedSubtract.includes(resultCode))
  ) {
    return null;
  }

  const codes: string[] = [];
  for (const code of [...normalizedSubtract, measured, resultCode]) {
    if (code !== null && !codes.includes(code)) codes.push(code);
  }
  return { measured, subtract: normalizedSubtract, resultCode, codes };
}

/**
 * Read the ordered derivation steps out of `glue_weight_inputs`.
 *
 * The stored object's key order is the institute's own step order (JSON
 * objects preserve insertion order on both sides of the wire), which is why
 * the sheet's two gluing bands come out in the sheet's sequence without a
 * second ordering key to keep in sync.
 */
export function parseLayoutSteps(settings: unknown): LayoutStep[] {
  if (!isRecord(settings)) return [];
  const raw = settings.glue_weight_inputs;
  if (!isRecord(raw)) return [];
  const steps: LayoutStep[] = [];
  for (const [rawKey, rawStep] of Object.entries(raw)) {
    const key = cleanLabel(rawKey);
    if (key === null || !isRecord(rawStep)) return [];
    const formula = parseLayoutFormula(rawStep);
    if (formula === null) return [];
    // A step whose `test_type` is unreadable must not silently become a step
    // for every test type. The backend's documented default is GLUE_WEIGHT.
    const testType =
      rawStep.test_type === undefined ? "GLUE_WEIGHT" : cleanCode(rawStep.test_type);
    if (testType === null) return [];

    const byTypeCode: Record<string, { codes: string[]; resultCode: string | null }> = {};
    if (rawStep.by_type_code !== undefined) {
      if (!isRecord(rawStep.by_type_code)) return [];
      for (const [rawTypeCode, rawOverride] of Object.entries(rawStep.by_type_code)) {
        const typeCode = cleanCode(rawTypeCode);
        if (
          typeCode === null ||
          typeCode.length > 32 ||
          typeCode in byTypeCode ||
          !isRecord(rawOverride) ||
          Object.keys(rawOverride).some(
            (field) => !["measured", "subtract", "result_code"].includes(field),
          )
        ) {
          return [];
        }
        const override = parseLayoutFormula(rawOverride, formula);
        if (override === null) return [];
        byTypeCode[typeCode] = {
          codes: override.codes,
          resultCode: override.resultCode,
        };
      }
    }
    steps.push({
      key,
      label: cleanLabel(rawStep.label),
      testType,
      codes: formula.codes,
      byTypeCode,
      resultCode: formula.resultCode,
    });
  }
  return layoutStepsAreSafe(steps) ? steps : [];
}

function layoutStepsAreSafe(steps: LayoutStep[]): boolean {
  const typeCodes = new Set<string | null>([null]);
  for (const step of steps) {
    for (const typeCode of Object.keys(step.byTypeCode)) typeCodes.add(typeCode);
  }
  for (const typeCode of typeCodes) {
    const outputsByTest = new Map<string, Set<string>>();
    const inputsByTest = new Map<string, Set<string>>();
    for (const step of steps) {
      const formula =
        typeCode === null
          ? { codes: step.codes, resultCode: step.resultCode }
          : (step.byTypeCode[typeCode] ?? { codes: step.codes, resultCode: step.resultCode });
      const inputs = inputsByTest.get(step.testType) ?? new Set<string>();
      for (const code of formula.codes) {
        if (code !== formula.resultCode) inputs.add(code);
      }
      inputsByTest.set(step.testType, inputs);
      if (formula.resultCode === null) continue;
      const outputs = outputsByTest.get(step.testType) ?? new Set<string>();
      if (outputs.has(formula.resultCode)) return false;
      outputs.add(formula.resultCode);
      outputsByTest.set(step.testType, outputs);
    }
    for (const [testType, outputs] of outputsByTest) {
      const inputs = inputsByTest.get(testType) ?? new Set<string>();
      if ([...outputs].some((code) => inputs.has(code))) return false;
    }
  }
  return true;
}

/**
 * Read which fields hold a registry tool rather than a typed value.
 *
 * Shape: `{ "<TEST_TYPE>": [{ "code": "<FIELD_CODE>", "kinds": ["jig"] }] }`.
 * `kinds` is optional; absent or empty means every registry kind is offered.
 */
export function parseToolFieldSpecs(settings: unknown): Record<string, ToolFieldSpec[]> {
  if (!isRecord(settings)) return {};
  const raw = settings.test_tool_fields;
  if (!isRecord(raw)) return {};
  const parsed: Record<string, ToolFieldSpec[]> = {};
  for (const [rawTestType, rawSpecs] of Object.entries(raw)) {
    const testType = cleanCode(rawTestType);
    if (testType === null || !Array.isArray(rawSpecs)) return {};
    const specs: ToolFieldSpec[] = [];
    for (const rawSpec of rawSpecs) {
      if (!isRecord(rawSpec)) return {};
      const code = cleanCode(rawSpec.code);
      if (code === null || specs.some((spec) => spec.code === code)) return {};
      const rawKinds = rawSpec.kinds === undefined ? [] : cleanStringList(rawSpec.kinds);
      if (rawKinds === null) return {};
      const kinds = [...new Set(rawKinds.map((kind) => kind.toLowerCase()))];
      const step = rawSpec.step === undefined ? null : cleanLabel(rawSpec.step);
      if (rawSpec.step !== undefined && step === null) return {};
      specs.push({ code, kinds, step });
    }
    if (specs.length > 0) parsed[testType] = specs;
  }
  return parsed;
}

export function parseDataEntryLayout(settings: unknown): DataEntryLayout {
  return { steps: parseLayoutSteps(settings), toolFields: parseToolFieldSpecs(settings) };
}

// ---- Field enumeration ------------------------------------------------------

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim() !== "") return value.trim();
  if (isRecord(value)) {
    const code = value.code;
    if (typeof code === "string" && code.trim() !== "") return code.trim();
  }
  return null;
}

function collectionEntries(
  collection: TestSchemaFieldCollection | undefined,
): Array<[string | null, TestSchemaField | string | null]> {
  if (collection === undefined || collection === null) return [];
  return Array.isArray(collection)
    ? collection.map((field) => [null, field] as [string | null, TestSchemaField | string])
    : Object.entries(collection);
}

/**
 * Enumerate one block of a definition. Deliberately tolerant in the same way
 * `TestForm.normalizeFields` is (array or map collection, descriptor or bare
 * dataType string), because the planner must see exactly the fields the form
 * will render — a field this misses would be dropped from the reordered
 * definition and vanish from the panel.
 */
function enumerateProperties(definition: TestSchemaDefinition): LayoutField[] {
  const required = requiredCodes(definition, "properties");
  const seen = new Set<string>();
  const fields: LayoutField[] = [];
  for (const [mapCode, candidate] of collectionEntries(definition.properties)) {
    const descriptor: TestSchemaField =
      typeof candidate === "string"
        ? mapCode === null
          ? { code: candidate }
          : { code: mapCode, dataType: candidate }
        : isRecord(candidate)
          ? candidate
          : mapCode === null
            ? {}
            : { code: mapCode };
    const code = textValue(descriptor.code) ?? mapCode;
    if (code === null || code.trim() === "" || seen.has(code)) continue;
    seen.add(code);
    fields.push({
      section: "properties",
      code,
      label: textValue(descriptor.name) ?? textValue(descriptor.title) ?? code,
      description: textValue(descriptor.description),
      required: descriptor.required === true || required.has(code),
      defaultValue: descriptor.defaultValue ?? descriptor.default,
    });
  }
  return fields;
}

/** Every field the generated form would render, properties block first. */
export function enumerateFields(definition: TestSchemaDefinition): LayoutField[] {
  const measurements: LayoutField[] = measurementFields(definition).map((field) => ({
    section: "results" as const,
    code: field.code,
    label: field.label,
    description: field.description,
    required: field.required,
    defaultValue: field.defaultValue,
  }));
  return [...enumerateProperties(definition), ...measurements];
}

// ---- The plan ---------------------------------------------------------------

/** The trailing group's stable key. Not a heading — see `FieldGroup.title`. */
export const OTHER_GROUP_KEY = "other";

function stepApplies(step: LayoutStep, testType: string): boolean {
  return step.testType === testType.trim().toUpperCase();
}

function stepFormula(
  step: LayoutStep,
  componentTypeCode?: string,
): { codes: string[]; resultCode: string | null } {
  const typeCode = componentTypeCode?.trim().toUpperCase();
  return typeCode === undefined || typeCode === ""
    ? { codes: step.codes, resultCode: step.resultCode }
    : (step.byTypeCode[typeCode] ?? { codes: step.codes, resultCode: step.resultCode });
}

function reemit(fields: LayoutField[], source: TestSchemaDefinition): TestSchemaField[] {
  const byCode = new Map<string, TestSchemaField>();
  for (const [mapCode, candidate] of [
    ...collectionEntries(source.properties),
    ...collectionEntries(source.results),
    ...collectionEntries(source.parameters),
  ]) {
    const descriptor: TestSchemaField =
      typeof candidate === "string"
        ? mapCode === null
          ? { code: candidate }
          : { code: mapCode, dataType: candidate }
        : isRecord(candidate)
          ? { ...candidate }
          : mapCode === null
            ? {}
            : { code: mapCode };
    const code = textValue(descriptor.code) ?? mapCode;
    if (code === null || byCode.has(code)) continue;
    byCode.set(code, { ...descriptor, code });
  }
  return fields.map((field) => byCode.get(field.code) ?? { code: field.code });
}

/**
 * Order and group one definition's fields, and lift its tool fields out.
 *
 * Fields a step does not name keep the definition's own relative order and
 * land in the trailing group — an institute that configures nothing gets
 * exactly the behaviour it had before, which is what makes this safe to apply
 * unconditionally.
 */
export function planFieldLayout(
  definition: TestSchemaDefinition,
  testType: string,
  layout: DataEntryLayout = EMPTY_LAYOUT,
  componentTypeCode?: string,
): FieldLayoutPlan {
  const applicableSteps = layout.steps.filter((step) => stepApplies(step, testType));
  const derivedCodes = new Set(
    applicableSteps
      .flatMap((step) => [
        step.resultCode,
        ...Object.values(step.byTypeCode).map((formula) => formula.resultCode),
      ])
      .filter((code): code is string => code !== null),
  );
  // A profile result_code is computed and reviewed by the server. Leaving the
  // same code in TestForm creates a second, editable value that the upload
  // later overwrites; the sheet exposes formula cells, not raw inputs.
  const enumerated = enumerateFields(definition);
  const ownsMeasurements = enumerated.some((field) => field.section === "results");
  const all = enumerated.filter((field) => !derivedCodes.has(field.code));
  const byCode = new Map(all.map((field) => [field.code, field]));
  const specs = layout.toolFields[testType.trim().toUpperCase()] ?? [];
  const toolSpecByCode = new Map(specs.map((spec) => [spec.code, spec]));

  const claimed = new Set<string>();
  const groups: FieldGroup[] = [];
  for (const step of layout.steps) {
    if (!stepApplies(step, testType)) continue;
    const fields: LayoutField[] = [];
    for (const code of stepFormula(step, componentTypeCode).codes) {
      if (derivedCodes.has(code)) continue;
      const field = byCode.get(code);
      if (field === undefined || claimed.has(code)) continue;
      claimed.add(code);
      fields.push(field);
    }
    if (fields.length > 0) {
      groups.push({ key: step.key, title: step.label, fields });
    }
  }
  const rest = all.filter((field) => !claimed.has(field.code));
  if (rest.length > 0) {
    groups.push({ key: OTHER_GROUP_KEY, title: null, fields: rest });
  }

  // A band a tool field explicitly claims, by `glue_weight_inputs` step key.
  const bandOrder = new Map(applicableSteps.map((step, index) => [step.key, index]));
  const bandTitle = new Map(applicableSteps.map((step) => [step.key, step.label]));

  const toolFields: ToolField[] = [];
  const formGroups: FieldGroup[] = [];
  for (const group of groups) {
    const kept: LayoutField[] = [];
    for (const field of group.fields) {
      const spec = toolSpecByCode.get(field.code);
      if (spec === undefined) {
        kept.push(field);
        continue;
      }
      const claimed = spec.step !== null && bandOrder.has(spec.step) ? spec.step : null;
      toolFields.push({
        ...field,
        kinds: spec.kinds,
        groupKey: claimed ?? group.key,
        groupTitle: claimed === null ? group.title : (bandTitle.get(claimed) ?? null),
      });
    }
    if (kept.length > 0) formGroups.push({ ...group, fields: kept });
  }
  // Tooling reads band by band, in the institute's own step order; anything
  // unbanded trails, so a named band never appears twice in the section.
  toolFields.sort(
    (a, b) =>
      (bandOrder.get(a.groupKey) ?? Number.MAX_SAFE_INTEGER) -
      (bandOrder.get(b.groupKey) ?? Number.MAX_SAFE_INTEGER),
  );

  const ordered = formGroups.flatMap((group) => group.fields);
  // Whether this plan owns the measurement block. When it does, `parameters`
  // must be cleared as well: `TestForm` falls through to `parameters` for an
  // empty `results`, so a definition whose only measurement fields were all
  // lifted out as tool fields would otherwise render them again — as the free
  // text inputs this module exists to replace.
  const emitted: TestSchemaDefinition = {
    ...definition,
    properties: reemit(
      ordered.filter((field) => field.section === "properties"),
      definition,
    ),
    results: reemit(
      ordered.filter((field) => field.section === "results"),
      definition,
    ),
  };
  if (ownsMeasurements) emitted.parameters = undefined;
  return { groups: formGroups, toolFields, definition: emitted };
}

// ---- Tool registry helpers --------------------------------------------------

/**
 * How a tool reads in every picker in the app.
 *
 * The sheet names tools by their shop-floor sticker — colour and number, e.g.
 * a module jig known as "#3 (orange)" — and keeps the serial in a separate
 * inventory tab. So: the human label leads and the serial follows, because
 * the serial is what gets written to the PDB and an operator has to be able
 * to check it without leaving the field.
 */
export function toolOptionLabel(tool: Tool): string {
  return `${tool.label ?? tool.code} · ${tool.code}`;
}

/** Whether a registry tool may be offered for one tool field. */
export function toolMatchesField(tool: Tool, field: ToolField, componentTypeCode?: string): boolean {
  if (tool.status !== "active") return false;
  // API writes are canonical lower-case, but older/tool-sync profile data can
  // predate that normalization. A harmless `JIG` spelling must not empty a
  // picker whose configured filter was correctly normalized to `jig`.
  if (field.kinds.length > 0 && !field.kinds.includes(tool.kind.trim().toLowerCase())) return false;
  if (componentTypeCode === undefined || componentTypeCode.trim() === "") return true;
  // An empty compatibility list is "not stated", not "fits nothing": the
  // registry mirrors PDB tools whose type list is frequently blank, and
  // hiding those would empty the dropdown an operator is holding the tool for.
  if (tool.compatible_types.length === 0) return true;
  return tool.compatible_types.includes(componentTypeCode.trim());
}

export function toolFieldCandidates(
  tools: readonly Tool[],
  field: ToolField,
  componentTypeCode?: string,
): Tool[] {
  return tools.filter((tool) => toolMatchesField(tool, field, componentTypeCode));
}
