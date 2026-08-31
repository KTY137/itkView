# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-8c851f5d7e62
"""Terminate the Linux PyInstaller child when its onefile bootstrap dies."""

from __future__ import annotations

import ctypes
import os
import signal
import sys


def install_linux_parent_death_signal() -> None:
    if not sys.platform.startswith("linux"):
        return

    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [
        ctypes.c_int,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
        ctypes.c_ulong,
    ]
    prctl.restype = ctypes.c_int
    if prctl(1, int(signal.SIGTERM), 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        error = ctypes.get_errno()
        raise OSError(error, "could not install the Linux parent-death signal")

    # Close the race where the bootstrap exits between process creation and
    # PR_SET_PDEATHSIG. PID 1 means this child has already been re-parented.
    if os.getppid() == 1:
        os.kill(os.getpid(), signal.SIGTERM)


install_linux_parent_death_signal()
