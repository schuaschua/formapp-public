"""Story 1.7: the domain schema loader: latest version, load by version, immutable (AD-7)."""

import json
from pathlib import Path

import pytest
from jsonschema.exceptions import SchemaError

from domain.schema import (
    SCHEMA_DIR,
    SchemaVersionMismatchError,
    UnknownSchemaVersionError,
    freeze,
    latest_version,
    load_schema,
    questions,
    thaw,
)
from tests.support import FORM_SCHEMA_DIR


def test_story_1_7_loader_reads_the_repo_form_schema_folder() -> None:
    # The image puts the same files at /form-schema/, which the same path expression finds.
    assert SCHEMA_DIR == FORM_SCHEMA_DIR.resolve()


def test_form_222_latest_version_is_2_with_the_v2_document() -> None:
    # FORM-222: v2.json lands alongside v1.json (never edited, AD-7), so the loader's own repo-
    # folder scan now finds 2 as the highest version.
    schema = load_schema(latest_version())

    assert latest_version() == 2
    assert schema["$id"] == "urn:formapp:form-schema:v2"
    assert thaw(schema) == json.loads((FORM_SCHEMA_DIR / "v2.json").read_text())


def test_story_1_7_v1_still_loads_by_its_own_version_number() -> None:
    schema = load_schema(1)

    assert schema["$id"] == "urn:formapp:form-schema:v1"
    assert thaw(schema) == json.loads((FORM_SCHEMA_DIR / "v1.json").read_text())


@pytest.mark.parametrize("version", [3, 0, -1, True, "1"])
def test_story_1_7_unknown_version_is_an_error(version: object) -> None:
    with pytest.raises(UnknownSchemaVersionError) as caught:
        load_schema(version)  # type: ignore[arg-type]  # a bad caller's value

    assert isinstance(caught.value, LookupError)
    assert caught.value.version == version


def test_story_1_7_a_loaded_schema_can_never_be_changed() -> None:
    schema = load_schema(1)

    with pytest.raises(TypeError):
        schema["properties"]["N1"]["enum"] = ["other"]
    with pytest.raises(TypeError):
        schema["required"][0] = "Z9"
    with pytest.raises(TypeError):
        del schema["properties"]["C1"]
    with pytest.raises(AttributeError):
        schema["required"].append("Z9")

    again = load_schema(1)
    assert again is schema
    assert list(again["properties"]["N1"]["enum"]) == ["life", "life_health", "health"]
    assert "C1" in questions(again)


def test_story_1_7_thaw_gives_an_independent_mutable_copy() -> None:
    schema = load_schema(1)
    copy = thaw(schema)

    copy["properties"]["N1"]["enum"].append("other")

    assert "other" not in load_schema(1)["properties"]["N1"]["enum"]
    assert freeze({"a": [1, {"b": 2}]})["a"][1]["b"] == 2


def _write(directory: Path, name: str, document: object) -> None:
    (directory / name).write_text(json.dumps(document), encoding="utf-8")


def _schema(version: int) -> dict[str, object]:
    return {"$id": f"urn:formapp:form-schema:v{version}", "type": "object"}


def test_story_1_7_latest_is_the_highest_version_file(tmp_path: Path) -> None:
    for version in (1, 2, 10):
        _write(tmp_path, f"v{version}.json", _schema(version))
    for name in ("v0.json", "v01.json", "vx.json", "lint.py.json"):
        _write(tmp_path, name, {})

    assert latest_version(tmp_path) == 10
    assert load_schema(2, tmp_path)["type"] == "object"
    with pytest.raises(UnknownSchemaVersionError):
        load_schema(3, tmp_path)


def test_story_1_7_no_schema_files_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(UnknownSchemaVersionError):
        latest_version(tmp_path)


def test_story_1_7_an_invalid_schema_file_is_never_loaded(tmp_path: Path) -> None:
    _write(tmp_path, "v1.json", _schema(1) | {"type": "no-such-type"})

    with pytest.raises(SchemaError):
        load_schema(1, tmp_path)


def test_story_1_7_a_file_whose_id_names_another_version_is_never_loaded(
    tmp_path: Path,
) -> None:
    # v2.json copied from v1 without updating $id.
    _write(tmp_path, "v2.json", _schema(1))
    _write(tmp_path, "v3.json", {"type": "object"})

    with pytest.raises(SchemaVersionMismatchError):
        load_schema(2, tmp_path)
    with pytest.raises(SchemaVersionMismatchError):
        load_schema(3, tmp_path)
