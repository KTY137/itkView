import { render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import type { ComponentOut } from "../api";
import { getComponents } from "../api";
import BoardScreen from "./BoardScreen";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getComponents: vi.fn(),
}));

const HELD: ComponentOut = {
  sn: "MODULE-HOLD",
  local_name: "Module on hold",
  component_type: "MODULE",
  type_code: "R5M0",
  stage: "FINISHED",
  location: "EXAMPLE",
  institute_code: "EXAMPLE",
  parent_sn: null,
  is_dummy: false,
  trashed: false,
  stale: false,
  synced_at: "2026-08-28T08:00:00Z",
  production_status: "hold",
  production_policy_source: "seed_default",
  production_status_reasons: [
    { code: "provisional_profile", stage: null, test_type: null },
    { code: "required_test_failed", stage: "GLUED", test_type: "MODULE_METROLOGY" },
  ],
};

const CLEAR: ComponentOut = {
  ...HELD,
  sn: "MODULE-CLEAR",
  local_name: "Clear module",
  production_status: "clear",
  production_policy_source: "profile_override",
  production_status_reasons: [],
};

beforeEach(() => {
  vi.mocked(getComponents).mockResolvedValue([CLEAR, HELD]);
});

it("puts an accessible danger marker and critical tone on held overview cards", async () => {
  render(<BoardScreen onOpen={vi.fn()} onAssemble={vi.fn()} />);

  const marker = await screen.findByLabelText(
    /Production hold · provisional workflow: MODULE_METROLOGY failed at the configured Glued gate/,
  );
  expect(marker).toHaveTextContent("!");
  expect(marker).toHaveAttribute("role", "img");
  expect(screen.getByRole("button", { name: /Module on hold/ })).toHaveAttribute(
    "data-tone",
    "crit",
  );
  expect(screen.getByRole("button", { name: /Clear module/ })).toHaveAttribute(
    "data-tone",
    "good",
  );
  expect(screen.queryAllByLabelText(/Production hold/)).toHaveLength(1);

  const heldCard = screen.getByRole("button", { name: /Module on hold/ });
  const clearCard = screen.getByRole("button", { name: /Clear module/ });
  expect(heldCard.compareDocumentPosition(clearCard) & Node.DOCUMENT_POSITION_FOLLOWING).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
});

it("does not claim a configured workflow when the institute profile is missing", async () => {
  vi.mocked(getComponents).mockResolvedValue([
    {
      ...HELD,
      production_status: "unknown",
      production_policy_source: "missing_profile",
      production_policy_approved: false,
      production_status_reasons: [
        { code: "missing_profile", stage: null, test_type: null },
      ],
    },
  ]);

  render(<BoardScreen onOpen={vi.fn()} onAssemble={vi.fn()} />);

  const marker = await screen.findByRole("img", {
    name: /No institute workflow profile is available/,
  });
  expect(marker).not.toHaveAccessibleName(/Based on the configured workflow/);
});
