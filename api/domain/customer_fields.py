"""The ``customer`` columns behind the ``x-fill: db`` questions (spine AD-7, AD-10, AD-13).

Column names are fixed here, not derived from question text, so a later schema version can't rename a
database column by accident. Story 1.8's ``customer`` migration and the customer lookup use this list.
"""

from dataclasses import dataclass
from enum import StrEnum

from domain.schema import Schema, questions


class ColumnType(StrEnum):
    """The database type of a ``customer`` column."""

    TEXT = "text"
    DATE = "date"


@dataclass(frozen=True, slots=True)
class DbColumn:
    """One ``x-fill: db`` question and the ``customer`` column that stores it."""

    question_id: str
    column: str
    type: ColumnType


class UnmappedDbQuestionError(LookupError):
    """A schema has an ``x-fill: db`` question with no fixed ``customer`` column."""

    def __init__(self, question_id: str) -> None:
        super().__init__(f"x-fill: db question {question_id} has no customer column.")
        self.question_id = question_id


_COLUMNS: dict[str, tuple[str, ColumnType]] = {
    "C1": ("first_name", ColumnType.TEXT),
    "C13": ("last_name", ColumnType.TEXT),
    "C2": ("date_of_birth", ColumnType.DATE),
    "C3": ("sex_at_birth", ColumnType.TEXT),
    "C4": ("country_of_origin", ColumnType.TEXT),
    "C5": ("country_of_residence", ColumnType.TEXT),
    "C6": ("id_number", ColumnType.TEXT),
    "C7": ("email", ColumnType.TEXT),
    "C8": ("mobile", ColumnType.TEXT),
    "C9": ("street_address", ColumnType.TEXT),
    "C14": ("city", ColumnType.TEXT),
    "C15": ("postcode", ColumnType.TEXT),
    "C10": ("occupation", ColumnType.TEXT),
    "C11": ("marital_status", ColumnType.TEXT),
    "C12": ("income_range", ColumnType.TEXT),
}


def db_columns(schema: Schema) -> tuple[DbColumn, ...]:
    """Return the ``x-fill: db`` questions in schema order, each with its ``customer`` column."""
    columns = []
    for qid, question in questions(schema).items():
        if question.get("x-fill") != "db":
            continue
        if qid not in _COLUMNS:
            raise UnmappedDbQuestionError(qid)
        column, column_type = _COLUMNS[qid]
        columns.append(DbColumn(question_id=qid, column=column, type=column_type))
    return tuple(columns)
