"""Story 1.7: the x-fill: db questions and their fixed customer columns (FR45, AD-10, AD-13)."""

import pytest

from domain.customer_fields import (
    ColumnType,
    DbColumn,
    UnmappedDbQuestionError,
    db_columns,
)
from domain.schema import freeze, load_schema, questions

TEXT, DATE = ColumnType.TEXT, ColumnType.DATE


def test_story_1_7_v1_db_questions_map_to_fixed_customer_columns() -> None:
    assert db_columns(load_schema(1)) == (
        DbColumn("C1", "first_name", TEXT),
        DbColumn("C13", "last_name", TEXT),
        DbColumn("C2", "date_of_birth", DATE),
        DbColumn("C3", "sex_at_birth", TEXT),
        DbColumn("C4", "country_of_origin", TEXT),
        DbColumn("C5", "country_of_residence", TEXT),
        DbColumn("C6", "id_number", TEXT),
        DbColumn("C7", "email", TEXT),
        DbColumn("C8", "mobile", TEXT),
        DbColumn("C9", "street_address", TEXT),
        DbColumn("C14", "city", TEXT),
        DbColumn("C15", "postcode", TEXT),
        DbColumn("C10", "occupation", TEXT),
        DbColumn("C11", "marital_status", TEXT),
        DbColumn("C12", "income_range", TEXT),
    )


def test_story_1_7_column_types_are_text_or_date() -> None:
    assert {column.type.value for column in db_columns(load_schema(1))} == {
        "text",
        "date",
    }


def test_story_1_7_date_columns_are_exactly_the_date_questions() -> None:
    schema = load_schema(1)

    for column in db_columns(schema):
        is_date = questions(schema)[column.question_id].get("format") == "date"
        assert (column.type is DATE) == is_date, column.question_id


def test_story_1_7_a_db_question_without_a_column_is_an_error() -> None:
    schema = freeze(
        {
            "properties": {
                "C1": {"type": "string", "x-fill": "db"},
                "C99": {"type": "string", "x-fill": "db"},
            }
        }
    )

    with pytest.raises(UnmappedDbQuestionError) as caught:
        db_columns(schema)

    assert isinstance(caught.value, LookupError)
    assert caught.value.question_id == "C99"
