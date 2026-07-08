"""DUMMY write scope for the production PDB (docs/09, ADR 003).

There is no PDB test server. The strips community separates test parts from
real production via the DUMMY batch prefix (batch names are
``[Phase]_[Institute]``, e.g. ``DUMMY_TUDO``): institutes may freely register
hybrids and modules for testing, but there is **no** dummy mechanism for
sensors or ASICs — registering one corrupts collaboration serial numbering.

itkFlow enforces that policy in code:

- a component may only be *registered* if its component type is on the
  configured allowlist (`Settings.pdb_dummy_component_types`, hybrids/modules)
  and its batch carries the DUMMY prefix;
- a component may only be *written to* (test-run upload, stage move) if it is
  present in the local mirror with ``is_dummy=True`` — a flag only set when
  itkFlow registered the part itself (or the PDB reports it as dummy).
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Component

# Collaboration-wide batch phase for test parts (module meeting intro slides:
# batch = [Phase]_[Institute], phase one of PPA/PPB/…/DUMMY).
DUMMY_BATCH_PREFIX = "DUMMY"


def dummy_batch_name(institute_code: str) -> str:
    """Batch name for this institute's test parts, e.g. ``DUMMY_TUDO``."""
    return f"{DUMMY_BATCH_PREFIX}_{institute_code}"


def is_registrable_type(component_type: str, settings: Settings) -> bool:
    """True if itkFlow may register this component type as a DUMMY part.

    Strict allowlist: anything not listed — sensors and ASICs above all — is
    refused, full stop.
    """
    return component_type in settings.pdb_dummy_component_types


def is_dummy_target(session: Session, sn: str) -> bool:
    """True if `sn` is a known DUMMY test component in the local mirror.

    This is the central write gate: PDB writes in `dummy_only` scope are
    refused unless the target passes this check.
    """
    if not sn:
        return False
    component = session.scalar(select(Component).where(Component.sn == sn))
    return component is not None and bool(component.is_dummy)
