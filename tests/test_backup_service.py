from datetime import date

from src.backup_service import AdminOperation, Tenant, build_snapshot, snapshot_key


def test_snapshot_contains_lifecycle_and_admin_context() -> None:
    tenant = Tenant("acme", "suspended", "creator@acme.test")
    operation = AdminOperation("ops@acme.test", "restore_review", "acme")
    assert snapshot_key("acme", date(2026, 9, 7)) == "snapshots/acme/2026-09-07.json"
    assert b'"account_state": "suspended"' in build_snapshot(tenant, operation)
    assert b'"action": "restore_review"' in build_snapshot(tenant, operation)
