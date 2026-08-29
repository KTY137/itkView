// SPDX-License-Identifier: MIT
// SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
// SPDX-FileComment: itkflow-fc925bf463f9
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  ApiError,
  deleteShareCredential,
  getShareCredentials,
  putShareCredential,
} from "./api";
import type { ShareCredentialOut } from "./api";
import ShareCredentialsPanel from "./ShareCredentialsPanel";

const { showToast } = vi.hoisted(() => ({ showToast: vi.fn() }));

vi.mock("./auth", () => ({
  useAuth: () => ({ showToast }),
}));

vi.mock("./api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api")>();
  return {
    ...actual,
    deleteShareCredential: vi.fn(),
    getShareCredentials: vi.fn(),
    putShareCredential: vi.fn(),
  };
});

const credential: ShareCredentialOut = {
  id: 17,
  provider_host: "cernbox.cern.ch",
  token_hint: "abc...xyz",
  updated_at: "2026-08-27T12:34:56Z",
};

describe("ShareCredentialsPanel", () => {
  beforeEach(() => {
    vi.mocked(deleteShareCredential).mockReset();
    vi.mocked(getShareCredentials).mockReset();
    vi.mocked(putShareCredential).mockReset();
    showToast.mockReset();
    vi.mocked(getShareCredentials).mockResolvedValue([]);
  });

  it("loads only non-secret metadata and explains the private-CERNBox boundary", async () => {
    vi.mocked(getShareCredentials).mockResolvedValue([credential]);

    render(<ShareCredentialsPanel />);

    expect(screen.getByText(/Loading/)).toBeVisible();
    expect(await screen.findByText("cernbox.cern.ch")).toBeVisible();
    expect(screen.getByText("abc...xyz")).toBeVisible();
    expect(screen.getByText(/Saved:/)).toBeVisible();
    expect(getShareCredentials).toHaveBeenCalledWith(expect.any(AbortSignal));
    expect(
      screen.getByText(/Private CERNBox account links require CERN sign-in/i),
    ).toBeVisible();
    expect(
      screen.getByText(/never asks for or stores your CERN account password/i),
    ).toBeVisible();
    expect(
      screen.getByText(/Access is checked only when evidence sync needs the link/i),
    ).toBeVisible();
  });

  it("saves the write-only URL/password pair for sync, then clears the secret", async () => {
    vi.mocked(putShareCredential).mockResolvedValue(credential);
    const user = userEvent.setup();
    render(<ShareCredentialsPanel />);

    await screen.findByText("No public-share passwords saved yet.");
    const urlInput = screen.getByRole("textbox", { name: "Public share link" });
    const passwordInput = screen.getByLabelText("Share password");
    const secret = "correct horse battery staple";

    expect(passwordInput).toHaveAttribute("type", "password");
    await user.type(urlInput, "https://cernbox.cern.ch/s/abc123");
    await user.type(passwordInput, secret);
    await user.click(screen.getByRole("button", { name: "Save password" }));

    await waitFor(() =>
      expect(putShareCredential).toHaveBeenCalledWith({
        url: "https://cernbox.cern.ch/s/abc123",
        password: secret,
      }),
    );
    await waitFor(() => expect(passwordInput).toHaveValue(""));
    expect(urlInput).toHaveValue("");
    expect(screen.queryByDisplayValue(secret)).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(secret);
    expect(await screen.findByText("cernbox.cern.ch")).toBeVisible();
    expect(showToast).toHaveBeenCalledWith(
      "Public-share password saved. Access will be checked during evidence sync.",
    );
  });

  it("shows the backend detail for a rejected public-link format", async () => {
    vi.mocked(putShareCredential).mockRejectedValue(
      new ApiError(
        "Unprocessable Entity",
        422,
        "This is not a password-capable public share link.",
      ),
    );
    const user = userEvent.setup();
    render(<ShareCredentialsPanel />);

    await screen.findByText("No public-share passwords saved yet.");
    await user.type(
      screen.getByRole("textbox", { name: "Public share link" }),
      "https://cernbox.cern.ch/s/locked",
    );
    await user.type(screen.getByLabelText("Share password"), "wrong password");
    await user.click(screen.getByRole("button", { name: "Save password" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This is not a password-capable public share link.",
    );
  });

  it("removes a saved share password without exposing its secret", async () => {
    vi.mocked(getShareCredentials).mockResolvedValue([credential]);
    vi.mocked(deleteShareCredential).mockResolvedValue();
    const user = userEvent.setup();
    render(<ShareCredentialsPanel />);

    expect(await screen.findByText("cernbox.cern.ch")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Remove" }));

    await waitFor(() => expect(deleteShareCredential).toHaveBeenCalledWith(17));
    expect(
      await screen.findByText("No public-share passwords saved yet."),
    ).toBeVisible();
    expect(screen.queryByText("cernbox.cern.ch")).not.toBeInTheDocument();
    expect(showToast).toHaveBeenCalledWith("Public-share password removed.");
  });
});
