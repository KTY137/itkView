// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-2c6e2e305954
import { useEffect, useId, useMemo, useState } from "react";
import type { FormEvent } from "react";
import type {
  TestSchemaDefinition,
  TestSchemaField,
  TestSchemaFieldCollection,
  TestTypeSchema,
} from "./api";

export type { TestTypeSchema } from "./api";

export type TestFormLabels = {
  runNumber: string;
  date: string;
  passed: string;
  problems: string;
  properties: string;
  results: string;
  submit: string;
  booleanUnset: string;
  booleanTrue: string;
  booleanFalse: string;
  arrayHint: string;
  /**
   * Shown instead of "<results> is required" when the schema itself declares
   * no measurement field this form can capture — the person's input is not
   * the problem, so the message must not read like it is. Optional so a label
   * bundle keeps type-checking without it; `DEFAULT_NO_MEASUREMENT_FIELDS`
   * (English, like every default locale string) is used until one is wired.
   */
  noMeasurementFields?: (testType: string) => string;
  requiredField: (field: string) => string;
  invalidNumber: (field: string, line?: number) => string;
  invalidInteger: (field: string, line?: number) => string;
  invalidBoolean: (field: string, line?: number) => string;
  unsupportedType: (field: string, dataType: string) => string;
};

export type TestFormFieldValue = string | number | boolean | Array<string | number | boolean>;

export type TestFormSubmitPayload = {
  component: string;
  testType: string;
  runNumber: string;
  date: string;
  passed: boolean;
  problems: boolean;
  properties: Record<string, TestFormFieldValue>;
  results: Record<string, TestFormFieldValue>;
};

export type TestFormProps = {
  component: string;
  schema: TestTypeSchema;
  labels: TestFormLabels;
  onSubmit: (payload: TestFormSubmitPayload) => void | Promise<unknown>;
  disabled?: boolean;
  variant?: "default" | "worksheet";
  cancelLabel?: string;
  onCancel?: () => void;
};

type FieldKind = "string" | "float" | "integer" | "boolean" | "unsupported";
/**
 * The two blocks of a submitted run — the payload keys `uploadTestRunResults`
 * expects. `results` is itkFlow's name for the measurement block regardless of
 * which key the *definition* spelled it under (see `measurementFields`).
 */
type FieldSection = "properties" | "results";

export type ManualEntryBlockerReason =
  | "required-unsupported-type"
  | "unsupported-array-shape"
  | "no-enterable-measurement";

export type ManualEntryBlocker = {
  section: FieldSection;
  code: string;
  label: string;
  dataType: string;
  arrayDimensions: number | null;
  reason: ManualEntryBlockerReason;
};

export type ManualEntryCapability = {
  canEnter: boolean;
  blockers: ManualEntryBlocker[];
};

/** English fallback for `TestFormLabels.noMeasurementFields`. */
export const DEFAULT_NO_MEASUREMENT_FIELDS = (testType: string): string =>
  `${testType} declares no measurement field that can be entered here, so this ` +
  `form cannot record a run for it. Upload a result file for this test type instead.`;

type NormalizedField = {
  code: string;
  label: string;
  description: string | null;
  kind: FieldKind;
  rawDataType: string;
  isArray: boolean;
  arrayDimensions: number | null;
  arrayShapeSupported: boolean;
  required: boolean;
  defaultValue: unknown;
};

type NormalizedSchema = Record<FieldSection, NormalizedField[]>;
type DraftValues = Record<FieldSection, Record<string, string>>;
type ValidationErrors = Record<string, string>;

type ParsedField =
  | { status: "empty" }
  | { status: "error"; message: string }
  | { status: "value"; value: TestFormFieldValue };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function textValue(value: unknown): string | null {
  if (typeof value === "string" && value.trim() !== "") {
    return value.trim();
  }
  if (isRecord(value)) {
    const code = value.code;
    if (typeof code === "string" && code.trim() !== "") {
      return code.trim();
    }
  }
  return null;
}

function fieldKind(rawDataType: string): FieldKind {
  switch (rawDataType.toLowerCase()) {
    case "string":
      return "string";
    case "float":
      return "float";
    case "integer":
      return "integer";
    case "boolean":
      return "boolean";
    default:
      return "unsupported";
  }
}

function arrayShape(
  descriptor: TestSchemaField,
  isArray: boolean,
): { dimensions: number | null; supported: boolean } {
  if (!isArray) return { dimensions: null, supported: true };
  const raw = descriptor.arrayDimensions ?? descriptor.array_dimensions;
  // A missing/null dimension is how a number of otherwise ordinary one-
  // dimensional PDB arrays are mirrored. It is safe to capture those as one
  // value per line. Anything explicitly more complex (or malformed) stays
  // file-only: flattening it would silently change the payload shape.
  if (raw === undefined || raw === null) return { dimensions: null, supported: true };
  if (typeof raw !== "number" || !Number.isInteger(raw) || raw < 0) {
    return { dimensions: null, supported: false };
  }
  return { dimensions: raw, supported: raw <= 1 };
}

function fieldCanEnter(field: NormalizedField): boolean {
  return field.kind !== "unsupported" && field.arrayShapeSupported;
}

/**
 * Which field codes in one section (`properties`/`results`) are required by
 * the schema's `required` block. Exported so the worksheet's edit strip
 * (ModuleWorksheet.tsx) can determine, ahead of rendering `TestForm`, whether
 * a value it cannot prefill would otherwise become a silent dead end (review
 * finding C1) — using the exact same required-ness rules `TestForm` itself
 * applies, rather than a second, divergence-prone copy of them.
 */
export function requiredCodes(definition: TestSchemaDefinition, section: FieldSection): Set<string> {
  const required = definition.required;
  if (Array.isArray(required)) {
    return new Set(required.filter((code): code is string => typeof code === "string"));
  }
  if (!isRecord(required)) {
    return new Set();
  }

  // The measurement block is spelled `results` by itkFlow and `parameters` by
  // the PDB (see `measurementFields`), so a scoped `required` map is consulted
  // under both spellings for that one section.
  const keys = section === "results" ? (["results", "parameters"] as const) : ([section] as const);
  const scopedCodes = new Set<string>();
  let scopedFound = false;
  for (const key of keys) {
    const scoped = required[key];
    if (Array.isArray(scoped)) {
      scopedFound = true;
      for (const code of scoped) {
        if (typeof code === "string") scopedCodes.add(code);
      }
    } else if (isRecord(scoped)) {
      scopedFound = true;
      for (const [code, value] of Object.entries(scoped)) {
        if (value === true) scopedCodes.add(code);
      }
    }
  }
  if (scopedFound) {
    return scopedCodes;
  }
  // Some map-shaped definitions put the flags directly under `required`
  // instead of nesting them below `properties` / `results`.
  return new Set(
    Object.entries(required)
      .filter(([, value]) => value === true)
      .map(([code]) => code),
  );
}

const EMPTY_REQUIRED: ReadonlySet<string> = new Set<string>();

function normalizeFields(
  collection: TestSchemaFieldCollection | null | undefined,
  required: ReadonlySet<string>,
): NormalizedField[] {
  // `null` as well as `undefined`: a mirrored definition is raw PDB JSON, and
  // an explicit `"results": null` would otherwise reach `Object.entries` and
  // throw during render.
  if (collection === undefined || collection === null) {
    return [];
  }

  const candidates: Array<[string | null, TestSchemaField | string | null]> = Array.isArray(
    collection,
  )
    ? collection.map((field) => [null, field])
    : Object.entries(collection);
  const seen = new Set<string>();
  const fields: NormalizedField[] = [];

  for (const [mapCode, candidate] of candidates) {
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
    if (code === null || code.trim() === "" || seen.has(code)) {
      continue;
    }
    seen.add(code);

    const rawDataType =
      textValue(descriptor.dataType) ??
      textValue(descriptor.data_type) ??
      textValue(descriptor.type) ??
      "";
    const rawValueType =
      textValue(descriptor.valueType) ?? textValue(descriptor.value_type) ?? "single";
    const isArray = rawValueType.toLowerCase() === "array";
    const shape = arrayShape(descriptor, isArray);
    fields.push({
      code,
      label: textValue(descriptor.name) ?? textValue(descriptor.title) ?? code,
      description: textValue(descriptor.description),
      kind: fieldKind(rawDataType),
      rawDataType,
      isArray,
      arrayDimensions: shape.dimensions,
      arrayShapeSupported: shape.supported,
      required: descriptor.required === true || required.has(code),
      defaultValue: descriptor.defaultValue ?? descriptor.default,
    });
  }

  return fields;
}

/**
 * The measurement fields of one definition — the block that becomes the run's
 * `results` payload.
 *
 * Two vocabularies name the same block. A PDB test-type definition
 * (`getTestTypeByCode`, mirrored raw) calls it **`parameters`**: every MODULE
 * definition in a live mirror carries no `results` key at all and lists all of
 * its measurement fields — GLUE_WEIGHT's 19 `GW_*` weights, VISUAL_INSPECTION's
 * 18 strings — under `parameters`. itkFlow calls it **`results`**: that is the
 * `uploadTestRunResults` payload key, and the key a caller writes when it
 * rewrites a definition before rendering (the worksheet edit strip re-emits
 * `{...definition, properties, results}` with the previous run's values).
 *
 * PRECEDENCE, deliberately: `results` wins — but only while it actually
 * carries fields; an absent, null or empty `results` falls through to
 * `parameters`. Exactly one block is ever used, so a definition holding both
 * never renders a field twice.
 *   - `results` first, because when it is populated it is either a definition
 *     that genuinely uses that key or a caller-rewritten one whose fields
 *     carry prefilled `defaultValue`s; preferring `parameters` there would
 *     throw those away.
 *   - "carries fields" rather than "is present", because a rewriter can
 *     legitimately emit `results: []` for a parameters-only definition — and
 *     reading that as "this test type has no measurements" is exactly how an
 *     empty form survives one layer along.
 */
export function measurementCollection(definition: TestSchemaDefinition): {
  key: "results" | "parameters";
  collection: TestSchemaFieldCollection | null | undefined;
} {
  const declared = definition.results;
  // "Carries fields", not "is defined": normalizing answers that question with
  // the same rules the form itself applies.
  return normalizeFields(declared, EMPTY_REQUIRED).length > 0
    ? { key: "results", collection: declared }
    : { key: "parameters", collection: definition.parameters };
}

/** The measurement fields of one definition, normalized for rendering.
 * Exported alongside `measurementCollection` so a caller that has to touch the
 * raw collection (prefilling a previous run into it) resolves the same block
 * this form will render, instead of assuming a key. */
export function measurementFields(definition: TestSchemaDefinition): NormalizedField[] {
  return normalizeFields(
    measurementCollection(definition).collection,
    requiredCodes(definition, "results"),
  );
}

function normalizeSchema(definition: TestSchemaDefinition): NormalizedSchema {
  return {
    properties: normalizeFields(
      definition.properties,
      requiredCodes(definition, "properties"),
    ),
    results: measurementFields(definition),
  };
}

/**
 * Whether the generated controls can safely create a complete manual run for
 * this exact definition. This is deliberately fail-closed and shared by both
 * entry surfaces: required object/testRun fields block, and primitive arrays
 * are enterable only when their declared shape is missing or at most 1-D.
 */
export function manualEntryCapability(
  definition: TestSchemaDefinition,
): ManualEntryCapability {
  const fields = normalizeSchema(definition);
  const blockers: ManualEntryBlocker[] = [];
  const seen = new Set<string>();

  function addBlocker(
    section: FieldSection,
    field: NormalizedField,
    reason: ManualEntryBlockerReason,
  ) {
    const key = `${section}:${field.code}`;
    if (seen.has(key)) return;
    seen.add(key);
    blockers.push({
      section,
      code: field.code,
      label: field.label,
      dataType: field.rawDataType,
      arrayDimensions: field.arrayDimensions,
      reason,
    });
  }

  for (const section of ["properties", "results"] as const) {
    for (const field of fields[section]) {
      if (field.kind !== "unsupported" && !field.arrayShapeSupported) {
        addBlocker(section, field, "unsupported-array-shape");
        continue;
      }
      if (!field.required || fieldCanEnter(field)) continue;
      addBlocker(
        section,
        field,
        "required-unsupported-type",
      );
    }
  }

  if (!fields.results.some(fieldCanEnter)) {
    const unavailableResults = fields.results.filter((field) => !fieldCanEnter(field));
    if (unavailableResults.length === 0) {
      blockers.push({
        section: "results",
        code: "results",
        label: "Results",
        dataType: "",
        arrayDimensions: null,
        reason: "no-enterable-measurement",
      });
    } else {
      for (const field of unavailableResults) {
        addBlocker("results", field, "no-enterable-measurement");
      }
    }
  }

  return { canEnter: blockers.length === 0, blockers };
}

/** Compact, deterministic field list for the two blocking notices. */
export function manualEntryBlockerSummary(
  capability: ManualEntryCapability,
  limit = 6,
): string {
  const names = capability.blockers.map((field) =>
    field.label === field.code ? field.code : `${field.label} (${field.code})`,
  );
  const visible = names.slice(0, Math.max(1, limit));
  const remaining = names.length - visible.length;
  return remaining > 0 ? `${visible.join(", ")} (+${remaining})` : visible.join(", ");
}

function initialFieldValue(field: NormalizedField): string {
  const value = field.defaultValue;
  if (Array.isArray(value)) {
    return value.map((entry) => String(entry)).join("\n");
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return "";
}

function initialDraft(schema: NormalizedSchema): DraftValues {
  return {
    properties: Object.fromEntries(
      schema.properties.map((field) => [field.code, initialFieldValue(field)]),
    ),
    results: Object.fromEntries(
      schema.results.map((field) => [field.code, initialFieldValue(field)]),
    ),
  };
}

function parseScalar(
  field: NormalizedField,
  rawValue: string,
  labels: TestFormLabels,
  line?: number,
): ParsedField {
  const value = rawValue.trim();
  if (value === "") {
    return field.required
      ? { status: "error", message: labels.requiredField(field.label) }
      : { status: "empty" };
  }

  switch (field.kind) {
    case "string":
      return { status: "value", value };
    case "float": {
      const parsed = Number(value.replace(",", "."));
      return LOCALIZED_DECIMAL_NUMBER.test(value) && Number.isFinite(parsed)
        ? { status: "value", value: parsed }
        : { status: "error", message: labels.invalidNumber(field.label, line) };
    }
    case "integer": {
      const parsed = Number(value);
      return DECIMAL_NUMBER.test(value) && Number.isSafeInteger(parsed)
        ? { status: "value", value: parsed }
        : { status: "error", message: labels.invalidInteger(field.label, line) };
    }
    case "boolean": {
      const normalized = value.toLowerCase();
      if (normalized === "true" || normalized === "false") {
        return { status: "value", value: normalized === "true" };
      }
      return { status: "error", message: labels.invalidBoolean(field.label, line) };
    }
    case "unsupported":
      return field.required
        ? {
            status: "error",
            message: labels.unsupportedType(field.label, field.rawDataType),
          }
        : { status: "empty" };
  }
}

const DECIMAL_NUMBER = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/u;
const LOCALIZED_DECIMAL_NUMBER = /^[+-]?(?:\d+(?:[.,]\d*)?|[.,]\d+)(?:[eE][+-]?\d+)?$/u;

function emptyArrayLineError(
  field: NormalizedField,
  labels: TestFormLabels,
  line: number,
): string {
  switch (field.kind) {
    case "float":
      return labels.invalidNumber(field.label, line);
    case "integer":
      return labels.invalidInteger(field.label, line);
    case "boolean":
      return labels.invalidBoolean(field.label, line);
    case "string":
    case "unsupported":
      return labels.requiredField(field.label);
  }
}

function parseField(
  field: NormalizedField,
  rawValue: string,
  labels: TestFormLabels,
): ParsedField {
  if (!fieldCanEnter(field)) {
    return field.required
      ? { status: "error", message: labels.unsupportedType(field.label, field.rawDataType) }
      : { status: "empty" };
  }
  if (!field.isArray) {
    return parseScalar(field, rawValue, labels);
  }

  const lines = rawValue
    .split(/\r?\n/u)
    .map((value, index) => ({ value: value.trim(), line: index + 1 }));
  while (lines[0]?.value === "") {
    lines.shift();
  }
  while (lines.at(-1)?.value === "") {
    lines.pop();
  }
  if (lines.length === 0) {
    return field.required
      ? { status: "error", message: labels.requiredField(field.label) }
      : { status: "empty" };
  }

  const parsedValues: Array<string | number | boolean> = [];
  for (const entry of lines) {
    if (entry.value === "") {
      return { status: "error", message: emptyArrayLineError(field, labels, entry.line) };
    }
    const parsed = parseScalar(field, entry.value, labels, entry.line);
    if (parsed.status === "error") {
      return parsed;
    }
    if (parsed.status === "value" && !Array.isArray(parsed.value)) {
      parsedValues.push(parsed.value);
    }
  }
  return { status: "value", value: parsedValues };
}

function canonicalDate(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value.trim() : parsed.toISOString();
}

function errorKey(section: FieldSection, code: string): string {
  return `${section}:${code}`;
}

function safeIdPart(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/gu, "-");
}

export default function TestForm({
  component,
  schema,
  labels,
  onSubmit,
  disabled = false,
  variant = "default",
  cancelLabel,
  onCancel,
}: TestFormProps) {
  const idPrefix = safeIdPart(useId());
  const schemaKey = JSON.stringify([
    schema.id,
    schema.component_type,
    schema.test_code,
    schema.synced_at,
    schema.schema,
  ]);
  const fields = useMemo(() => normalizeSchema(schema.schema), [schemaKey]);
  // A schema can declare measurement fields that no control can hold — a
  // PDB `testRun` reference, an `object` map. If none of them is enterable,
  // the run cannot be completed here, and that is the schema's doing.
  const hasEnterableResult = fields.results.some(fieldCanEnter);
  const noMeasurementFieldsMessage = (
    labels.noMeasurementFields ?? DEFAULT_NO_MEASUREMENT_FIELDS
  )(schema.test_code.trim());
  const [runNumber, setRunNumber] = useState("");
  const [date, setDate] = useState("");
  const [passed, setPassed] = useState(true);
  const [problems, setProblems] = useState(false);
  const [draft, setDraft] = useState<DraftValues>(() => initialDraft(fields));
  const [errors, setErrors] = useState<ValidationErrors>({});

  useEffect(() => {
    setRunNumber("");
    setDate("");
    setPassed(true);
    setProblems(false);
    setDraft(initialDraft(fields));
    setErrors({});
  }, [component, fields]);

  function updateDraft(section: FieldSection, code: string, value: string) {
    setDraft((current) => ({
      ...current,
      [section]: { ...current[section], [code]: value },
    }));
    setErrors((current) => {
      const key = errorKey(section, code);
      if (!(key in current)) {
        return current;
      }
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors: ValidationErrors = {};
    const trimmedRunNumber = runNumber.trim();
    const trimmedDate = date.trim();
    if (trimmedRunNumber === "") {
      nextErrors.runNumber = labels.requiredField(labels.runNumber);
    }
    if (trimmedDate === "") {
      nextErrors.date = labels.requiredField(labels.date);
    }

    const values: Record<FieldSection, Record<string, TestFormFieldValue>> = {
      properties: {},
      results: {},
    };
    for (const section of ["properties", "results"] as const) {
      for (const field of fields[section]) {
        const parsed = parseField(field, draft[section][field.code] ?? "", labels);
        if (parsed.status === "error") {
          nextErrors[errorKey(section, field.code)] = parsed.message;
        } else if (parsed.status === "value") {
          values[section][field.code] = parsed.value;
        }
      }
    }
    const hasResultFieldError = Object.keys(nextErrors).some((key) =>
      key.startsWith("results:"),
    );
    if (Object.keys(values.results).length === 0 && !hasResultFieldError) {
      // A run without a single measured value is still refused — but only the
      // enterable case is the person's to fix, so only that one is phrased as
      // a missing input.
      nextErrors.results = hasEnterableResult
        ? labels.requiredField(labels.results)
        : noMeasurementFieldsMessage;
    }

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      const firstError = Object.keys(nextErrors)[0];
      let controlName: string | null = null;
      if (firstError === "runNumber" || firstError === "date") {
        controlName = firstError;
      } else if (firstError === "results") {
        const firstResult = fields.results.find(fieldCanEnter);
        controlName = firstResult === undefined ? null : `results.${firstResult.code}`;
      } else {
        const separator = firstError.indexOf(":");
        if (separator > 0) {
          controlName = `${firstError.slice(0, separator)}.${firstError.slice(separator + 1)}`;
        }
      }
      const control =
        controlName === null ? null : event.currentTarget.elements.namedItem(controlName);
      if (control instanceof HTMLElement) {
        // `noValidate` keeps locale-aware parsing under our control, so it also
        // makes focus management our responsibility. Keep a long worksheet
        // form from appearing to do nothing when its first error is above the
        // viewport.
        control.focus({ preventScroll: true });
        control.scrollIntoView?.({ block: "nearest" });
      }
      return;
    }

    void onSubmit({
      component: component.trim(),
      testType: schema.test_code.trim(),
      runNumber: trimmedRunNumber,
      date: canonicalDate(trimmedDate),
      passed,
      problems,
      properties: values.properties,
      results: values.results,
    });
  }

  function renderField(section: FieldSection, field: NormalizedField, index: number) {
    const inputId = `${idPrefix}-${section}-${index}-${safeIdPart(field.code)}`;
    const hintId = `${inputId}-hint`;
    const validationId = `${inputId}-error`;
    const error = errors[errorKey(section, field.code)];
    const describedBy = [
      field.description === null && !field.isArray && fieldCanEnter(field)
        ? null
        : hintId,
      error === undefined ? null : validationId,
    ]
      .filter((value): value is string => value !== null)
      .join(" ");
    const value = draft[section][field.code] ?? "";
    // The worksheet is intentionally dense: its schema may contain dozens of
    // measurements in a narrow detail column. Keep descriptive copy in the
    // accessibility tree and expose it as a native hover title, without
    // repeating every label as another permanently visible line. Array and
    // unsupported-type guidance remains visible because it changes how (or
    // whether) the value can be entered.
    const quietDescription =
      variant === "worksheet" &&
      field.description !== null &&
      !field.isArray &&
      fieldCanEnter(field);
    const common = {
      id: inputId,
      name: `${section}.${field.code}`,
      value,
      disabled,
      required: field.required && fieldCanEnter(field),
      "aria-invalid": error === undefined ? undefined : true,
      "aria-describedby": describedBy === "" ? undefined : describedBy,
      title: quietDescription ? field.description ?? undefined : undefined,
    } as const;

    let control;
    if (!fieldCanEnter(field)) {
      control = <input {...common} className="text-input" readOnly />;
    } else if (field.isArray) {
      control = (
        <textarea
          {...common}
          className="text-input phase4-textarea mono"
          rows={4}
          inputMode={field.kind === "float" ? "decimal" : undefined}
          onChange={(event) => updateDraft(section, field.code, event.target.value)}
        />
      );
    } else if (field.kind === "boolean") {
      control = (
        <select
          {...common}
          className="select-input"
          onChange={(event) => updateDraft(section, field.code, event.target.value)}
        >
          <option value="">{labels.booleanUnset}</option>
          <option value="true">{labels.booleanTrue}</option>
          <option value="false">{labels.booleanFalse}</option>
        </select>
      );
    } else {
      control = (
        <input
          {...common}
          className="text-input"
          // A float is deliberately NOT `type="number"`. `parseScalar` accepts a
          // comma as the decimal separator (mixed-locale labs write 0,166), but
          // a numeric input rejects the comma in the browser before the parser
          // ever sees it — the operator's keystroke is simply swallowed. Text
          // plus `inputMode="decimal"` still raises the numeric keypad on a
          // tablet, and validation stays with the parser that understands both
          // separators. Integers keep the stepper; they have no separator.
          type={field.kind === "integer" ? "number" : "text"}
          inputMode={field.kind === "float" ? "decimal" : undefined}
          step={field.kind === "integer" ? "1" : undefined}
          onChange={(event) => updateDraft(section, field.code, event.target.value)}
        />
      );
    }

    return (
      <label
        className={field.isArray ? "phase4-field phase4-field-wide" : "phase4-field"}
        htmlFor={inputId}
        key={field.code}
      >
        <span className="field-label">
          {field.label}
          {field.required && <span aria-hidden="true"> *</span>}
        </span>
        {control}
        {(field.description !== null || field.isArray || !fieldCanEnter(field)) && (
          <small className={quietDescription ? "sr-only" : "muted"} id={hintId}>
            {!fieldCanEnter(field)
              ? labels.unsupportedType(field.label, field.rawDataType)
              : (
                  <>
                    {field.description}
                    {field.description !== null && field.isArray && <br />}
                    {field.isArray && labels.arrayHint}
                  </>
                )}
          </small>
        )}
        {error !== undefined && (
          <small className="error-text" id={validationId} role="alert">
            {error}
          </small>
        )}
      </label>
    );
  }

  return (
    <form
      className={variant === "worksheet" ? "phase4-form phase4-form-worksheet" : "phase4-form"}
      onSubmit={handleSubmit}
      noValidate
    >
      <div className="phase4-form-grid">
        <label className="phase4-field" htmlFor={`${idPrefix}-run-number`}>
          <span className="field-label">
            {labels.runNumber}
            <span aria-hidden="true"> *</span>
          </span>
          <input
            className="text-input"
            id={`${idPrefix}-run-number`}
            name="runNumber"
            value={runNumber}
            disabled={disabled}
            required
            aria-invalid={errors.runNumber === undefined ? undefined : true}
            aria-describedby={errors.runNumber === undefined ? undefined : `${idPrefix}-run-error`}
            onChange={(event) => {
              setRunNumber(event.target.value);
              setErrors((current) => {
                if (current.runNumber === undefined) return current;
                const next = { ...current };
                delete next.runNumber;
                return next;
              });
            }}
          />
          {errors.runNumber !== undefined && (
            <small className="error-text" id={`${idPrefix}-run-error`} role="alert">
              {errors.runNumber}
            </small>
          )}
        </label>
        <label className="phase4-field" htmlFor={`${idPrefix}-date`}>
          <span className="field-label">
            {labels.date}
            <span aria-hidden="true"> *</span>
          </span>
          <input
            className="text-input"
            id={`${idPrefix}-date`}
            name="date"
            type="datetime-local"
            value={date}
            disabled={disabled}
            required
            aria-invalid={errors.date === undefined ? undefined : true}
            aria-describedby={errors.date === undefined ? undefined : `${idPrefix}-date-error`}
            onChange={(event) => {
              setDate(event.target.value);
              setErrors((current) => {
                if (current.date === undefined) return current;
                const next = { ...current };
                delete next.date;
                return next;
              });
            }}
          />
          {errors.date !== undefined && (
            <small className="error-text" id={`${idPrefix}-date-error`} role="alert">
              {errors.date}
            </small>
          )}
        </label>
        <label className="phase4-field" htmlFor={`${idPrefix}-passed`}>
          <span className="field-label">{labels.passed}</span>
          <select
            className="select-input"
            id={`${idPrefix}-passed`}
            name="passed"
            value={passed ? "true" : "false"}
            disabled={disabled}
            onChange={(event) => setPassed(event.target.value === "true")}
          >
            <option value="true">{labels.booleanTrue}</option>
            <option value="false">{labels.booleanFalse}</option>
          </select>
        </label>
        <label className="phase4-field" htmlFor={`${idPrefix}-problems`}>
          <span className="field-label">{labels.problems}</span>
          <select
            className="select-input"
            id={`${idPrefix}-problems`}
            name="problems"
            value={problems ? "true" : "false"}
            disabled={disabled}
            onChange={(event) => setProblems(event.target.value === "true")}
          >
            <option value="false">{labels.booleanFalse}</option>
            <option value="true">{labels.booleanTrue}</option>
          </select>
        </label>
      </div>

      {fields.properties.length > 0 && (
        <section className="phase4-subsection" aria-labelledby={`${idPrefix}-properties-title`}>
          <h3 className="section-title" id={`${idPrefix}-properties-title`}>
            {labels.properties}
          </h3>
          <div className="phase4-form-grid">
            {fields.properties.map((field, index) => renderField("properties", field, index))}
          </div>
        </section>
      )}

      {fields.results.length > 0 && (
        <section className="phase4-subsection" aria-labelledby={`${idPrefix}-results-title`}>
          <h3 className="section-title" id={`${idPrefix}-results-title`}>
            {labels.results}
          </h3>
          <div className="phase4-form-grid">
            {fields.results.map((field, index) => renderField("results", field, index))}
          </div>
        </section>
      )}

      {errors.results !== undefined ? (
        <div className="error-banner" role="alert">
          <span>{errors.results}</span>
        </div>
      ) : (
        !hasEnterableResult && (
          // Say it before the submit is attempted, not only after it fails:
          // nothing on this form can make such a schema submittable.
          <div className="info-banner" role="status">
            <span>{noMeasurementFieldsMessage}</span>
          </div>
        )
      )}

      <div className="phase4-form-actions">
        {onCancel !== undefined && cancelLabel !== undefined && (
          <button className="btn" type="button" disabled={disabled} onClick={onCancel}>
            {cancelLabel}
          </button>
        )}
        <button className="btn primary" type="submit" disabled={disabled}>
          {labels.submit}
        </button>
      </div>
    </form>
  );
}
