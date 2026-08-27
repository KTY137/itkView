import { render, waitFor } from "@testing-library/react";
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
    [COMPONENT.sn]: { source: "share_link", code: "shared-code" },
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
