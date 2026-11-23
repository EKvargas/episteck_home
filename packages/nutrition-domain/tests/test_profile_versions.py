from datetime import date

from nutrition_domain.profile_versions import VersionRef, version_in_force


def V(n, d, origin):
    return VersionRef(n, date.fromisoformat(d), origin)


def test_first_profile_version_reaches_back_over_mode_only_versions():
    vs = [V(1, "2026-11-25", "MODE"), V(2, "2026-12-10", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 20)) == 2
    assert version_in_force(vs, date(2026, 12, 1)) == 2
    assert version_in_force(vs, date(2026, 12, 11)) == 2


def test_same_day_correction_reaches_back():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2026-11-23", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 21)) == 2


def test_same_day_mode_switch_reaches_back():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2026-11-23", "MODE")]
    assert version_in_force(vs, date(2026, 11, 22)) == 2
    assert version_in_force(vs, date(2026, 11, 23)) == 2


def test_next_day_correction_starts_that_day():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2026-11-24", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 21)) == 1
    assert version_in_force(vs, date(2026, 11, 23)) == 1
    assert version_in_force(vs, date(2026, 11, 24)) == 2


def test_mode_switch_after_onboarding_applies_from_its_day():
    vs = [V(1, "2026-11-23", "PROFILE"), V(2, "2027-06-01", "MODE")]
    assert version_in_force(vs, date(2027, 5, 31)) == 1 and version_in_force(vs, date(2027, 6, 1)) == 2


def test_migrated_never_reaches_back():
    vs = [V(1, "2026-11-30", "MIGRATED")]
    assert version_in_force(vs, date(2026, 11, 29)) is None and version_in_force(vs, date(2026, 11, 30)) == 1


def test_order_of_input_does_not_matter():
    vs = [V(2, "2026-11-23", "PROFILE"), V(1, "2026-11-23", "PROFILE")]
    assert version_in_force(vs, date(2026, 11, 1)) == 2
    assert version_in_force(vs, date(2026, 11, 23)) == 2


def test_no_versions():
    assert version_in_force([], date(2026, 11, 23)) is None
