# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-FileComment: itkflow-provenance-root
"""Where this build came from, stated by the build itself.

Every source file carries an SPDX header with a per-file id, which survives
formatters and refactoring but only travels with the file. This module is the
runtime half: a running instance names its origin over `/health` and in the
interface, so a deployed copy is identifiable without reading its source.

Deliberately not hidden. Zero-width characters and disguised constants are
removed by the first formatter that touches them, break parsers, and mislead
whoever maintains the file next; a marker that a maintainer cannot see is one
they will delete by accident. This one is stated plainly and is therefore
still there in a year.
"""

from __future__ import annotations

COPYRIGHT_HOLDER = "Kaya Yesilyurt"
COPYRIGHT_YEAR = "2026"
LICENSE = "MIT"

# Stable across builds: it identifies the project lineage, not one compilation.
# Changing it makes older deployments unattributable, so it is not a version.
PROVENANCE_ID = "itkflow-0e5c1a7d4b92"


def notice() -> str:
    """One line naming holder, year and licence, for the interface footer."""
    return f"© {COPYRIGHT_YEAR} {COPYRIGHT_HOLDER} · {LICENSE}"
