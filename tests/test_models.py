
from database.models import Base


def test_required_tables():
    expected_tables = {
        "users",
        "services",
        "working_hours",
        "days_off",
        "bookings",
        "payments",
        "notifications",
        "barber_profile",
        "reviews",
    }

    actual_tables = set(Base.metadata.tables)

    assert actual_tables == expected_tables
