"""Story 2.1: migrations 0002 and 0003 create and seed the product catalogue (AD-10, AD-17)."""

from collections.abc import Callable, Iterator
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql

from adapters.db.readiness import bundled_head
from adapters.rest.app import create_app
from adapters.settings import Settings
from tests.support import (
    API_USER,
    EXPECTED_PRODUCTS,
    EXPECTED_RIDERS,
    MIGRATOR_ROLE,
    downgrade_migrations,
    run_migrations,
)

Admin = Callable[[str], psycopg.Connection[Any]]

_PRODUCT_COLUMNS = (
    "code, name, type, covers_dependents, policy_terms, sum_assured_min, sum_assured_max, "
    "default_sum_assured, default_term, min_age, max_age, baseline_monthly"
)
_SELECT_PRODUCTS = f"SELECT {_PRODUCT_COLUMNS} FROM product ORDER BY code"  # noqa: S608 -- constant
_SELECT_RIDERS = (
    "SELECT code, product_code, name, baseline_monthly FROM product_rider ORDER BY code"
)
_GOOD_PRODUCT = {
    "code": "SYN1",
    "name": "Synthetic product",
    "type": "life",
    "covers_dependents": True,
    "policy_terms": '[{"code": "10_yrs", "label": "10 yrs"}]',
    "sum_assured_min": "100000.00",
    "sum_assured_max": "200000.00",
    "default_sum_assured": "150000.00",
    "default_term": "10_yrs",
    "min_age": 18,
    "max_age": 60,
    "baseline_monthly": "50.00",
}


def _catalogue(connection: psycopg.Connection[Any]) -> tuple[list[Any], list[Any]]:
    return (
        connection.execute(_SELECT_PRODUCTS).fetchall(),
        connection.execute(_SELECT_RIDERS).fetchall(),
    )


def _insert_product(connection: psycopg.Connection[Any], **changes: Any) -> None:
    row = {**_GOOD_PRODUCT, **changes}
    connection.execute(
        sql.SQL("INSERT INTO product ({}) VALUES ({})").format(
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join(map(sql.Placeholder, row)),
        ),
        row,
    )


def test_story_2_1_tables_and_columns_from_an_empty_database(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        columns = connection.execute(
            "SELECT table_name, column_name, data_type, is_nullable, "
            "character_maximum_length, numeric_precision, numeric_scale "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name IN ('product', 'product_rider') "
            "ORDER BY table_name, ordinal_position"
        ).fetchall()
        foreign_key = connection.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'product_rider'::regclass AND contype = 'f'"
        ).fetchall()
        primary_keys = connection.execute(
            "SELECT conrelid::regclass::text, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid IN ('product'::regclass, 'product_rider'::regclass) "
            "AND contype = 'p' ORDER BY 1"
        ).fetchall()
        indexed = connection.execute(
            "SELECT indexdef FROM pg_indexes WHERE tablename = 'product_rider' "
            "AND indexname = 'ix_product_rider_product_code'"
        ).fetchall()

    code = ("character varying", "NO", 50, None, None)
    name = ("character varying", "NO", 200, None, None)
    money = ("numeric", "NO", None, 12, 2)
    nullable_money = ("numeric", "YES", None, 12, 2)
    age = ("smallint", "NO", None, 16, 0)
    assert columns == [
        ("product", "code", *code),
        ("product", "name", *name),
        ("product", "type", *code),
        ("product", "covers_dependents", "boolean", "NO", None, None, None),
        ("product", "policy_terms", "jsonb", "NO", None, None, None),
        ("product", "sum_assured_min", *nullable_money),
        ("product", "sum_assured_max", *nullable_money),
        ("product", "default_sum_assured", *nullable_money),
        ("product", "default_term", *code),
        ("product", "min_age", *age),
        ("product", "max_age", *age),
        ("product", "baseline_monthly", *money),
        ("product_rider", "code", *code),
        ("product_rider", "product_code", *code),
        ("product_rider", "name", *name),
        ("product_rider", "baseline_monthly", *money),
    ]
    assert primary_keys == [
        ("product", "PRIMARY KEY (code)"),
        ("product_rider", "PRIMARY KEY (code)"),
    ]
    assert foreign_key == [("FOREIGN KEY (product_code) REFERENCES product(code)",)]
    assert len(indexed) == 1


def test_story_2_1_products_hold_exactly_the_content_draft_values(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        products, _ = _catalogue(connection)

    assert [tuple(row) for row in products] == EXPECTED_PRODUCTS


def test_story_2_1_thirteen_riders_on_their_products_with_unique_codes(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _, riders = _catalogue(connection)
        # "Critical illness" on LT20 and on FSH are two riders with their own codes.
        critical_illness = connection.execute(
            "SELECT code, product_code FROM product_rider "
            "WHERE name = 'Critical illness' ORDER BY code"
        ).fetchall()
        with pytest.raises(psycopg.errors.UniqueViolation):
            connection.execute(
                "INSERT INTO product_rider VALUES ('R01', 'FSH', 'Duplicate', 1)"
            )

    assert [tuple(row) for row in riders] == EXPECTED_RIDERS
    assert len({row[0] for row in riders}) == 13
    assert critical_illness == [("R01", "LT20"), ("R05", "FSH"), ("R09", "ELH")]


def test_story_2_1_catalogue_is_loaded_by_the_data_migration(
    admin: Admin, fresh_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_migrations(monkeypatch, fresh_db, revision="0002")
    with admin(fresh_db) as connection:
        assert _catalogue(connection) == ([], [])

    run_migrations(monkeypatch, fresh_db)
    with admin(fresh_db) as connection:
        products, riders = _catalogue(connection)

    assert (len(products), len(riders)) == (5, 13)


def test_story_2_1_downgrade_to_0001_then_upgrade_gives_the_same_catalogue(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    with admin(migrated_db) as connection:
        before = _catalogue(connection)

    downgrade_migrations(monkeypatch, migrated_db, "0001")
    with admin(migrated_db) as connection:
        tables = connection.execute(
            "SELECT to_regclass('product'), to_regclass('product_rider')"
        ).fetchone()
    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        after = _catalogue(connection)
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchall()

    assert tables == (None, None)
    assert after == before
    assert revision == [(bundled_head(),)]


def test_story_2_1_downgrade_to_0002_empties_the_catalogue_and_upgrade_reseeds_it(
    admin: Admin, migrated_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    downgrade_migrations(monkeypatch, migrated_db, "0002")
    with admin(migrated_db) as connection:
        emptied = _catalogue(connection)
    run_migrations(monkeypatch, migrated_db)
    with admin(migrated_db) as connection:
        products, riders = _catalogue(connection)

    assert emptied == ([], [])
    assert [tuple(row) for row in products] == EXPECTED_PRODUCTS
    assert [tuple(row) for row in riders] == EXPECTED_RIDERS


def test_story_2_1_foreign_key_rejects_a_rider_without_a_product(
    admin: Admin, migrated_db: str
) -> None:
    with (
        admin(migrated_db) as connection,
        pytest.raises(psycopg.errors.ForeignKeyViolation),
    ):
        connection.execute(
            "INSERT INTO product_rider VALUES ('R99', 'NOPE', 'Synthetic rider', 5)"
        )


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"min_age": 61, "max_age": 60}, id="min age above max age"),
        pytest.param({"max_age": 71}, id="max age above 70"),
        pytest.param({"min_age": -1}, id="negative min age"),
        pytest.param(
            {"sum_assured_min": "300000.00", "sum_assured_max": "200000.00"},
            id="sum assured min above max",
        ),
        pytest.param({"default_sum_assured": "900000.00"}, id="default above max"),
        pytest.param({"default_sum_assured": None}, id="partly null sum assured"),
        pytest.param({"baseline_monthly": "0"}, id="zero baseline"),
        pytest.param({"policy_terms": "[]"}, id="no policy terms"),
        pytest.param({"policy_terms": '{"code": "x"}'}, id="policy terms not a list"),
        pytest.param({"type": "savings"}, id="unknown type"),
        pytest.param({"default_term": "20_yrs"}, id="default term not a policy term"),
    ],
)
def test_story_2_1_check_constraints_reject_bad_products(
    admin: Admin, migrated_db: str, changes: dict[str, Any]
) -> None:
    with (
        admin(migrated_db) as connection,
        pytest.raises(psycopg.errors.CheckViolation),
    ):
        _insert_product(connection, **changes)


def test_story_2_1_check_constraints_accept_a_good_product_and_rider(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        _insert_product(connection)
        _insert_product(
            connection,
            code="SYN2",
            sum_assured_min=None,
            sum_assured_max=None,
            default_sum_assured=None,
        )
        with pytest.raises(psycopg.errors.CheckViolation):
            connection.execute(
                "INSERT INTO product_rider VALUES ('SYN_R', 'SYN1', 'Synthetic', 0)"
            )
        count = connection.execute(
            "SELECT count(*) FROM product WHERE code LIKE 'SYN%'"
        ).fetchone()

    assert count == (2,)


def test_story_2_1_tables_owned_by_the_migrator_without_rls_and_read_only_for_api(
    admin: Admin, migrated_db: str
) -> None:
    with admin(migrated_db) as connection:
        tables = connection.execute(
            "SELECT relname, pg_get_userbyid(relowner), relrowsecurity, relforcerowsecurity "
            "FROM pg_class WHERE relname IN ('product', 'product_rider') ORDER BY relname"
        ).fetchall()
        privileges = connection.execute(
            "SELECT t.name, p.privilege, has_table_privilege(%s, t.name, p.privilege) "
            "FROM unnest(ARRAY['product', 'product_rider']) AS t(name) "
            "CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', "
            "'REFERENCES', 'TRIGGER']) AS p(privilege)",
            (API_USER,),
        ).fetchall()
        # Nobody but the owner may change the catalogue; PUBLIC holds nothing.
        writers = connection.execute(
            "SELECT DISTINCT pg_get_userbyid(acl.grantee) FROM pg_class AS c "
            "CROSS JOIN LATERAL aclexplode(c.relacl) AS acl "
            "WHERE c.relname IN ('product', 'product_rider') "
            "AND acl.privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')"
        ).fetchall()

    assert tables == [
        ("product", MIGRATOR_ROLE, False, False),
        ("product_rider", MIGRATOR_ROLE, False, False),
    ]
    granted = {(table, privilege) for table, privilege, has in privileges if has}
    assert granted == {("product", "SELECT"), ("product_rider", "SELECT")}
    assert writers == [(MIGRATOR_ROLE,)]


def test_story_2_1_api_user_cannot_change_the_catalogue(
    migrated_db: str, db_settings: Settings
) -> None:
    password = db_settings.database_password
    assert password is not None
    with psycopg.connect(
        host=db_settings.database_host,
        port=db_settings.database_port,
        dbname=migrated_db,
        user=API_USER,
        password=password.get_secret_value(),
        autocommit=True,
    ) as connection:
        assert connection.execute("SELECT count(*) FROM product").fetchone() == (5,)
        for statement in (
            "UPDATE product SET baseline_monthly = 1",
            "DELETE FROM product_rider",
            "TRUNCATE product_rider",
            "INSERT INTO product_rider VALUES ('R99', 'LT20', 'Synthetic', 1)",
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute(statement)


@pytest.fixture
def ready_client(db_settings: Settings, migrated_db: str) -> Iterator[TestClient]:
    settings = db_settings.model_copy(update={"database_name": migrated_db})
    with TestClient(create_app(settings)) as client:
        yield client


def test_story_2_1_readyz_200_at_the_catalogue_head(ready_client: TestClient) -> None:
    response = ready_client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
