import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { TestTypeSchema } from "./api";
import TestForm from "./TestForm";
import type { TestFormLabels } from "./TestForm";

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

  it("blocks missing required fields, non-integers, and arrays with internal blank lines", async () => {
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

    await user.click(screen.getByRole("button", { name: "Create dry-run" }));
    expect(screen.getByText("Run number is required.")).toBeInTheDocument();
    expect(screen.getByText("Measured at is required.")).toBeInTheDocument();
    expect(screen.getByText("Temperature is required.")).toBeInTheDocument();
    expect(screen.getByText("Count is required.")).toBeInTheDocument();
    expect(screen.getByText("Voltage is required.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();

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

    await user.clear(screen.getByLabelText(/^Count/));
    await user.type(screen.getByLabelText(/^Count/), "9007199254740993");
    await user.click(screen.getByRole("button", { name: "Create dry-run" }));
    expect(screen.getByText("Count must be an integer.")).toBeInTheDocument();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
