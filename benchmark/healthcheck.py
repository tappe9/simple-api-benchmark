"""Health-policy support for the non-publishing benchmark investigation."""

from .registry import implementation
from .results import require

CONTAINER_HEALTHCHECK = "container-healthcheck"
EXTERNAL_READINESS = "external-readiness"
_POLICIES = (CONTAINER_HEALTHCHECK, EXTERNAL_READINESS)


def validate_policy(value: str) -> str:
    """Accept only explicit benchmark API health-policy names."""
    require(type(value) is str and value in _POLICIES, "unsupported API health policy")
    return value


def override_text(implementation_id: str) -> str:
    """Disable only one registered API healthcheck in a Compose override."""
    implementation(implementation_id)
    return f"services:\n  {implementation_id}:\n    healthcheck:\n      disable: true\n"
