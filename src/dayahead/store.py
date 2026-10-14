"""Where pipeline state lives: a local folder in development, S3 in AWS.

Keys are deterministic (see ``keys``), which is what makes every step safe to
re-run: the same inputs always land on the same object.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol


class Store(Protocol):
    def get_json(self, key: str) -> Any | None: ...
    def put_json(self, key: str, obj: Any) -> None: ...
    def list_keys(self, prefix: str) -> list[str]: ...


def _dumps(obj: Any) -> bytes:
    return json.dumps(obj, indent=1, sort_keys=True).encode()


class LocalStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def get_json(self, key: str) -> Any | None:
        path = self.root / key
        return json.loads(path.read_bytes()) if path.exists() else None

    def put_json(self, key: str, obj: Any) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(_dumps(obj))

    def list_keys(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())


class S3Store:
    def __init__(self, bucket: str, prefix: str = "", client: Any = None):
        if client is None:
            import boto3

            client = boto3.client("s3")
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix.strip("/") else ""
        self._s3 = client

    def get_json(self, key: str) -> Any | None:
        try:
            body = self._s3.get_object(Bucket=self.bucket, Key=self.prefix + key)["Body"].read()
        except self._s3.exceptions.NoSuchKey:
            return None
        return json.loads(body)

    def put_json(self, key: str, obj: Any) -> None:
        self._s3.put_object(
            Bucket=self.bucket,
            Key=self.prefix + key,
            Body=_dumps(obj),
            ContentType="application/json",
        )

    def list_keys(self, prefix: str) -> list[str]:
        keys = []
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix + prefix):
            keys.extend(obj["Key"][len(self.prefix) :] for obj in page.get("Contents", []))
        return sorted(keys)


def open_store(uri: str) -> Store:
    """``s3://bucket/optional/prefix`` or a local directory path."""
    if uri.startswith("s3://"):
        bucket, _, prefix = uri[len("s3://") :].partition("/")
        return S3Store(bucket, prefix)
    return LocalStore(uri)


class keys:
    """Object layout. Raw snapshots are immutable; everything else is derived."""

    @staticmethod
    def raw(series_slug: str, fetched_on: str, chunk_ms: int) -> str:
        return f"raw/smard/{series_slug}/fetched={fetched_on}/{chunk_ms}.json"

    @staticmethod
    def actuals(region: str, day: str) -> str:
        return f"curated/day_ahead_price/{region}/{day}.json"

    @staticmethod
    def forecast(day: str, model: str) -> str:
        return f"forecasts/{day}/{model}.json"

    @staticmethod
    def published(day: str) -> str:
        return f"published/{day}.json"

    LATEST = "published/latest.json"

    @staticmethod
    def score(day: str, model: str) -> str:
        return f"scores/{day}/{model}.json"
