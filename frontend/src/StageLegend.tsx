// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-7c7c5fd297fd
import { stageChipClass, stageLabel } from "./ui";

/** The assembly flow in canonical order, then the two off-flow exits. Renders
 * the same chips used across the app, so the colour ramp is self-documenting:
 * cool → green as work nears completion; green = done, red = failed/trashed. */
const FLOW = [
  "HV_TAB_ATTACHED",
  "GLUED",
  "STITCH_BONDING",
  "BONDED",
  "TESTED",
  "FINISHED",
];
const EXITS = ["FAILED", "TRASHED"];

export default function StageLegend({ label }: { label: string }) {
  return (
    <div className="stage-legend">
      <span className="field-label">{label}</span>
      <div
        className="legend-row"
        role="img"
        aria-label={`${label}: ${FLOW.map(stageLabel).join(" → ")}`}
      >
        {FLOW.map((stage, i) => (
          <span className="legend-item" key={stage}>
            <span className={stageChipClass(stage)} title={stage}>
              {stageLabel(stage)}
            </span>
            {i < FLOW.length - 1 && (
              <span className="legend-arrow" aria-hidden="true">
                →
              </span>
            )}
          </span>
        ))}
        <span className="legend-sep" aria-hidden="true">
          |
        </span>
        {EXITS.map((stage) => (
          <span className={stageChipClass(stage)} key={stage} title={stage}>
            {stageLabel(stage)}
          </span>
        ))}
      </div>
    </div>
  );
}
