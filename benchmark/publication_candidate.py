"""Immutable identities for a locally audited result transaction, not authorization."""

import re
from dataclasses import asdict, dataclass, fields

from .results import require


@dataclass(frozen=True)
class PublicationCandidate:
    """Rebuild from trusted source and raw evidence before trusting serialized values."""

    source: str
    source_tree: str
    commit: str
    tree: str
    run_id: str
    run_attempt: str
    report_sha256: str

    def __post_init__(self) -> None:
        for value in (self.source, self.source_tree, self.commit, self.tree):
            require(
                type(value) is str and re.fullmatch(r"[0-9a-f]{40}", value) is not None,
                "invalid publication candidate SHA",
            )
        for value in (self.run_id, self.run_attempt):
            require(
                type(value) is str and re.fullmatch(r"[1-9][0-9]{0,19}", value) is not None,
                "invalid publication candidate producer identity",
            )
        require(
            type(self.report_sha256) is str
            and re.fullmatch(r"[0-9a-f]{64}", self.report_sha256) is not None,
            "invalid publication candidate report digest",
        )

    @property
    def branch(self) -> str:
        return f"results/verified-{self.run_id}-{self.run_attempt}-{self.source}"

    def as_dict(self) -> dict[str, str]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value) -> "PublicationCandidate":
        require(
            type(value) is dict and set(value) == {field.name for field in fields(cls)},
            "invalid publication candidate fields",
        )
        return cls(**value)
