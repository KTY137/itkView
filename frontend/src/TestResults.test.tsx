// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-0096f89b6cbb
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { TestRunAttachment, TestRunDetail } from "./api";
import { t } from "./i18n";
import { RunAttachments, RunCurves, RunScalars } from "./TestResults";

function run(
  results: Record<string, unknown>,
  names: Record<string, string>,
  attachments: TestRunAttachment[] = [],
): TestRunDetail {
  return {
    test_type: "GENERIC_MEASUREMENT",
    passed: true,
    external_ref: "RUN-1",
    measured_at: "2026-08-27T10:00:00Z",
    run_number: "1",
    run_state: null,
    results,
    result_meta: Object.fromEntries(
      Object.entries(names).map(([code, name]) => [code, { name }]),
    ),
    properties: {},
    attachments,
  };
}

describe("generated plots in expanded test results", () => {
  it("keeps the paired IV curve when the run has no attachment", () => {
    const iv = run(
      { VOLTAGE: [0, -50, -100], CURRENT: [0.1, 0.8, 1.7] },
      { VOLTAGE: "Bias voltage [V]", CURRENT: "Leakage current [uA]" },
    );

    render(
      <>
        <RunCurves run={iv} />
        <RunAttachments sn="20USEM00000001" attachments={iv.attachments} onOpen={vi.fn()} />
      </>,
    );

    expect(
      screen.getByRole("img", { name: "Leakage current [uA] over Bias voltage [V]" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("img").closest("figure")).toHaveTextContent(
      t.testResults.curvePoints(3),
    );
    expect(document.querySelector(".img-grid")).toBeNull();
  });

  it("keeps a stored TIFF visible while saying that its preview is unavailable", () => {
    const attachment: TestRunAttachment = {
      source: "pdb",
      code: "stored-tiff",
      test_type: "VISUAL_INSPECTION",
      test_run_ref: "RUN-1",
      filename: "profile-y.tiff",
      content_type: "image/tiff",
      title: "Profile Y",
      size_bytes: 1024,
      stored: true,
      is_image: true,
    };

    const { container } = render(
      <RunAttachments sn="20USEM00000001" attachments={[attachment]} onOpen={vi.fn()} />,
    );

    expect(screen.getByText("profile-y.tiff")).toBeInTheDocument();
    expect(screen.getByText(t.images.storedLocally)).toBeInTheDocument();
    expect(container.querySelector(".img-thumb.placeholder")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("plots an all-finite numeric map by its discrete keys and keeps the full table", () => {
    const mapped = run(
      { THICKNESS: { SENSOR_LEFT: 1.25, SENSOR_RIGHT: -0.5 } },
      { THICKNESS: "Glue thickness [um]" },
    );

    const { container } = render(
      <>
        <RunCurves run={mapped} />
        <RunScalars run={mapped} />
      </>,
    );

    expect(
      screen.getByRole("img", {
        name: t.testResults.categoryPlotAria("Glue thickness [um]", 2),
      }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("svg rect")).toHaveLength(2);
    expect(container.querySelector("svg circle")).toBeNull();
    expect(container.querySelector("svg polyline")).toBeNull();
    expect(screen.getAllByText("SENSOR_LEFT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("SENSOR_RIGHT").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1.25").length).toBeGreaterThan(0);
    expect(screen.getAllByText("-0.5").length).toBeGreaterThan(0);
    expect(container.querySelector(".map-measure > dd > .measure-grid")).not.toBeNull();
  });

  it("keeps finite numeric pairs in the table without inventing plot axes", () => {
    const pairs = run(
      { PAIRS: { POSITION_A: [0.1, -0.2], POSITION_B: [-0.3, 0.4] } },
      { PAIRS: "Measured pairs [mm]" },
    );

    const { container } = render(
      <>
        <RunCurves run={pairs} />
        <RunScalars run={pairs} />
      </>,
    );

    expect(screen.queryByRole("img")).toBeNull();
    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("POSITION_A")).toBeInTheDocument();
    expect(screen.getByText("POSITION_B")).toBeInTheDocument();
    expect(screen.getByText(t.testResults.numericPair("0.1", "-0.2"))).toBeInTheDocument();
    expect(screen.getByText(t.testResults.numericPair("-0.3", "0.4"))).toBeInTheDocument();
    expect(container).not.toHaveTextContent("Δx");
    expect(container).not.toHaveTextContent("Δy");
  });

  it("gives every map result its own full-width responsive value block", () => {
    const metrology = run(
      {
        INTERBOARD_GLUE_THICKNESS: {
          ABC_R5H0_0: 147.9588,
          ABC_R5H0_1: 159.0245,
        },
        HYBRID_POSITION_DEVIATION: {
          H_R5H0_P1: [-125, 525],
          H_R5H0_P2: [-36, -21],
        },
      },
      {
        INTERBOARD_GLUE_THICKNESS: "Interboard glue thickness [um]",
        HYBRID_POSITION_DEVIATION: "Hybrid position deviation [um]",
      },
    );

    const { container } = render(<RunScalars run={metrology} />);

    const maps = [...container.querySelectorAll(".map-measure")];
    expect(maps).toHaveLength(2);
    for (const map of maps) {
      expect(map.parentElement).toHaveClass("measure-grid");
      expect(map.querySelector(":scope > dd > .measure-grid")).not.toBeNull();
    }
  });

  it("does not let a categorical fallback replace an original numeric-array curve", () => {
    const mixedShapes = run(
      {
        CURRENT: [0.1, 0.8, 1.7],
        THICKNESS: { SENSOR_LEFT: 1.25, SENSOR_RIGHT: 1.2 },
      },
      { CURRENT: "Leakage current [uA]", THICKNESS: "Glue thickness [um]" },
    );

    const { container } = render(<RunCurves run={mixedShapes} />);

    expect(
      screen.getByRole("img", { name: "Leakage current [uA] over #" }),
    ).toBeInTheDocument();
    expect(container.querySelectorAll("svg")).toHaveLength(1);
    expect(container.querySelector("svg polyline")).not.toBeNull();
    expect(container.querySelector("svg rect")).toBeNull();
  });

  it("uses a displayable attachment instead of generating a categorical fallback", () => {
    const attachment: TestRunAttachment = {
      source: "pdb",
      code: "PLOT-PNG",
      test_type: "MODULE_METROLOGY",
      test_run_ref: "RUN-1",
      filename: "profile.png",
      content_type: "image/png",
      title: "Measured profile",
      size_bytes: 2048,
      stored: true,
      is_image: true,
    };
    const mapped = run(
      { THICKNESS: { SENSOR_LEFT: 1.25, SENSOR_RIGHT: 1.2 } },
      { THICKNESS: "Glue thickness [um]" },
      [attachment],
    );

    const { container } = render(
      <>
        <RunAttachments sn="20USEM00000001" attachments={mapped.attachments} onOpen={vi.fn()} />
        <RunCurves run={mapped} />
      </>,
    );

    expect(screen.getByRole("img", { name: "Measured profile" })).toBeInTheDocument();
    expect(container.querySelector("figure.curve")).toBeNull();
  });

  it("shows a real image before the original array curve when both exist", () => {
    const attachment: TestRunAttachment = {
      source: "pdb",
      code: "PLOT-PNG",
      test_type: "MODULE_IV",
      test_run_ref: "RUN-1",
      filename: "iv.png",
      content_type: "image/png",
      title: "Instrument IV plot",
      size_bytes: 2048,
      stored: true,
      is_image: true,
    };
    const iv = run(
      { VOLTAGE: [0, -50, -100], CURRENT: [0.1, 0.8, 1.7] },
      { VOLTAGE: "Bias voltage [V]", CURRENT: "Leakage current [uA]" },
      [attachment],
    );

    const { container } = render(
      <>
        <RunAttachments sn="20USEM00000001" attachments={iv.attachments} onOpen={vi.fn()} />
        <RunCurves run={iv} />
      </>,
    );

    const imageGrid = container.querySelector(".img-grid");
    const curve = container.querySelector("figure.curve");
    expect(imageGrid).not.toBeNull();
    expect(curve).not.toBeNull();
    expect(imageGrid!.compareDocumentPosition(curve!)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("leaves a mixed map as a table without inventing plot points", () => {
    const mixed = run(
      { OFFSETS: { POSITION_A: [0.1, -0.2], POSITION_B: "not measured" } },
      { OFFSETS: "Measured offsets [mm]" },
    );

    render(
      <>
        <RunCurves run={mixed} />
        <RunScalars run={mixed} />
      </>,
    );

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("POSITION_A")).toBeInTheDocument();
    expect(screen.getByText("POSITION_B")).toBeInTheDocument();
    expect(screen.getByText(t.testResults.numericPair("0.1", "-0.2"))).toBeInTheDocument();
    expect(screen.getByText("not measured")).toBeInTheDocument();
  });

  it("gives a stored TIFF without filename an honest non-empty placeholder", () => {
    const attachment: TestRunAttachment = {
      source: "pdb",
      code: "ATT-TIFF",
      test_type: "MODULE_METROLOGY",
      test_run_ref: "RUN-1",
      filename: null,
      content_type: "image/tiff",
      title: null,
      size_bytes: 123,
      stored: true,
      is_image: true,
    };

    render(<RunAttachments sn="20USEM00000001" attachments={[attachment]} onOpen={vi.fn()} />);

    expect(screen.getByText("MODULE_METROLOGY")).toBeVisible();
    expect(screen.getByText(t.images.storedLocally)).toBeVisible();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
