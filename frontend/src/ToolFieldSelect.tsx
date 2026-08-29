// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-3b9104f569a0
/**
 * A schema field that the institute profile identifies as a jig, pickup tool
 * or panel is chosen from the registry, never typed as unconstrained text.
 *
 * The production sheet uses serial-number validation for the dedicated
 * hybrid jig/pickup rows (28/29). Its later combined tooling rows (30/38) are
 * not equivalent dropdowns, and GLUE_WEIGHT has no PDB jig/pickup property;
 * those glue-tool records need the planned local neighbouring store instead.
 * A real PDB-backed example is MODULE_BOW.JIG. Where that generated form left
 * the same decision as free text, the mirrored evidence shows what happens:
 * one institute's 28 MODULE_BOW runs carry the same jig under three spellings
 * (`Module Assembly Jig`, `Module Metrology Jig`, `1`), which is a wrong PDB
 * property that nobody can even detect afterwards.
 *
 * Two entry paths, both kept:
 *   - the dropdown, for the operator working from the list, fully keyboard
 *     operable because it is a native `<select>`;
 *   - the scan box, for the operator holding the tool — a keyboard-wedge
 *     barcode/RFID read ends in Enter and submits, which is faster than any
 *     dropdown and must not be taken away by adding one.
 *
 * A value that is not in the registry is never silently dropped or corrected.
 * It stays selected, labelled as unknown, so an operator sees the old free
 * text and decides — instead of the form quietly changing a stored value.
 */
import { useId, useState } from "react";
import type { FormEvent } from "react";

import type { Tool } from "./api";
import { toolFieldCandidates, toolOptionLabel } from "./fieldLayout";
import type { ToolField } from "./fieldLayout";

export type ToolFieldLabels = {
  choose: string;
  /** Shown for a stored value that no registry tool matches. */
  unknownValue: (value: string) => string;
  scanLabel: (field: string) => string;
  scanPlaceholder: string;
  scan: string;
  scanNoMatch: (value: string) => string;
  noCandidates: string;
  registryError: (error: string) => string;
  required: string;
};

export type ToolFieldSelectProps = {
  field: ToolField;
  tools: readonly Tool[];
  componentTypeCode?: string;
  /** The tool code that will be submitted; `""` when nothing is chosen. */
  value: string;
  onChange: (value: string) => void;
  labels: ToolFieldLabels;
  disabled?: boolean;
  invalid?: boolean;
};

/** Local resolution of a scanned code: printed tool code or RFID, either case. */
function matchScan(tools: readonly Tool[], scanned: string): Tool | null {
  const needle = scanned.trim().toUpperCase();
  if (needle === "") return null;
  return (
    tools.find(
      (tool) =>
        tool.code.trim().toUpperCase() === needle ||
        (tool.rfid !== null && tool.rfid.trim().toUpperCase() === needle),
    ) ?? null
  );
}

export default function ToolFieldSelect({
  field,
  tools,
  componentTypeCode,
  value,
  onChange,
  labels,
  disabled = false,
  invalid = false,
}: ToolFieldSelectProps) {
  const idPrefix = useId().replace(/[^a-zA-Z0-9_-]+/gu, "-");
  const selectId = `${idPrefix}-select`;
  const [scan, setScan] = useState("");
  const [scanError, setScanError] = useState<string | null>(null);

  const candidates = toolFieldCandidates(tools, field, componentTypeCode);
  const selected = candidates.find((tool) => tool.code === value) ?? null;
  // A stored value the registry does not know keeps its own option rather
  // than disappearing from a control that would then submit "" over it.
  const unknownValue = value !== "" && selected === null ? value : null;

  function handleScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const tool = matchScan(candidates, scan);
    if (tool === null) {
      setScanError(labels.scanNoMatch(scan.trim()));
      return;
    }
    setScanError(null);
    setScan("");
    onChange(tool.code);
  }

  return (
    <div className={invalid ? "tool-field tool-field-invalid" : "tool-field"}>
      <label className="phase4-field" htmlFor={selectId}>
        <span className="field-label">
          {field.label}
          {field.required && <span aria-hidden="true"> *</span>}
        </span>
        <select
          id={selectId}
          className="select-input"
          name={`${field.section}.${field.code}`}
          value={value}
          disabled={disabled}
          required={field.required}
          aria-invalid={invalid ? true : undefined}
          onChange={(event) => {
            setScanError(null);
            onChange(event.target.value);
          }}
        >
          <option value="">{labels.choose}</option>
          {unknownValue !== null && (
            <option value={unknownValue}>{labels.unknownValue(unknownValue)}</option>
          )}
          {candidates.map((tool) => (
            <option key={tool.id} value={tool.code}>
              {toolOptionLabel(tool)}
            </option>
          ))}
        </select>
        {field.description !== null && <small className="muted">{field.description}</small>}
      </label>
      <form className="inline-form tool-field-scan" onSubmit={handleScan}>
        <input
          className="search-input mono"
          value={scan}
          disabled={disabled}
          aria-label={labels.scanLabel(field.label)}
          placeholder={labels.scanPlaceholder}
          onChange={(event) => {
            setScan(event.target.value);
            setScanError(null);
          }}
        />
        <button className="btn" type="submit" disabled={disabled}>
          {labels.scan}
        </button>
      </form>
      {scanError !== null && (
        <p className="error-text" role="alert">
          {scanError}
        </p>
      )}
      {candidates.length === 0 && (
        <p className="tool-field-hint serious-text">{labels.noCandidates}</p>
      )}
      {invalid && (
        <p className="error-text" role="alert">
          {labels.required}
        </p>
      )}
    </div>
  );
}

export type ToolFieldSectionProps = {
  fields: readonly ToolField[];
  tools: readonly Tool[];
  componentTypeCode?: string;
  values: Record<string, string>;
  onChange: (code: string, value: string) => void;
  /** Field codes the panel refused to submit without. */
  invalidCodes?: ReadonlySet<string>;
  labels: ToolFieldLabels;
  /** Heading for the whole section when no band names its own. */
  title: string;
  toolsError?: string | null;
  disabled?: boolean;
};

/**
 * Every tool field of one test type, banded the way the sheet bands them.
 *
 * A band heading is the institute's own step label, printed verbatim. Bands
 * the profile did not name (`groupTitle === null`) fall under the section's
 * own heading instead of growing an invented one — a heading that claims a
 * grouping the institute never configured is worse than no heading.
 */
export function ToolFieldSection({
  fields,
  tools,
  componentTypeCode,
  values,
  onChange,
  invalidCodes,
  labels,
  title,
  toolsError = null,
  disabled = false,
}: ToolFieldSectionProps) {
  if (fields.length === 0) return null;
  const bands: Array<{ key: string; title: string | null; fields: ToolField[] }> = [];
  for (const field of fields) {
    const existing = bands.find((band) => band.key === field.groupKey);
    if (existing === undefined) {
      bands.push({ key: field.groupKey, title: field.groupTitle, fields: [field] });
    } else {
      existing.fields.push(field);
    }
  }

  return (
    <section className="phase4-subsection tool-field-section">
      <h4 className="section-title">{title}</h4>
      {toolsError !== null && (
        <p className="error-text" role="alert">
          {labels.registryError(toolsError)}
        </p>
      )}
      {bands.map((band) => (
        <div className="tool-field-band" key={band.key}>
          {band.title !== null && <div className="field-label">{band.title}</div>}
          <div className="phase4-form-grid">
            {band.fields.map((field) => (
              <ToolFieldSelect
                key={field.code}
                field={field}
                tools={tools}
                componentTypeCode={componentTypeCode}
                value={values[field.code] ?? ""}
                onChange={(next) => onChange(field.code, next)}
                labels={labels}
                disabled={disabled}
                invalid={invalidCodes?.has(field.code) === true}
              />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
