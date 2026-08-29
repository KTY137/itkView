// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-7be19d31a166
/**
 * What a data-entry panel needs from the server before it can render the
 * sheet's layout: the institute's profile (field order, which fields hold a
 * tool) and the tool registry to populate those fields from.
 *
 * Loaded lazily — only once a form is actually open. An operator who never
 * opens one pays nothing, and the component detail page keeps the request
 * count it had before.
 *
 * Fails soft on purpose. An unreachable or malformed profile must degrade to
 * "no layout configured" (the definition's own order, no tool dropdown), never
 * block test entry: recording a run is the thing the operator came for, and a
 * cosmetic ordering must not be able to stop it. A tool-registry failure is
 * reported, because there the consequence is visible — an empty dropdown.
 */
import { useEffect, useState } from "react";

import { getInstitutes, getTools } from "./api";
import type { Tool } from "./api";
import { EMPTY_LAYOUT, parseDataEntryLayout } from "./fieldLayout";
import type { DataEntryLayout } from "./fieldLayout";

export type DataEntryProfile = {
  layout: DataEntryLayout;
  tools: Tool[];
  loading: boolean;
  /** Set only when the tool registry could not be read. */
  toolsError: string | null;
};

export type UseDataEntryProfileOptions = {
  instituteCode?: string;
  /** Restricts the registry to tools that fit this exact PDB component type code. */
  componentTypeCode?: string;
  /** Nothing is fetched until a panel actually needs it. */
  enabled: boolean;
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function useDataEntryProfile({
  instituteCode,
  componentTypeCode,
  enabled,
}: UseDataEntryProfileOptions): DataEntryProfile {
  const [layout, setLayout] = useState<DataEntryLayout>(EMPTY_LAYOUT);
  const [tools, setTools] = useState<Tool[]>([]);
  const [loading, setLoading] = useState(false);
  const [resolvedRequest, setResolvedRequest] = useState<string | null>(null);
  const [toolsError, setToolsError] = useState<string | null>(null);
  const requestKey = JSON.stringify([instituteCode ?? null, componentTypeCode ?? null]);

  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    let live = true;
    setLoading(true);
    setToolsError(null);

    // Two independent requests: a broken institute profile must not cost the
    // operator the tool list, and vice versa.
    const layoutRequest = getInstitutes(controller.signal)
      .then((institutes) => {
        if (!live) return;
        const institute =
          instituteCode === undefined
            ? null
            : (institutes.find((item) => item.code === instituteCode) ?? null);
        setLayout(institute === null ? EMPTY_LAYOUT : parseDataEntryLayout(institute.settings));
      })
      .catch(() => {
        if (live) setLayout(EMPTY_LAYOUT);
      });

    const toolsRequest = getTools(
      {
        status: "active",
        ...(instituteCode === undefined ? {} : { institute: instituteCode }),
      },
      controller.signal,
    )
      .then((found) => {
        if (live) setTools(found);
      })
      .catch((error: unknown) => {
        if (!live || controller.signal.aborted) return;
        setTools([]);
        setToolsError(errorMessage(error));
      });

    void Promise.all([layoutRequest, toolsRequest]).finally(() => {
      if (live) {
        setResolvedRequest(requestKey);
        setLoading(false);
      }
    });

    return () => {
      live = false;
      controller.abort();
    };
  }, [enabled, instituteCode, componentTypeCode, requestKey]);

  // Effects run after render. Without the resolved-key check, a newly opened
  // form gets one frame of the unconfigured free-text schema before loading
  // flips to true; an operator can type or even submit during that window.
  return {
    layout,
    tools,
    loading: enabled && (loading || resolvedRequest !== requestKey),
    toolsError,
  };
}
