from app.main import app


def test_calendar_write_routes_are_not_registered():
    assert not any("/schedule" in route.path for route in app.routes)


def test_approval_and_export_routes_remain_registered():
    paths = {route.path for route in app.routes}
    assert "/api/projects/{project_id}/clips/{clip_id}/approve" in paths
    assert "/api/clips/{clip_id}/export" in paths
