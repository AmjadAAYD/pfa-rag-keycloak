"""Read the synthetic document corpus and its access rules."""

import json
from collections.abc import Set
from dataclasses import dataclass
from io import StringIO
from pathlib import Path


DEPARTMENTS = frozenset({"rh", "finance", "informatique", "operations"})
KNOWN_ROLES = DEPARTMENTS | {"direction"}
LEVELS = frozenset({"commun", "interne", "confidentiel"})
TEXT_FIELDS = ("id", "project", "department", "confidentiality", "title", "text")


@dataclass(frozen=True)
class Document:
    id: str
    project: str
    department: str
    confidentiality: str
    title: str
    text: str
    allowed_roles: frozenset[str]

    def can_read(self, roles: Set[str]) -> bool:
        return not self.allowed_roles.isdisjoint(roles)


def load_corpus(path: Path) -> dict[str, Document]:
    return parse_corpus(path.read_bytes(), path)


def parse_corpus(data: bytes, path: Path) -> dict[str, Document]:
    documents = {}
    with StringIO(data.decode("utf-8"), newline=None) as source:
        for line_number, line in enumerate(source, start=1):
            try:
                document = _parse_document(json.loads(line))
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            if document.id in documents:
                raise ValueError(f"{path}:{line_number}: duplicate document ID {document.id!r}")
            documents[document.id] = document

    if not documents:
        raise ValueError(f"{path}: the corpus is empty")
    return documents


def _parse_document(record: object) -> Document:
    if not isinstance(record, dict):
        raise ValueError("expected a document object")

    fields = {name: record.get(name) for name in TEXT_FIELDS}
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a nonempty string")
    if fields["department"] not in DEPARTMENTS:
        raise ValueError("unknown department")
    if fields["confidentiality"] not in LEVELS:
        raise ValueError("unknown confidentiality level")

    roles = record.get("allowed_roles")
    if not isinstance(roles, list) or not roles or any(
        not isinstance(role, str) or role not in KNOWN_ROLES for role in roles
    ):
        raise ValueError("allowed_roles must be a nonempty list of known roles")

    return Document(**fields, allowed_roles=frozenset(roles))
