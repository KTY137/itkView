// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-f3448e195b62
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { RequirementCheck, StageSuggestion } from "../api";
import { t } from "../i18n";
import { StageSuggestionSection } from "./ComponentsScreen";

// Spec §H3 (2026-08-26): the projected-checks table (ProjectedChecksSection)
// was replaced by the module worksheet, which owns pending/staged rows and the
// in-row edit strip; its ghost-pencil coverage moved with it. The current
// required-tests table below keeps its pencils — routing of a pencil click
// (worksheet edit strip vs. legacy form card) is covered by
// ComponentsScreen.worksheet.test.tsx.

// Same mocking pattern as ShipmentsScreen.test.tsx / ToolsScreen.test.tsx:
// useAuth() throws outside <AuthProvider>, so the module is replaced wholesale
// and tests mutate the hoisted, mutable auth state per-case.
const authState = vi.hoisted(() => ({
  current: {
    canWrite: true,
    showToast: vi.fn(),
    user: {
      email: "operator@example.org",
      role: "operator",
      institute_code: "TUDO" as string | null,
    },
  },
}));

vi.mock("../auth", () => ({
  useAuth: () => authState.current,
}));

function operatorAuth(instituteCode: string | null = "TUDO") {
  authState.current = {
    canWrite: true,
    showToast: vi.fn(),
    user: { email: "operator@example.org", role: "operator", institute_code: instituteCode },
  };
}

function viewerAuth() {
  authState.current = {
    canWrite: false,
    showToast: vi.fn(),
    user: { email: "viewer@example.org", role: "viewer", institute_code: "TUDO" },
  };
}

function suggestion(checks: RequirementCheck[]): StageSuggestion {
  return {
    sn: "20USEM00000001",
    current_stage: "GLUED",
    next_stage: "BONDED",
    move_suggested: false,
    suggested_stage: null,
    checks,
    blocking: [],
  };
}

const missingCheck: RequirementCheck = {
  stage: "GLUED",
  test_type: "MODULE_BOW",
  status: "missing",
};
const failedCheck: RequirementCheck = {
  stage: "GLUED",
  test_type: "MODULE_IV_PS_V1",
  status: "failed",
};
const passedCheck: RequirementCheck = {
  stage: "HV_TAB_ATTACHED",
  test_type: "VISUAL_INSPECTION",
  status: "passed",
};

describe("StageSuggestionSection edit ghosts (current required-tests table)", () => {
  beforeEach(() => operatorAuth());

  it("renders a keyboard-reachable, accessibly-named ghost for missing/failed rows only, and reports the clicked test type", async () => {
    const onRecordTest = vi.fn();
    render(
      <StageSuggestionSection
        suggestion={suggestion([missingCheck, failedCheck, passedCheck])}
        instituteCode="TUDO"
        onStagedChanged={vi.fn()}
        onRecordTest={onRecordTest}
      />,
    );

    const missingGhost = screen.getByRole("button", { name: "Record MODULE_BOW result" });
    expect(missingGhost).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record MODULE_IV_PS_V1 result" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record VISUAL_INSPECTION result" }),
    ).not.toBeInTheDocument();

    const user = userEvent.setup();
    await user.click(missingGhost);
    expect(onRecordTest).toHaveBeenCalledWith("MODULE_BOW");
  });

  it("hides every edit ghost for a viewer", () => {
    viewerAuth();
    render(
      <StageSuggestionSection
        suggestion={suggestion([missingCheck, failedCheck])}
        instituteCode="TUDO"
        onStagedChanged={vi.fn()}
        onRecordTest={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Record .* result$/ })).not.toBeInTheDocument();
  });

  it("hides every edit ghost when the operator's institute does not match the component", () => {
    operatorAuth("DESYZ");
    render(
      <StageSuggestionSection
        suggestion={suggestion([missingCheck])}
        instituteCode="TUDO"
        onStagedChanged={vi.fn()}
        onRecordTest={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Record .* result$/ })).not.toBeInTheDocument();
  });

  it("shows blockers instead of a harmless final-stage message at FINISHED", () => {
    render(
      <StageSuggestionSection
        suggestion={{
          sn: "20USEM00000001",
          current_stage: "FINISHED",
          next_stage: null,
          move_suggested: false,
          suggested_stage: null,
          checks: [failedCheck],
          blocking: [failedCheck],
        }}
        instituteCode="TUDO"
        onStagedChanged={vi.fn()}
      />,
    );

    expect(screen.getByText(t.components.stageBlocked)).toBeVisible();
    expect(screen.queryByText(t.components.stageNoNext)).not.toBeInTheDocument();
  });
});
