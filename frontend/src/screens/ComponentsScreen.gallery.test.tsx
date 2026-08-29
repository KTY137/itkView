// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-2cc23170af69
/**
 * The module page's image gallery, rendered against the real detail panel.
 *
 * WHY THIS FILE EXISTS. On the owner's mirror 241 of 432 mirrored images hang
 * on a sensor that is a module's direct child and 3 on modules themselves, so
 * a gallery filtered by serial number alone shows an operator almost nothing.
 * The children's pictures now come with the page — but each under its own
 * serial, because that is both whose picture it is and where the mirror filed
 * the bytes. A merged grid would fetch them from the parent's URL and 404.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import type { ComponentAttachments, TestRunAttachment } from "../api";
import {
  getComponent,
  getComponentAttachments,
  getComponentPreview,
  getComponentStaged,
  getComponentTests,
  getMe,
  getStageSuggestion,
  getTestTypeSchemas,
} from "../api";
import { AuthProvider } from "../auth";
import { t } from "../i18n";
import {
  moduleDetail,
  MODULE_SN,
  operatorMe,
  previewPayload,
  stageSuggestion,
  testTypeSchemas,
} from "../test/moduleWorksheetFixtures";
import { describeComponent } from "../ui";
import { ComponentDetailPanel } from "./ComponentsScreen";

vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  getComponent: vi.fn(),
  getComponentAttachments: vi.fn(),
  getComponentPreview: vi.fn(),
  getComponentStaged: vi.fn(),
  getComponentTests: vi.fn(),
  getMe: vi.fn(),
  getStageSuggestion: vi.fn(),
  getTestTypeSchemas: vi.fn(),
}));

const SENSOR_SN = "20USES40000123";

function image(code: string, overrides: Partial<TestRunAttachment> = {}): TestRunAttachment {
  return {
    source: "pdb",
    code,
    test_type: "VISUAL_INSPECTION",
    test_run_ref: `RUN-${code}`,
    filename: `${code}.jpg`,
    content_type: "image/jpeg",
    title: null,
    size_bytes: 1024,
    stored: true,
    is_image: true,
    ...overrides,
  };
}

const family: ComponentAttachments = {
  component_sn: MODULE_SN,
  attachments: [image("module-photo")],
  children: [
    {
      sn: SENSOR_SN,
      component_type: "SENSOR",
      type_code: "ATLAS18R5",
      local_name: "EXA-S-007",
      attachments: [image("sensor-photo")],
    },
  ],
};

beforeEach(() => {
  vi.mocked(getMe).mockResolvedValue(operatorMe);
  vi.mocked(getComponent).mockResolvedValue(moduleDetail);
  vi.mocked(getComponentPreview).mockResolvedValue(previewPayload());
  vi.mocked(getComponentStaged).mockResolvedValue([]);
  vi.mocked(getStageSuggestion).mockResolvedValue(stageSuggestion);
  vi.mocked(getTestTypeSchemas).mockResolvedValue(testTypeSchemas);
  vi.mocked(getComponentTests).mockResolvedValue([]);
  vi.mocked(getComponentAttachments).mockResolvedValue(family);
});

function renderModulePage() {
  return render(
    <AuthProvider>
      <ComponentDetailPanel
        sn={MODULE_SN}
        backLabel="Back"
        onBack={vi.fn()}
        onOpen={vi.fn()}
        evidenceJobId={null}
        evidenceEpoch={0}
        pinnedTestType={null}
        testIntentToken={0}
        onNavigate={vi.fn()}
      />
    </AuthProvider>,
  );
}

function childSection(): HTMLElement {
  const heading = screen.getByRole("heading", { name: t.images.childrenTitle });
  const section = heading.closest("section");
  if (section === null) throw new Error("child image section not found");
  return section;
}

function ownImagePanel(): HTMLElement {
  const heading = screen.getByRole("heading", { name: t.images.title });
  const panel = heading.nextElementSibling;
  if (!(panel instanceof HTMLElement)) throw new Error("own image panel not found");
  return panel;
}

it("shows a child's image tagged with the child's serial and type", async () => {
  renderModulePage();

  await screen.findByRole("heading", { name: t.images.childrenTitle });
  const section = childSection();

  expect(within(section).getByText(SENSOR_SN)).toBeTruthy();
  // The kind of part is the other half of "whose picture is this" — rendered
  // through the same describeComponent() the worksheet's child groups use.
  expect(within(section).getByText(describeComponent(family.children[0]))).toBeTruthy();
  expect(within(section).getByRole("img")).toHaveAttribute(
    "src",
    `/api/components/${SENSOR_SN}/attachments/sensor-photo?source=pdb`,
  );
});

it("keeps the component's own images out of the children's groups", async () => {
  renderModulePage();

  await screen.findByRole("heading", { name: t.images.childrenTitle });

  // The module's own picture is fetched under the module's serial, and it is
  // not repeated inside the child group.
  const own = screen.getByAltText("module-photo.jpg");
  expect(own).toHaveAttribute(
    "src",
    `/api/components/${MODULE_SN}/attachments/module-photo?source=pdb`,
  );
  expect(within(childSection()).queryByAltText("module-photo.jpg")).toBeNull();
});

it("addresses equal attachment codes by source in the gallery and lightbox", async () => {
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: MODULE_SN,
    attachments: [
      image("shared-code", { source: "pdb", filename: "pdb-copy.jpg" }),
      image("shared-code", { source: "share_link", filename: "shared-copy.jpg" }),
    ],
    children: [],
  });
  renderModulePage();

  const pdbImage = await screen.findByAltText("pdb-copy.jpg");
  const sharedImage = screen.getByAltText("shared-copy.jpg");
  expect(pdbImage).toHaveAttribute(
    "src",
    `/api/components/${MODULE_SN}/attachments/shared-code?source=pdb`,
  );
  expect(sharedImage).toHaveAttribute(
    "src",
    `/api/components/${MODULE_SN}/attachments/shared-code?source=share_link`,
  );

  await userEvent.setup().click(sharedImage.closest("button") as HTMLButtonElement);
  const dialog = screen.getByRole("dialog", { name: "shared-copy.jpg" });
  expect(within(dialog).getByRole("img")).toHaveAttribute(
    "src",
    `/api/components/${MODULE_SN}/attachments/shared-code?source=share_link`,
  );
});

it("keeps an own TIFF visible with an explicit unavailable-preview label", async () => {
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: MODULE_SN,
    attachments: [
      image("module-scan", {
        filename: "module-scan.tiff",
        content_type: "image/tiff",
      }),
    ],
    children: [],
  });
  renderModulePage();

  await screen.findByText(/module-scan\.tiff/u);
  const panel = ownImagePanel();
  expect(within(panel).queryByText(t.images.empty)).toBeNull();
  expect(within(panel).queryByText(t.images.ownEmpty)).toBeNull();
  expect(within(panel).getByText(t.images.storedLocally)).toBeInTheDocument();
  expect(panel.querySelector(".img-thumb.placeholder")).not.toBeNull();
  expect(panel.querySelector("img")).toBeNull();
});

it("keeps a child-only TIFF in its owner group with an unavailable-preview label", async () => {
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: MODULE_SN,
    attachments: [],
    children: [
      {
        ...family.children[0],
        attachments: [
          image("sensor-scan", {
            filename: "sensor-scan.tif",
            content_type: "image/tiff",
          }),
        ],
      },
    ],
  });
  renderModulePage();

  await screen.findByText(t.images.ownEmpty);
  const section = childSection();
  expect(screen.queryByText(t.images.empty)).toBeNull();
  expect(within(section).getByText(/sensor-scan\.tif/u)).toBeInTheDocument();
  expect(within(section).getByText(t.images.storedLocally)).toBeInTheDocument();
  expect(section.querySelector(".img-thumb.placeholder")).not.toBeNull();
  expect(section.querySelector("img")).toBeNull();
});

it("says so when only the children have pictures", async () => {
  vi.mocked(getComponentAttachments).mockResolvedValue({ ...family, attachments: [] });
  renderModulePage();

  await screen.findByText(t.images.ownEmpty);
  // Not the "nothing mirrored anywhere" message: there is something to see.
  expect(screen.queryByText(t.images.empty)).toBeNull();
  expect(within(childSection()).getByRole("img")).toBeTruthy();
});

it("falls back to the empty state when the whole family has none", async () => {
  vi.mocked(getComponentAttachments).mockResolvedValue({
    component_sn: MODULE_SN,
    attachments: [],
    children: [],
  });
  renderModulePage();

  await screen.findByText(t.images.empty);
  expect(screen.queryByRole("heading", { name: t.images.childrenTitle })).toBeNull();
});

it("never renders a child image the mirror does not hold", async () => {
  vi.mocked(getComponentAttachments).mockResolvedValue({
    ...family,
    attachments: [],
    children: [
      {
        ...family.children[0],
        attachments: [image("not-here", { stored: false })],
      },
    ],
  });
  renderModulePage();

  await waitFor(() => expect(vi.mocked(getComponentAttachments)).toHaveBeenCalled());
  await screen.findByText(t.images.empty);
  expect(screen.queryByRole("heading", { name: t.images.childrenTitle })).toBeNull();
});
