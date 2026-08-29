// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-f127e430940b
/**
 * The order and grouping an operator reads, checked against the definition
 * the PDB really returns (`test/pdbTestTypeSchemas.ts`) and against the
 * institute profile shape the backend really validates.
 *
 * The GLUE_WEIGHT expectations below are the live production sheet's own
 * sequence, read out of the sheet (rows 10, 17, 21 for the hybrid inputs;
 * 35 and 40 for powerboard): the parts are weighed, then the assembly. Formula
 * rows 24/43 remain server-derived output rather than editable fields.
 */
import { describe, expect, it } from "vitest";

import type { TestSchemaDefinition, Tool } from "./api";
import {
  EMPTY_LAYOUT,
  enumerateFields,
  parseDataEntryLayout,
  parseLayoutSteps,
  parseToolFieldSpecs,
  planFieldLayout,
  toolFieldCandidates,
  toolOptionLabel,
} from "./fieldLayout";
import type { ToolField } from "./fieldLayout";
import { glueWeightMirrorDefinition } from "./test/pdbTestTypeSchemas";

/**
 * An institute that glues one hybrid and then the powerboard — the chain the
 * owner's sheet actually runs (its `Hybrids SNs (top, bottom)` row holds one
 * serial per cell). Exactly the shape `institute_settings._glue_weight_inputs`
 * stores.
 */
const singleHybridSettings = {
  glue_weight_inputs: {
    hybrids: {
      label: "Gluing hybrids",
      test_type: "GLUE_WEIGHT",
      measured: "GW_MODULE_H1",
      subtract: ["GW_SENSOR", "GW_HYBRID1"],
      result_code: "GW_GLUE_H1",
    },
    powerboard: {
      label: "Gluing the powerboard",
      test_type: "GLUE_WEIGHT",
      measured: "GW_MODULE_H1PB",
      subtract: ["GW_MODULE_H1", "GW_PB"],
      result_code: "GW_GLUE_PB",
    },
  },
};

/**
 * `MODULE_BOW` as the mirror holds it: a `JIG` property the PDB can only
 * describe as `dataType: "string"`, which is why the same jig arrives in the
 * mirror under three different spellings across 28 runs.
 */
const moduleBowDefinition: TestSchemaDefinition = {
  code: "MODULE_BOW",
  name: "Module bow",
  parameters: [
    { code: "BOW", name: "Bow [mm]", dataType: "float", valueType: "single", required: false },
  ],
  properties: [
    { code: "JIG", name: "Jig", dataType: "string", valueType: "single", required: true },
    {
      code: "USED_SETUP",
      name: "Used setup",
      dataType: "string",
      valueType: "single",
      required: false,
    },
    {
      code: "SCRIPT_VERSION",
      name: "Script version",
      dataType: "string",
      valueType: "single",
      required: false,
    },
  ],
};

function tool(overrides: Partial<Tool> & Pick<Tool, "id" | "code">): Tool {
  return {
    kind: "jig",
    label: null,
    rfid: null,
    compatible_types: [],
    institute_id: 1,
    status: "active",
    created_at: "2026-08-01T00:00:00Z",
    ...overrides,
  } as Tool;
}

function codes(definition: TestSchemaDefinition, section: "properties" | "results"): string[] {
  const collection = definition[section];
  return Array.isArray(collection)
    ? collection.map((field) => (typeof field === "string" ? field : String(field.code)))
    : [];
}

describe("planFieldLayout ordering", () => {
  it("runs GLUE_WEIGHT in the sheet's order, banded per gluing step", () => {
    const layout = parseDataEntryLayout(singleHybridSettings);
    const plan = planFieldLayout(glueWeightMirrorDefinition, "GLUE_WEIGHT", layout);

    expect(plan.groups.map((group) => [group.key, group.title])).toEqual([
      ["hybrids", "Gluing hybrids"],
      ["powerboard", "Gluing the powerboard"],
      ["other", null],
    ]);
    // Sheet rows 10 / 17 / 21 are editable readings. Row 24 is a formula cell
    // and therefore stays out of TestForm.
    expect(plan.groups[0].fields.map((field) => field.code)).toEqual([
      "GW_SENSOR",
      "GW_HYBRID1",
      "GW_MODULE_H1",
    ]);
    // Sheet rows 35 / 40 are inputs; row 43 is server-derived. `GW_MODULE_H1`
    // belongs to both formulas and
    // appears once, in the band that measured it — as on the sheet.
    expect(plan.groups[1].fields.map((field) => field.code)).toEqual([
      "GW_PB",
      "GW_MODULE_H1PB",
    ]);
  });

  it("hands TestForm a definition whose measurement block leads with the sheet's sequence", () => {
    const plan = planFieldLayout(
      glueWeightMirrorDefinition,
      "GLUE_WEIGHT",
      parseDataEntryLayout(singleHybridSettings),
    );

    expect(codes(plan.definition, "results").slice(0, 5)).toEqual([
      "GW_SENSOR",
      "GW_HYBRID1",
      "GW_MODULE_H1",
      "GW_PB",
      "GW_MODULE_H1PB",
    ]);
    // Only the two server-derived outputs are removed; every raw/unconfigured
    // field from the mirrored definition remains available.
    expect(codes(plan.definition, "results").sort()).toEqual(
      enumerateFields(glueWeightMirrorDefinition)
        .filter((field) => field.section === "results")
        .map((field) => field.code)
        .filter((code) => !["GW_GLUE_H1", "GW_GLUE_PB"].includes(code))
        .sort(),
    );
  });

  it("uses the component-type formula override instead of ordering by the base chain", () => {
    const layout = parseDataEntryLayout({
      glue_weight_inputs: {
        hybrids: {
          label: "Gluing hybrids",
          test_type: "GLUE_WEIGHT",
          measured: "GW_MODULE_H1",
          subtract: ["GW_SENSOR", "GW_HYBRID1"],
          result_code: "GW_GLUE_H1",
          by_type_code: {
            R2: {
              measured: "GW_MODULE_H1H2",
              subtract: ["GW_SENSOR", "GW_HYBRID1", "GW_HYBRID2"],
              result_code: "GW_GLUE_H1H2",
            },
          },
        },
      },
    });

    const plan = planFieldLayout(glueWeightMirrorDefinition, "GLUE_WEIGHT", layout, "R2");

    expect(plan.groups[0].fields.map((field) => field.code)).toEqual([
      "GW_SENSOR",
      "GW_HYBRID1",
      "GW_HYBRID2",
      "GW_MODULE_H1H2",
    ]);
    expect(codes(plan.definition, "results")).not.toContain("GW_GLUE_H1H2");
    expect(codes(plan.definition, "results")).not.toContain("GW_GLUE_H1");
    expect(plan.groups[0].fields.map((field) => field.code)).not.toContain("GW_MODULE_H1");
  });

  it("leaves the definition's own order alone when the institute configures none", () => {
    const plan = planFieldLayout(glueWeightMirrorDefinition, "GLUE_WEIGHT", EMPTY_LAYOUT);

    expect(plan.groups.map((group) => group.key)).toEqual(["other"]);
    expect(codes(plan.definition, "results").slice(0, 4)).toEqual([
      "GW_SENSOR",
      "GW_GLUE_H2",
      "GW_HYBRID1",
      "GW_GLUE_PB",
    ]);
  });

  it("re-emits a parameters-only definition under results and clears parameters", () => {
    // TestForm falls through to `parameters` for an empty `results`; leaving
    // the source key in place would let the unordered original win back.
    const plan = planFieldLayout(glueWeightMirrorDefinition, "GLUE_WEIGHT", EMPTY_LAYOUT);

    expect(glueWeightMirrorDefinition.results).toBeUndefined();
    expect(codes(plan.definition, "results")).toContain("GW_SENSOR");
    expect(plan.definition.parameters).toBeUndefined();
  });

  it("does not let parameters fall through when every measurement is server-derived", () => {
    const onlyDerived: TestSchemaDefinition = {
      properties: [],
      parameters: [
        { code: "GW_GLUE_H1", name: "Glue under hybrid 1", dataType: "float" },
      ],
    };

    const plan = planFieldLayout(
      onlyDerived,
      "GLUE_WEIGHT",
      parseDataEntryLayout(singleHybridSettings),
    );

    expect(plan.definition.results).toEqual([]);
    expect(plan.definition.parameters).toBeUndefined();
    expect(enumerateFields(plan.definition)).toEqual([]);
  });

  it("ignores a step that names a different test type", () => {
    const plan = planFieldLayout(
      glueWeightMirrorDefinition,
      "MODULE_METROLOGY",
      parseDataEntryLayout(singleHybridSettings),
    );

    expect(plan.groups.map((group) => group.key)).toEqual(["other"]);
  });

  it("applies a step without test_type only to the backend default GLUE_WEIGHT", () => {
    const layout = parseDataEntryLayout({
      glue_weight_inputs: {
        hybrids: { measured: "GW_MODULE_H1", subtract: ["GW_SENSOR"] },
      },
    });

    expect(
      planFieldLayout(glueWeightMirrorDefinition, "MODULE_METROLOGY", layout).groups.map(
        (group) => group.key,
      ),
    ).toEqual(["other"]);
    expect(
      planFieldLayout(glueWeightMirrorDefinition, "GLUE_WEIGHT", layout).groups[0]?.key,
    ).toBe("hybrids");
  });
});

describe("tool fields", () => {
  it("lifts a configured tool field out of the generated form", () => {
    const layout = parseDataEntryLayout({
      test_tool_fields: { MODULE_BOW: [{ code: "JIG", kinds: ["jig"] }] },
    });
    const plan = planFieldLayout(moduleBowDefinition, "MODULE_BOW", layout);

    expect(plan.toolFields.map((field) => field.code)).toEqual(["JIG"]);
    expect(plan.toolFields[0]).toMatchObject({
      section: "properties",
      label: "Jig",
      required: true,
      kinds: ["jig"],
    });
    // Gone from what TestForm will render: no free-text input for a jig.
    expect(codes(plan.definition, "properties")).toEqual(["USED_SETUP", "SCRIPT_VERSION"]);
  });

  it("puts a tool field under the band the institute assigned it to", () => {
    const layout = parseDataEntryLayout({
      glue_weight_inputs: {
        bow: {
          label: "Bow setup",
          test_type: "MODULE_BOW",
          measured: "BOW",
        },
      },
      test_tool_fields: {
        MODULE_BOW: [{ code: "JIG", kinds: ["jig"], step: "bow" }],
      },
    });
    const plan = planFieldLayout(moduleBowDefinition, "MODULE_BOW", layout);

    expect(
      plan.toolFields.map((field) => [field.code, field.groupKey, field.groupTitle]),
    ).toEqual([["JIG", "bow", "Bow setup"]]);
  });

  it("falls back to the unnamed remainder for a band key the profile does not define", () => {
    const layout = parseDataEntryLayout({
      test_tool_fields: {
        MODULE_BOW: [{ code: "JIG", kinds: ["jig"], step: "no-such-step" }],
      },
    });
    const plan = planFieldLayout(moduleBowDefinition, "MODULE_BOW", layout);

    // A heading the institute never configured would claim a grouping that
    // does not exist; no heading is the honest outcome.
    expect(plan.toolFields[0]).toMatchObject({ groupKey: "other", groupTitle: null });
  });

  it("offers only the right kind, only active tools, and never hides an unstated fit", () => {
    const field: ToolField = {
      section: "properties",
      code: "JIG",
      label: "Jig",
      description: null,
      required: true,
      defaultValue: undefined,
      kinds: ["jig"],
      groupKey: "other",
      groupTitle: null,
    };
    const tools = [
      tool({ id: 1, code: "20USERT0205022", label: "Module jig 22", compatible_types: ["R2H0S"] }),
      tool({ id: 2, code: "20USERT0510203", kind: "pickup_tool", compatible_types: ["R2H0S"] }),
      tool({ id: 3, code: "20USERT0205023", status: "flagged", compatible_types: ["R2H0S"] }),
      tool({ id: 4, code: "20USERT0510703", compatible_types: ["R5M0_HALFMODULE"] }),
      // Compatibility not stated is not "fits nothing": the mirrored registry
      // leaves the list blank on plenty of real tools.
      tool({ id: 5, code: "20USERT0606117", label: "Bond jig" }),
      // Legacy/sync data may predate canonical lower-case kind writes.
      tool({ id: 6, code: "20USERT0606118", label: "Legacy jig", kind: "JIG" }),
    ];

    expect(toolFieldCandidates(tools, field, "R2H0S").map((item) => item.code)).toEqual([
      "20USERT0205022",
      "20USERT0606117",
      "20USERT0606118",
    ]);
    // No kind filter configured: every active, compatible tool is offered.
    expect(
      toolFieldCandidates(tools, { ...field, kinds: [] }, "R2H0S").map((item) => item.code),
    ).toEqual([
      "20USERT0205022",
      "20USERT0510203",
      "20USERT0606117",
      "20USERT0606118",
    ]);
  });

  it("reads the shop-floor label first and the serial second", () => {
    expect(toolOptionLabel(tool({ id: 1, code: "20USERT0510703", label: "Module jig 3" }))).toBe(
      "Module jig 3 · 20USERT0510703",
    );
    expect(toolOptionLabel(tool({ id: 2, code: "20USERT0510703" }))).toBe(
      "20USERT0510703 · 20USERT0510703",
    );
  });
});

describe("profile parsing fails closed", () => {
  it("uppercases test types and codes and drops an absent kinds filter", () => {
    expect(
      parseToolFieldSpecs({ test_tool_fields: { module_bow: [{ code: "jig" }] } }),
    ).toEqual({ MODULE_BOW: [{ code: "JIG", kinds: [], step: null }] });
  });

  it("normalizes tool kinds to the registry's lower-case vocabulary", () => {
    expect(
      parseToolFieldSpecs({
        test_tool_fields: { MODULE_BOW: [{ code: "JIG", kinds: ["JIG", "jig"] }] },
      }),
    ).toEqual({ MODULE_BOW: [{ code: "JIG", kinds: ["jig"], step: null }] });
  });

  it.each([
    { test_tool_fields: [] },
    { test_tool_fields: { MODULE_BOW: "JIG" } },
    { test_tool_fields: { MODULE_BOW: ["JIG"] } },
    { test_tool_fields: { MODULE_BOW: [{ code: 42 }] } },
    { test_tool_fields: { MODULE_BOW: [{ code: "JIG" }, { code: "jig" }] } },
    { test_tool_fields: { MODULE_BOW: [{ code: "JIG", kinds: "jig" }] } },
    { test_tool_fields: { MODULE_BOW: [{ code: "JIG", step: 7 }] } },
    // Mixed validity is the dangerous shape: skipping the broken entry and
    // keeping the good one leaves *some* fields as pickers and the rest as
    // free text, which is harder to notice than nothing working at all.
    { test_tool_fields: { MODULE_BOW: [{ code: "JIG" }, "OOPS"] } },
    { test_tool_fields: { MODULE_BOW: [{ code: "JIG" }, { code: 42 }] } },
    { test_tool_fields: { MODULE_BOW: [{ code: "JIG" }], "BAD TYPE": [{ code: "JIG" }] } },
  ])("reads a malformed test_tool_fields block as no tool fields at all", (settings) => {
    // Half-applying an unreadable profile is how a jig field silently turns
    // back into free text for some test types and not others.
    expect(parseToolFieldSpecs(settings)).toEqual({});
  });

  it.each([
    { glue_weight_inputs: [] },
    { glue_weight_inputs: { hybrids: "GW_MODULE_H1" } },
    { glue_weight_inputs: { hybrids: { subtract: ["GW_SENSOR"] } } },
    { glue_weight_inputs: { hybrids: { measured: "GW_MODULE_H1", subtract: "GW_SENSOR" } } },
    { glue_weight_inputs: { hybrids: { measured: "GW_MODULE_H1", subtract: ["not a code"] } } },
    // A step whose test type is unreadable must not become a step for every
    // test type; that would reorder forms it was never meant to touch.
    { glue_weight_inputs: { hybrids: { measured: "GW_MODULE_H1", test_type: "bad type" } } },
    {
      glue_weight_inputs: {
        hybrids: { measured: "GW_MODULE_H1", by_type_code: [] },
      },
    },
    {
      glue_weight_inputs: {
        hybrids: {
          measured: "GW_MODULE_H1",
          by_type_code: { R2: { add: ["GW_T1"] } },
        },
      },
    },
    {
      glue_weight_inputs: {
        hybrids: { measured: "GW_MODULE_H1" },
        powerboard: { subtract: ["GW_PB"] },
      },
    },
    {
      glue_weight_inputs: {
        hybrids: { measured: "GW_MODULE_H1", result_code: "GW_PB" },
        powerboard: {
          measured: "GW_MODULE_H1PB",
          subtract: ["GW_MODULE_H1", "GW_PB"],
          result_code: "GW_GLUE_PB",
        },
      },
    },
  ])("reads a malformed glue_weight_inputs block as no layout", (settings) => {
    expect(parseLayoutSteps(settings)).toEqual([]);
  });

  it("survives settings that are not an object at all", () => {
    expect(parseDataEntryLayout(null)).toEqual(EMPTY_LAYOUT);
    expect(parseDataEntryLayout("nope")).toEqual(EMPTY_LAYOUT);
  });
});
