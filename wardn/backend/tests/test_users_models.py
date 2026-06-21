from app.modules.users.models import User


def test_display_name_uses_first_and_last_name() -> None:
    user = User(
        email="admin@example.com",
        first_name="Ada",
        last_name="Lovelace",
    )

    assert user.display_name == "Ada Lovelace"


def test_display_name_falls_back_to_email() -> None:
    user = User(
        email="admin@example.com",
        first_name="",
        last_name="",
    )

    assert user.display_name == "admin@example.com"
