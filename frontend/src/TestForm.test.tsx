import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TestSchemaDefinition, TestTypeSchema } from "./api";
import TestForm, { manualEntryCapability } from "./TestForm";
import type { TestFormLabels } from "./TestForm";
import {
  glueWeightMirrorDefinition,
  hybridTestsSummaryMirrorDefinition,
  mirroredSchema,
  moduleMetrologyMirrorDefinition,
} from "./test/pdbTestTypeSchemas";

const labels: TestFormLabels = {
  runNumber: "Run number",
  date: "Measured at",
  passed: "Passed",
  problems: "Problems",
  properties: "Properties",
  results: "Results",
  submit: "Create dry-run",
  booleanUnset: "Not set",
  booleanTrue: "Yes",
  booleanFalse: "No",
  arrayHint: "Enter one value per line.",
  requiredField: (field) => `${field} is required.`,
  invalidNumber: (field, line) =>
    `${field} must be a finite decimal${line === undefined ? "" : ` on line ${line}`}.`,
  invalidInteger: (field, line) =>
    `${field} must be an integer${line === undefined ? "" : ` on line ${line}`}.`,
  invalidBoolean: (field, line) =>
    `${field} must be a boolean${line === undefined ? "" : ` on line ${line}`}.`,
  unsupportedType: (field, dataType) => `${field} has unsupported type ${dataType}.`,
};

/**
 * A definition that spells its measurement block `results`. Not a PDB shape —
 * no mirrored definition uses that key (see `test/pdbTestTypeSchemas.ts`) — but
 * itkFlow's own: it is the `uploadTestRunResults` payload key and the shape a
 * caller re-emits when it prefills a definition. Kept because that branch must
 * go on working; the mirror-shaped suite below covers what the PDB sends.
 */
const schema: TestTypeSchema = {
  id: 11,
  component_type: "MODULE",
  test_code: " MODULE_METROLOGY ",
  name: "Module metrology",
  synced_at: "2026-08-26T08:00:00Z",
  schema: {
    properties: [
      { code: "TEMPERATURE", name: "Temperature", dataType: "float", required: true },
      { code: "JIG", name: "Jig", dataType: "string" },
      { code: "ENABLED", name: "Enabled", dataType: "boolean" },
    ],
    results: [
      { code: "COUNT", name: "Count", dataType: "integer", required: true },
      {
        code: "VOLTAGE",
        name: "Voltage",
        dataType: "float",
        valueType: "array",
        required: true,
      },
    ],
  },
};

describe("manualEntryCapability", () => {
  const scalarResult = { code: "VALUE", name: "Value", dataType: "float" };

  it("blocks required object and testRun fields even when a scalar result is enterable", () => {
    const capability = manualEntryCapability({
      properties: [
        { code: "DCS", name: "DCS settings", dataType: "object", required: true },
        { code: "SOURCE_RUN", name: "Source run", dataType: "testRun", required: true },
      ],
      parameters: [scalarResult],
    });

    expect(capability.canEnter).toBe(false);
    expect(capability.blockers).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ code: "DCS", reason: "required-unsupported-type" }),
        expect.objectContaining({ code: "SOURCE_RUN", reason: "required-unsupported-type" }),
      ]),
    );
  });

  it.each([undefined, null, 0, 1])(
    "allows a primitive array with arrayDimensions %s",
    (arrayDimensions) => {
      const capability = manualEntryCapability({
        parameters: [
          {
            code: "CURRENT",
            name: "Current",
            dataType: "float",
            valueType: "array",
            ...(arrayDimensions === undefined ? {} : { arrayDimensions }),
          },
        ],
      });

      expect(capability).toEqual({ canEnter: true, blockers: [] });
    },
  );

  it.each([2, 3, "2"])(
    "keeps a primitive array with unsafe arrayDimensions %s file-only",
    (arrayDimensions) => {
      const capability = manualEntryCapability({
        parameters: [
          scalarResult,
          {
            code: "CURRENT",
            name: "Current",
            dataType: "float",
            valueType: "array",
            arrayDimensions,
          },
        ],
      });

      expect(capability.canEnter).toBe(false);
      expect(capability.blockers).toContainEqual(
        expect.objectContaining({ code: "CURRENT", reason: "unsupported-array-shape" }),
      );
    },
  );

  it("allows optional unsupported fields when another measurement is enterable", () => {
    expect(
      manualEntryCapability({
        properties: [{ code: "OPTIONAL_MAP", dataType: "object" }],
        parameters: [scalarResult],
      }),
    ).toEqual({ canEnter: true, blockers: [] });
  });

  it("blocks a schema whose only measurements are unsupported, even when optional", () => {
    const capability = manualEntryCapability(hybridTestsSummaryMirrorDefinition);

    expect(capability.canEnter).toBe(false);
    expect(capability.blockers.length).toBeGreaterThan(0);
    expect(capability.blockers.every((blocker) => blocker.section === "results")).toBe(true);
  });
});

describe("TestForm", () => {
  it("submits the schema values as one canonical test-run payload", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <TestForm
        component=" 20USEM00000001 "
        schema={schema}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    await user.type(screen.getByLabelText(/^Run number/), " 004 ");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-26T10:15" },
    });
    await user.type(screen.getByLabelText(/^Temperature/), "-1.25e2");
    await user.type(screen.getByLabelText(/^Jig/), "  JIG-17  ");
    await user.selectOptions(screen.getByLabelText(/^Enabled/), "true");
    await user.type(screen.getByLabelText(/^Count/), "7");
    await user.type(screen.getByLabelText(/^Voltage/), "1.5\n-2e1");
    await user.selectOptions(screen.getByLabelText(/^Passed/), "false");
    await user.selectOptions(screen.getByLabelText(/^Problems/), "true");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      component: "20USEM00000001",
      testType: "MODULE_METROLOGY",
      runNumber: "004",
      date: new Date("2026-08-26T10:15").toISOString(),
      passed: false,
      problems: true,
      properties: {
        TEMPERATURE: -125,
        JIG: "JIG-17",
        ENABLED: true,
      },
      results: {
        COUNT: 7,
        VOLTAGE: [1.5, -20],
      },
    });
  });

  it("accepts decimal commas and points and submits canonical JSON numbers", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <TestForm
        component="20USEM00000001"
        schema={schema}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    const temperature = screen.getByLabelText(/^Temperature/);
    const voltage = screen.getByLabelText(/^Voltage/);
    expect(temperature).toHaveAttribute("type", "text");
    expect(temperature).toHaveAttribute("inputmode", "decimal");
    expect(voltage).toHaveAttribute("inputmode", "decimal");

    await user.type(screen.getByLabelText(/^Run number/), "5");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-26T11:00" },
    });
    await user.type(temperature, "-1,25e2");
    await user.type(screen.getByLabelText(/^Count/), "7");
    await user.type(voltage, "1,5\n-2.25e1");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      properties: { TEMPERATURE: -125 },
      results: { COUNT: 7, VOLTAGE: [1.5, -22.5] },
    });
    expect(typeof onSubmit.mock.calls[0][0].properties.TEMPERATURE).toBe("number");
    expect(onSubmit.mock.calls[0][0].results.VOLTAGE).toEqual(
      expect.arrayContaining([expect.any(Number), expect.any(Number)]),
    );
  });

  it("still rejects mixed decimal separators", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <TestForm
        component="20USEM00000001"
        schema={schema}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    await user.type(screen.getByLabelText(/^Run number/), "5");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-26T11:00" },
    });
    await user.type(screen.getByLabelText(/^Temperature/), "1,2.3");
    await user.type(screen.getByLabelText(/^Count/), "7");
    await user.type(screen.getByLabelText(/^Voltage/), "1");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(screen.getByText("Temperature must be a finite decimal.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("blocks missing required fields, non-integers, and arrays with internal blank lines", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    render(
      <TestForm
        component="20USEM00000001"
        schema={schema}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Create dry-run" }));
    expect(screen.getByText("Run number is required.")).toBeInTheDocument();
    expect(screen.getByText("Measured at is required.")).toBeInTheDocument();
    expect(screen.getByText("Temperature is required.")).toBeInTheDocument();
    expect(screen.getByText("Count is required.")).toBeInTheDocument();
    expect(screen.getByText("Voltage is required.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Run number/)).toHaveFocus();
    expect(scrollIntoView).toHaveBeenLastCalledWith({ block: "nearest" });

    await user.type(screen.getByLabelText(/^Run number/), "5");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-26T11:00" },
    });
    await user.type(screen.getByLabelText(/^Temperature/), "22.5");
    await user.type(screen.getByLabelText(/^Count/), "3.5");
    await user.type(screen.getByLabelText(/^Voltage/), "1\n\n2");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(screen.getByText("Count must be an integer.")).toBeInTheDocument();
    expect(screen.getByText("Voltage must be a finite decimal on line 2.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByLabelText(/^Count/)).toHaveFocus();

    await user.clear(screen.getByLabelText(/^Count/));
    await user.type(screen.getByLabelText(/^Count/), "9007199254740993");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));
    expect(screen.getByText("Count must be an integer.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

/**
 * The shape the product actually receives. Everything above this line uses a
 * `results`-keyed definition; no PDB definition is keyed that way, which is
 * how a form that could never be submitted shipped with a green suite.
 * These cases render definitions copied verbatim out of a live mirror.
 */
describe("TestForm on mirrored PDB definitions", () => {
  function measurementControls(container: HTMLElement): string[] {
    return Array.from(container.querySelectorAll('[name^="results."]')).map((node) =>
      (node.getAttribute("name") ?? "").replace(/^results\./u, ""),
    );
  }

  it("renders GLUE_WEIGHT's 19 `parameters` and records a weight", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const { container } = render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(glueWeightMirrorDefinition)}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    // All 19, not the 4 `properties` alone.
    expect(measurementControls(container)).toHaveLength(19);
    expect(measurementControls(container)).toEqual(
      expect.arrayContaining(["GW_SENSOR", "GW_HYBRID1T", "GW_T1", "GW_GLUE_PB", "GW_PB"]),
    );
    expect(screen.getByLabelText(/^Weight of sensor \[g\]/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Weight of hybrid 1 \(with tabs\) \[g\]/)).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^Run number/), "1");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-27T09:30" },
    });
    // GW_METHOD is the schema's one required property.
    await user.type(screen.getByLabelText(/^Glue application method/), "stencil");
    await user.type(screen.getByLabelText(/^Weight of sensor \[g\]/), "10.945");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith({
      component: "20USEM00000435",
      testType: "GLUE_WEIGHT",
      runNumber: "1",
      date: new Date("2026-08-27T09:30").toISOString(),
      passed: true,
      problems: false,
      properties: { GW_METHOD: "stencil" },
      results: { GW_SENSOR: 10.945 },
    });
  });

  it("keeps worksheet descriptions accessible without repeating them in the dense layout", async () => {
    const user = userEvent.setup();
    const onCancel = vi.fn();
    const { container } = render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(glueWeightMirrorDefinition)}
        labels={labels}
        onSubmit={vi.fn()}
        variant="worksheet"
        cancelLabel="Cancel"
        onCancel={onCancel}
      />,
    );

    expect(container.querySelector("form")).toHaveClass("phase4-form-worksheet");
    expect(screen.getByLabelText(/^Weight of sensor \[g\]/)).toHaveAttribute(
      "title",
      "Weight of bare sensor [g]",
    );
    expect(screen.getByText("Weight of bare sensor [g]")).toHaveClass("sr-only");

    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledOnce();
  });

  it("keeps a populated `results` block ahead of `parameters`, each field once", () => {
    const bothKeys: TestSchemaDefinition = {
      ...glueWeightMirrorDefinition,
      results: [
        // Same code as a `parameters` entry: proves the precedence decides,
        // not de-duplication.
        { code: "GW_SENSOR", name: "Sensor weight (results block)", dataType: "float" },
        { code: "GW_EXTRA", name: "Extra weight (results block)", dataType: "float" },
      ],
    };
    const { container } = render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(bothKeys)}
        labels={labels}
        onSubmit={vi.fn()}
      />,
    );

    expect(measurementControls(container)).toEqual(["GW_SENSOR", "GW_EXTRA"]);
    expect(screen.getByLabelText(/^Sensor weight \(results block\)/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/^Weight of sensor \[g\]/)).toBeNull();
    expect(screen.queryByLabelText(/^Weight of powerboard \[g\]/)).toBeNull();
  });

  it("falls back to `parameters` when a caller re-emits an empty `results` block", async () => {
    // Exactly what ModuleWorksheet's `prefilledDefinition` produces for a
    // parameters-only definition: properties rewritten, `results: []`.
    const reEmitted: TestSchemaDefinition = {
      ...glueWeightMirrorDefinition,
      properties: [
        { code: "GW_METHOD", name: "Glue application method", dataType: "string",
          required: true, defaultValue: "dispenser" },
      ],
      results: [],
    };
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const { container } = render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(reEmitted)}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    expect(measurementControls(container)).toHaveLength(19);
    await user.type(screen.getByLabelText(/^Run number/), "2");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-27T10:00" },
    });
    await user.type(screen.getByLabelText(/^Weight of powerboard \[g\]/), "3.5");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      testType: "GLUE_WEIGHT",
      properties: { GW_METHOD: "dispenser" },
      results: { GW_PB: 3.5 },
    });
  });

  it("explains a definition whose parameters cannot be entered, instead of blaming the input", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(hybridTestsSummaryMirrorDefinition)}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    // Said up front, not only after a doomed submit.
    expect(
      screen.getByText(/^HYBRID_TESTS_SUMMARY declares no measurement field/),
    ).toBeInTheDocument();

    await user.type(screen.getByLabelText(/^Run number/), "3");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-27T10:30" },
    });
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(onSubmit).not.toHaveBeenCalled();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(/^HYBRID_TESTS_SUMMARY declares no measurement field/);
    expect(screen.queryByText("Results is required.")).toBeNull();
  });

  it("uses a caller's own wording for that case when the label bundle carries one", () => {
    render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(hybridTestsSummaryMirrorDefinition)}
        labels={{
          ...labels,
          noMeasurementFields: (testType) => `Nothing to type for ${testType}.`,
        }}
        onSubmit={vi.fn()}
      />,
    );
    expect(screen.getByText("Nothing to type for HYBRID_TESTS_SUMMARY.")).toBeInTheDocument();
  });

  it("renders MODULE_METROLOGY's one enterable parameter and names the ones it cannot take", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();
    const { container } = render(
      <TestForm
        component="20USEM00000435"
        schema={mirroredSchema(moduleMetrologyMirrorDefinition)}
        labels={labels}
        onSubmit={onSubmit}
      />,
    );

    expect(measurementControls(container)).toHaveLength(6);
    // The float can be typed; the five per-position `object` maps cannot, and
    // two of those are required — so this test type stays unrecordable here,
    // with a message that names the data type rather than the person.
    await user.type(screen.getByLabelText(/^Run number/), "4");
    fireEvent.change(screen.getByLabelText(/^Measured at/), {
      target: { value: "2026-08-27T11:00" },
    });
    await user.type(screen.getByLabelText(/^Machine/), "OGP");
    await user.type(screen.getByLabelText(/^Operator/), "A. Abel");
    await user.type(screen.getByLabelText(/^Script version/), "3.1");
    await user.type(screen.getByLabelText(/^Shield box height \[um\]/), "295.5");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));

    expect(onSubmit).not.toHaveBeenCalled();
    expect(
      screen.getAllByText("Hybrid position Deviation [um] has unsupported type object."),
    ).not.toHaveLength(0);
  });
});
