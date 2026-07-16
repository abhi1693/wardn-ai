from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

from app.db.errors import integrity_constraint_name, is_constraint_violation


def test_integrity_constraint_name_reads_driver_diagnostics() -> None:
    error = IntegrityError(
        "insert",
        {},
        SimpleNamespace(diag=SimpleNamespace(constraint_name="uq_example_name")),
    )

    assert integrity_constraint_name(error) == "uq_example_name"
    assert is_constraint_violation(error, {"uq_example_name"}) is True


def test_constraint_match_does_not_mask_a_different_reported_constraint() -> None:
    error = IntegrityError(
        "insert mentioning uq_expected_name",
        {},
        SimpleNamespace(constraint_name="fk_actual_owner"),
    )

    assert is_constraint_violation(error, {"uq_expected_name"}) is False


def test_constraint_match_supports_drivers_without_structured_diagnostics() -> None:
    error = IntegrityError("insert", {}, Exception("violates uq_example_name"))

    assert is_constraint_violation(error, {"uq_example_name"}) is True
