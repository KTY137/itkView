// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-96a8e346cc49
import { describe, expect, it } from "vitest";

import { deriveAuthCapabilities } from "./auth";
import { product, productForVariant, setProductDocumentTitle } from "./product";

describe("product variants", () => {
  it("defaults to itkView and fails closed for unknown variants", () => {
    expect(productForVariant(undefined)).toEqual({
      variant: "view",
      name: "itkView",
      brandPrefix: "itk",
      brandAccent: "View",
      csrfCookie: "itkview_csrf",
      workflowWrites: false,
    });
    expect(productForVariant("anything-else")).toEqual(productForVariant(undefined));
  });

  it("keeps the shared itkFlow surface behind an explicit build selection", () => {
    expect(productForVariant(" FLOW ")).toEqual({
      variant: "flow",
      name: "itkFlow",
      brandPrefix: "itk",
      brandAccent: "Flow",
      csrfCookie: "itkflow_csrf",
      workflowWrites: true,
    });
    // The shared regression suite opts into Flow in vitest.config.ts. Runtime
    // builds do not receive that test-only environment value.
    expect(product).toEqual(productForVariant("flow"));
  });

  it("defines itkView branding, title, CSRF cookie and a hard workflow-write gate", () => {
    const view = productForVariant(" VIEW ");
    expect(view).toEqual({
      variant: "view",
      name: "itkView",
      brandPrefix: "itk",
      brandAccent: "View",
      csrfCookie: "itkview_csrf",
      workflowWrites: false,
    });

    const titleTarget = { title: "old title" };
    setProductDocumentTitle(view, titleTarget);
    expect(titleTarget.title).toBe("itkView");
  });

  it("never grants itkView workflow writes to an admin or demo session but keeps sync", () => {
    const view = productForVariant("view");
    expect(deriveAuthCapabilities("admin", false, view.workflowWrites)).toEqual({
      canWrite: false,
      canSync: true,
      isAdmin: true,
    });
    expect(deriveAuthCapabilities(null, true, view.workflowWrites)).toEqual({
      canWrite: false,
      canSync: true,
      isAdmin: true,
    });
  });

  it("preserves the existing itkFlow operator/admin/demo capability surface", () => {
    const flow = productForVariant("flow");
    expect(deriveAuthCapabilities("admin", false, flow.workflowWrites).canWrite).toBe(true);
    expect(deriveAuthCapabilities("operator", false, flow.workflowWrites).canWrite).toBe(true);
    expect(deriveAuthCapabilities(null, true, flow.workflowWrites).canWrite).toBe(true);
    expect(deriveAuthCapabilities("viewer", false, flow.workflowWrites)).toEqual({
      canWrite: false,
      canSync: false,
      isAdmin: false,
    });
  });
});
