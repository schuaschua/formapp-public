"""Story 1.3: domain code takes an injectable Clock and never reads the system clock (AD-18)."""

from datetime import UTC, datetime, timedelta
from textwrap import dedent

from domain.clock import Clock
from tests.domain.source_rules import domain_sources, system_clock_calls
from tests.fakes import FakeClock


def test_story_1_3_domain_never_calls_the_system_clock() -> None:
    violations = {
        str(path.name): found
        for path, source in domain_sources()
        if (found := system_clock_calls(source))
    }

    assert violations == {}


def test_story_1_3_clock_rule_catches_violations() -> None:
    source = dedent(
        """\
        import datetime, time
        from datetime import date
        from time import time_ns
        a = datetime.datetime.now()
        b = datetime.now(UTC)
        c = date.today()
        d = time.time()
        e = 'SELECT * FROM proposal WHERE lock_expires_at < now()'
        f = 'UPDATE proposal SET updated_at = CURRENT_TIMESTAMP'
        g = 'WHERE lock_expires_at < :now'
        '''A docstring may say now() in prose.'''
        """
    )

    assert sorted(system_clock_calls(source)) == [
        "SQL CURRENT_TIMESTAMP",
        "SQL now()",
        "date.today",
        "datetime.now",
        "datetime.now",
        "from time import time_ns",
        "time.time",
    ]


def test_story_1_3_fake_clock_is_a_settable_clock() -> None:
    start = datetime(2026, 9, 26, 9, 0, tzinfo=UTC)
    clock: Clock = FakeClock(start)

    assert clock.now() == start
    assert isinstance(clock, FakeClock)
    clock.advance(timedelta(seconds=61))
    assert clock.now() == start + timedelta(seconds=61)
    clock.set(start)
    assert clock.now() == start


def test_story_1_3_clock_rule_catches_aliased_imports() -> None:
    source = dedent(
        """\
        import datetime as dt
        import time as t
        from datetime import datetime as DateTime, date as Day
        a = dt.datetime.now()
        b = DateTime.now()
        c = Day.today()
        d = t.time()
        e = t.time_ns()
        """
    )

    assert sorted(system_clock_calls(source)) == [
        "date.today",
        "datetime.now",
        "datetime.now",
        "time.time",
        "time.time_ns",
    ]
