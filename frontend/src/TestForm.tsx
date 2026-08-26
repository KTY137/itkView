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
};

type FieldKind = "string" | "float" | "integer" | "boolean" | "unsupported";
type FieldSection = "properties" | "results";

type NormalizedField = {
  code: string;
  label: string;
  description: string | null;
  kind: FieldKind;
  rawDataType: string;
  isArray: boolean;
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

function requiredCodes(definition: TestSchemaDefinition, section: FieldSection): Set<string> {
  const required = definition.required;
  if (Array.isArray(required)) {
    return new Set(required.filter((code): code is string => typeof code === "string"));
  }
  if (!isRecord(required)) {
    return new Set();
  }

  const scoped = required[section];
  if (Array.isArray(scoped)) {
    return new Set(scoped.filter((code): code is string => typeof code === "string"));
  }
  if (isRecord(scoped)) {
    return new Set(
      Object.entries(scoped)
        .filter(([, value]) => value === true)
        .map(([code]) => code),
    );
  }
  // Some map-shaped definitions put the flags directly under `required`
  // instead of nesting them below `properties` / `results`.
  return new Set(
    Object.entries(required)
      .filter(([, value]) => value === true)
      .map(([code]) => code),
  );
}

function normalizeFields(
  collection: TestSchemaFieldCollection | undefined,
  required: Set<string>,
): NormalizedField[] {
  if (collection === undefined) {
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
    fields.push({
      code,
      label: textValue(descriptor.name) ?? textValue(descriptor.title) ?? code,
      description: textValue(descriptor.description),
      kind: fieldKind(rawDataType),
      rawDataType,
      isArray: rawValueType.toLowerCase() === "array",
      required: descriptor.required === true || required.has(code),
      defaultValue: descriptor.defaultValue ?? descriptor.default,
    });
  }

  return fields;
}

function normalizeSchema(definition: TestSchemaDefinition): NormalizedSchema {
  return {
    properties: normalizeFields(
      definition.properties,
      requiredCodes(definition, "properties"),
    ),
    results: normalizeFields(definition.results, requiredCodes(definition, "results")),
  };
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
      const parsed = Number(value);
      return DECIMAL_NUMBER.test(value) && Number.isFinite(parsed)
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
  if (field.kind === "unsupported") {
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
      nextErrors.results = labels.requiredField(labels.results);
    }

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
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
      field.description === null && !field.isArray && field.kind !== "unsupported"
        ? null
        : hintId,
      error === undefined ? null : validationId,
    ]
      .filter((value): value is string => value !== null)
      .join(" ");
    const value = draft[section][field.code] ?? "";
    const common = {
      id: inputId,
      name: `${section}.${field.code}`,
      value,
      disabled,
      required: field.required && field.kind !== "unsupported",
      "aria-invalid": error === undefined ? undefined : true,
      "aria-describedby": describedBy === "" ? undefined : describedBy,
    } as const;

    let control;
    if (field.kind === "unsupported") {
      control = <input {...common} className="text-input" readOnly />;
    } else if (field.isArray) {
      control = (
        <textarea
          {...common}
          className="text-input phase4-textarea mono"
          rows={4}
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
          type={field.kind === "string" ? "text" : "number"}
          step={field.kind === "float" ? "any" : field.kind === "integer" ? "1" : undefined}
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
        {(field.description !== null || field.isArray || field.kind === "unsupported") && (
          <small className="muted" id={hintId}>
            {field.kind === "unsupported"
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
    <form className="phase4-form" onSubmit={handleSubmit} noValidate>
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

      {errors.results !== undefined && (
        <div className="error-banner" role="alert">
          <span>{errors.results}</span>
        </div>
      )}

      <div className="phase4-form-actions">
        <button className="btn primary" type="submit" disabled={disabled}>
          {labels.submit}
        </button>
      </div>
    </form>
  );
}
