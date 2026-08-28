import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { ComponentOut, Institute, SyncJobKind } from "../api";
import { getComponents, getComponentThumbnails, getInstitutes } from "../api";
import type { SyncJobController } from "../componentSync";
import ComponentsScreen from "./ComponentsScreen";

vi.mock("../auth", () => ({
  useAuth: () => ({
    canWrite: false,
    isAdmin: false,
    user: {
      email: "reader@example.invalid",
      role: "reader",
      institute_code: "INST1",
      institute_id: 1,
    },
  }),
}));

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getComponents: vi.fn(),
  getComponentThumbnails: vi.fn(),
  getInstitutes: vi.fn(),
}));

const COMPONENT: ComponentOut = {
  sn: "20USEM00000001",
  local_name: "INST1-M-001",
  component_type: "MODULE",
  type_code: "PS_MODULE",
  stage: "ASSEMBLY",
  location: "INST1",
  institute_code: "INST1",
  parent_sn: null,
  is_dummy: false,
  trashed: false,
  stale: false,
  synced_at: "2026-08-27T10:00:00Z",
};

const INSTITUTE: Institute = {
  id: 1,
  code: "INST1",
  name: "Institute 1",
  local_name_prefix: "INST1",
  settings: {},
  created_at: "2026-08-27T10:00:00Z",
};

function syncController(kind: SyncJobKind): SyncJobController {
  return {
    kind,
    job: null,
    active: false,
    discovering: false,
    starting: false,
    startError: null,
    pollError: null,
    dataEpoch: 0,
    start: vi.fn(async () => undefined),
    dismiss: vi.fn(),
  };
}

it("uses the source-qualified thumbnail locator in the component list", async () => {
  vi.mocked(getComponents).mockResolvedValue([COMPONENT]);
  vi.mocked(getInstitutes).mockResolvedValue([INSTITUTE]);
  vi.mocked(getComponentThumbnails).mockResolvedValue({
    [COMPONENT.sn]: {
      source: "share_link",
      code: "shared-code",
      sn: COMPONENT.sn,
      part: null,
    },
  });

  const { container } = render(
    <ComponentsScreen
      componentSync={syncController("components")}
      evidenceSync={syncController("evidence")}
    />,
  );

  await waitFor(() => {
    expect(container.querySelector(".row-thumb")).toHaveAttribute(
      "src",
      `/api/components/${COMPONENT.sn}/attachments/shared-code?source=share_link`,
    );
  });
});

it("marks a tile borrowed from an assembled part and names whose it is", async () => {
  // A module almost never has a picture of its own — the photographs are of
  // the parts built into it. The row borrows one, but an unmarked tile would
  // claim a sensor's photograph is a picture of the module.
  vi.mocked(getComponents).mockResolvedValue([COMPONENT]);
  vi.mocked(getInstitutes).mockResolvedValue([INSTITUTE]);
  vi.mocked(getComponentThumbnails).mockResolvedValue({
    [COMPONENT.sn]: {
      source: "pdb",
      code: "sensorphoto",
      sn: "20USES50000515",
      part: {
        sn: "20USES50000515",
        component_type: "SENSOR",
        type_code: "ATLAS18R5",
        local_name: "TUDO-S-0042",
      },
    },
  });

  const { container } = render(
    <ComponentsScreen
      componentSync={syncController("components")}
      evidenceSync={syncController("evidence")}
    />,
  );

  await waitFor(() => {
    const tile = container.querySelector(".row-thumb");
    // The bytes live under the part's serial, not the listed component's.
    expect(tile).toHaveAttribute(
      "src",
      "/api/components/20USES50000515/attachments/sensorphoto?source=pdb",
    );
    expect(tile).toHaveClass("is-borrowed");
    expect(tile?.getAttribute("alt")).toContain("TUDO-S-0042");
    expect(container.querySelector(".row-thumb-mark")).not.toBeNull();
  });
});

it("shows missing required tests without a production hold in the component overview", async () => {
  vi.mocked(getComponents).mockResolvedValue([
    {
      ...COMPONENT,
      stage: "FINISHED",
      production_status: "incomplete",
      production_policy_source: "profile_override",
      production_policy_approved: true,
      production_status_reasons: [
        {
          code: "required_test_missing",
          stage: "GLUED",
          test_type: "MODULE_METROLOGY",
        },
      ],
    },
  ]);
  vi.mocked(getInstitutes).mockResolvedValue([INSTITUTE]);
  vi.mocked(getComponentThumbnails).mockResolvedValue({});

  render(
    <ComponentsScreen
      componentSync={syncController("components")}
      evidenceSync={syncController("evidence")}
    />,
  );

  expect(
    await screen.findByLabelText(
      /Required tests missing: MODULE_METROLOGY is missing at the configured Glued gate/,
    ),
  ).toHaveTextContent("ℹTests missing");
  expect(screen.queryByLabelText(/Production hold/)).not.toBeInTheDocument();
});

it("includes provisional-only unknown modules in the holds and unassessed filter", async () => {
  const user = userEvent.setup();
  vi.mocked(getComponents).mockResolvedValue([
    {
      ...COMPONENT,
      sn: "MODULE-UNKNOWN",
      local_name: "Unknown provisional module",
      production_status: "unknown",
      production_policy_source: "seed_default",
      production_policy_approved: false,
      production_status_reasons: [
        { code: "provisional_profile", stage: null, test_type: null },
      ],
    },
    {
      ...COMPONENT,
      sn: "MODULE-CLEAR",
      local_name: "Approved clear module",
      production_status: "clear",
      production_policy_source: "profile_override",
      production_policy_approved: true,
      production_status_reasons: [],
    },
  ]);
  vi.mocked(getInstitutes).mockResolvedValue([INSTITUTE]);
  vi.mocked(getComponentThumbnails).mockResolvedValue({});

  render(
    <ComponentsScreen
      componentSync={syncController("components")}
      evidenceSync={syncController("evidence")}
    />,
  );

  expect(await screen.findByText("Unknown provisional module")).toBeVisible();
  expect(screen.getByText("Approved clear module")).toBeVisible();
  await user.selectOptions(screen.getByLabelText("Production status filter"), "attention");

  expect(screen.getByText("Unknown provisional module")).toBeVisible();
  expect(screen.queryByText("Approved clear module")).not.toBeInTheDocument();
});
