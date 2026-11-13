"""S3 (RGW) client wrapper for the home archive. Keys: ``u/<uid>/<relpath>``."""
from typing import BinaryIO

MTIME_META = "mtime"


def _check_uid(uid: str) -> str:
    if not uid or "/" in uid or uid in (".", ".."):
        raise ValueError(f"invalid uid: {uid!r}")
    return uid


def _check_rel(relpath: str) -> str:
    parts = relpath.split("/")
    if relpath.startswith("/") or any(p in ("", "..") for p in parts):
        raise ValueError(f"invalid relpath: {relpath!r}")
    return relpath


class ArchiveStore:
    def __init__(self, client=None, bucket: str = "", settings=None):
        if client is None:
            import boto3

            if settings is None:
                from app.config import Settings

                settings = Settings()
            if not settings.archive_s3_endpoint:
                raise RuntimeError("archive disabled: archive_s3_endpoint is empty")
            client = boto3.client(
                "s3",
                endpoint_url=settings.archive_s3_endpoint,
                aws_access_key_id=settings.archive_s3_access_key,
                aws_secret_access_key=settings.archive_s3_secret_key,
            )
            bucket = bucket or settings.archive_s3_bucket
        self._c = client
        self._bucket = bucket

    def _key(self, uid: str, relpath: str) -> str:
        return f"u/{_check_uid(uid)}/{_check_rel(relpath)}"

    def put(self, uid: str, relpath: str, fileobj: BinaryIO, mtime: float) -> None:
        self._c.upload_fileobj(
            fileobj, self._bucket, self._key(uid, relpath),
            ExtraArgs={"Metadata": {MTIME_META: repr(float(mtime))}},
        )

    def _mtime(self, key: str) -> float:
        meta = self._c.head_object(Bucket=self._bucket, Key=key).get("Metadata", {})
        return float(meta.get(MTIME_META, 0.0))

    def list_with_size(self, uid: str) -> list[tuple[str, int, float]]:
        prefix = f"u/{_check_uid(uid)}/"
        out: list[tuple[str, int, float]] = []
        token = None
        while True:
            kw = {"Bucket": self._bucket, "Prefix": prefix}
            if token:
                kw["ContinuationToken"] = token
            resp = self._c.list_objects_v2(**kw)
            for o in resp.get("Contents", []):
                out.append((o["Key"][len(prefix):], int(o.get("Size", 0)),
                            self._mtime(o["Key"])))
            if not resp.get("IsTruncated"):
                return out
            token = resp.get("NextContinuationToken")

    def list(self, uid: str) -> list[tuple[str, float]]:
        return [(r, m) for r, _, m in self.list_with_size(uid)]

    def get(self, uid: str, relpath: str, fileobj: BinaryIO) -> float:
        key = self._key(uid, relpath)
        self._c.download_fileobj(self._bucket, key, fileobj)
        return self._mtime(key)

    def delete(self, uid: str, relpath: str) -> None:
        self._c.delete_object(Bucket=self._bucket, Key=self._key(uid, relpath))
