"""ArchiveStore: S3 wrapper for the home archive (fake client, no network)."""
import io

import pytest

from app.config import Settings
from app.services.archive_store import ArchiveStore


class FakeS3:
    def __init__(self):
        self.objs = {}

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
        self.objs[(bucket, key)] = (fileobj.read(), dict((ExtraArgs or {}).get("Metadata", {})))

    def download_fileobj(self, bucket, key, fileobj):
        fileobj.write(self.objs[(bucket, key)][0])

    def delete_object(self, Bucket, Key):
        self.objs.pop((Bucket, Key), None)

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):
        keys = sorted(k for b, k in self.objs if b == Bucket and k.startswith(Prefix))
        out = []
        for k in keys:
            data, meta = self.objs[(Bucket, k)]
            out.append({"Key": k, "Size": len(data)})
        return {"Contents": out, "IsTruncated": False}

    def head_object(self, Bucket, Key):
        return {"Metadata": self.objs[(Bucket, Key)][1]}


@pytest.fixture
def store():
    return ArchiveStore(client=FakeS3(), bucket="b")


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.archive_s3_endpoint == ""
    assert s.archive_s3_bucket == ""
    assert s.archive_s3_access_key == ""
    assert s.archive_s3_secret_key == ""
    assert s.homes_root == "/homes"


def test_round_trip_keeps_mtime(store):
    store.put("alice", "docs/a.txt", io.BytesIO(b"hi"), 1700000000.5)
    assert ("b", "u/alice/docs/a.txt") in store._c.objs
    out = io.BytesIO()
    mtime = store.get("alice", "docs/a.txt", out)
    assert out.getvalue() == b"hi"
    assert mtime == 1700000000.5
    assert store.list("alice") == [("docs/a.txt", 1700000000.5)]


def test_list_only_that_uid(store):
    store.put("alice", "a", io.BytesIO(b"1"), 1.0)
    store.put("alice2", "b", io.BytesIO(b"2"), 2.0)
    assert [r for r, _ in store.list("alice")] == ["a"]


def test_delete(store):
    store.put("alice", "a", io.BytesIO(b"1"), 1.0)
    store.delete("alice", "a")
    assert store.list("alice") == []


@pytest.mark.parametrize("bad", ["", "../x", "a/../b", "/abs", "a//b", "a/", ".."])
def test_bad_relpath_rejected(store, bad):
    with pytest.raises(ValueError):
        store.put("alice", bad, io.BytesIO(b""), 1.0)
    with pytest.raises(ValueError):
        store.get("alice", bad, io.BytesIO())
    with pytest.raises(ValueError):
        store.delete("alice", bad)


@pytest.mark.parametrize("bad", ["", "a/b", "..", "."])
def test_bad_uid_rejected(store, bad):
    with pytest.raises(ValueError):
        store.list(bad)
