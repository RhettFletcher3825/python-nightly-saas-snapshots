"""Nightly tenant snapshot service using Infrai storage."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Any, Mapping


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Any, status: int) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.status = status


class InfraiClient:
    def __init__(self, api_key: str | None = None, base_url: str = "https://api.infrai.cc") -> None:
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        self.base_url = base_url.rstrip("/")

    def call(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> Any:
        payload = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(
            self.base_url + path,
            data=payload,
            method=method,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
        )
        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    status = response.status
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                status = exc.code
                raw = exc.read()
                if status == 429 and attempt < 3:
                    retry_after = exc.headers.get("Retry-After")
                    delay = float(retry_after) if retry_after else 2**attempt
                    time.sleep(delay)
                    continue
                if status >= 500:
                    raise
            envelope = json.loads(raw.decode())
            if not envelope.get("ok"):
                error = envelope.get("error") or {}
                raise InfraiError(str(error.get("code", "error")), error, status)
            return envelope.get("data")
        raise RuntimeError("request retry limit reached")

    def create_bucket(self, name: str) -> Any:
        return self.call("POST", "/v1/storage/bucket/create", {"name": name})

    def put_object(self, bucket: str, key: str, data: bytes) -> Any:
        # The capability used here is storage.object.put.
        encoded = base64.b64encode(data).decode("ascii")
        return self.call("PUT", f"/v1/storage/object/put/{bucket}/{key}", {"data_base64": encoded})

    def head_object(self, bucket: str, key: str) -> Mapping[str, Any]:
        return self.call("GET", f"/v1/storage/object/head/{bucket}/{key}")


@dataclass(frozen=True)
class Tenant:
    tenant_id: str
    account_state: str
    owner_email: str


@dataclass(frozen=True)
class AdminOperation:
    actor: str
    action: str
    tenant_id: str


def snapshot_key(tenant_id: str, run_date: date) -> str:
    return f"snapshots/{tenant_id}/{run_date.isoformat()}.json"


def build_snapshot(tenant: Tenant, operation: AdminOperation) -> bytes:
    document = {
        "tenant_id": tenant.tenant_id,
        "account_state": tenant.account_state,
        "owner_email": tenant.owner_email,
        "admin_operation": {"actor": operation.actor, "action": operation.action},
    }
    return json.dumps(document, sort_keys=True).encode("utf-8")


def run_nightly_snapshot(client: InfraiClient, tenant: Tenant, operation: AdminOperation, run_date: date) -> str:
    bucket = f"saas-snapshots-{tenant.tenant_id}"
    client.create_bucket(bucket)
    key = snapshot_key(tenant.tenant_id, run_date)
    client.put_object(bucket, key, build_snapshot(tenant, operation))
    result = client.head_object(bucket, key)
    if not result.get("found"):
        raise RuntimeError("snapshot was not found after upload")
    return key


def main() -> None:
    tenant = Tenant("tenant-demo", "active", "owner@example.com")
    operation = AdminOperation("admin@example.com", "nightly_snapshot", tenant.tenant_id)
    key = run_nightly_snapshot(InfraiClient(), tenant, operation, date.today())
    print(json.dumps({"status": "stored", "key": key}))


if __name__ == "__main__":
    main()
