"""The form schema loader (spine AD-7).

Released versions are ``form-schema/v<N>.json`` files shipped in the image at ``/form-schema/`` (in the
repo, next to ``api/``). A released version never changes, so a loaded schema is cached and deeply
frozen: mappings are read-only and lists become tuples.
"""

import json
import re
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

from jsonschema import Draft202012Validator

# domain/schema.py -> api/ (repo) or / (image) -> form-schema/
SCHEMA_DIR = Path(__file__).resolve().parents[2] / "form-schema"
_FILE_NAME = re.compile(r"^v([1-9][0-9]*)\.json$")

Schema = Mapping[str, Any]


class UnknownSchemaVersionError(LookupError):
    """No released schema file has this version."""

    def __init__(self, version: object) -> None:
        super().__init__(f"No form schema version {version!r}.")
        self.version = version


class SchemaVersionMismatchError(ValueError):
    """A schema file's ``$id`` does not name the version in its file name."""

    def __init__(self, version: int, schema_id: object) -> None:
        super().__init__(f"form-schema v{version}.json has $id {schema_id!r}.")
        self.version = version


def _versions(directory: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in directory.glob("v*.json"):
        match = _FILE_NAME.match(path.name)
        if match:
            found[int(match[1])] = path
    return found


def latest_version(directory: Path | None = None) -> int:
    """Return the highest released schema version; a new proposal pins it (AD-7)."""
    versions = _versions(directory or SCHEMA_DIR)
    if not versions:
        raise UnknownSchemaVersionError("latest")
    return max(versions)


def load_schema(version: int, directory: Path | None = None) -> Schema:
    """Return the frozen schema for ``version``; raise ``UnknownSchemaVersionError`` if none."""
    # Checked before the cache, where True would hit the entry for 1.
    if type(version) is not int:
        raise UnknownSchemaVersionError(version)
    return _load(version, (directory or SCHEMA_DIR).resolve())


@cache
def _load(version: int, directory: Path) -> Schema:
    path = _versions(directory).get(version)
    if path is None:
        raise UnknownSchemaVersionError(version)
    document = json.loads(path.read_text(encoding="utf-8"))
    # A copied file that still names another version must never be served as this one.
    if document.get("$id") != f"urn:formapp:form-schema:v{version}":
        raise SchemaVersionMismatchError(version, document.get("$id"))
    # A broken schema file must never be served or validated against.
    Draft202012Validator.check_schema(document)
    frozen: Schema = freeze(document)
    return frozen


def freeze(value: Any) -> Any:
    """Return a deeply read-only copy of parsed JSON: dicts become mapping proxies, lists tuples."""
    if isinstance(value, Mapping):
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(freeze(item) for item in value)
    return value


def thaw(value: Any) -> Any:
    """Return a plain, mutable JSON copy (dicts and lists), as ``jsonschema`` validators expect."""
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [thaw(item) for item in value]
    return value


def questions(schema: Schema) -> Mapping[str, Mapping[str, Any]]:
    """Return the schema's questions by id, in page order."""
    properties: Mapping[str, Mapping[str, Any]] = schema["properties"]
    return properties
