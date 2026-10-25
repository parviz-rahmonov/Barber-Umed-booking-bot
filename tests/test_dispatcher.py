
from main import create_dispatcher


def test_dispatcher_registers_handlers():
    dp = create_dispatcher(admin_id=123456)

    assert dp["admin_id"] == 123456

    expected_routers = {
        "admin",
        "client_start",
        "client_info",
        "client_reviews",
        "admin_v2",
        "client_booking",
    }

    actual_routers = {
        router.name for router in dp.sub_routers
    }

    assert actual_routers == expected_routers
