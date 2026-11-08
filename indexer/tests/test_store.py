from __future__ import annotations

import fnmatch
import hashlib
import json
from dataclasses import replace

import pytest

from pipeline.config import get_settings
from pipeline.models import Chunk
from pipeline.store import store


class Lock:
    name = "writer-lock"

    def __init__(self, busy=False):
        self.held = False
        self.busy = busy

    def acquire(self, blocking=False):
        self.held = not self.busy
        return self.held

    def extend(self, *args, **kwargs):
        assert self.held

    def owned(self):
        return self.held

    def release(self):
        self.held = False


class Redis:
    def __init__(self):
        self.values = {}
        self.writer = Lock()
        self.fail_publish = False

    def lock(self, *args, **kwargs):
        return self.writer

    def get(self, key):
        return self.values.get(key)

    def scan_iter(self, match):
        return iter([key for key in self.values if fnmatch.fnmatch(key, match)])

    def pipeline(self, transaction):
        return Transaction(self)

    def close(self):
        pass


class Transaction:
    def __init__(self, connection):
        self.connection = connection
        self.changes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def watch(self, key):
        assert key == "writer-lock"

    def multi(self):
        pass

    def set(self, key, value):
        self.changes.append(("set", key, value))

    def unlink(self, *keys):
        self.changes.extend(("delete", key, None) for key in keys)

    def execute(self):
        if self.connection.fail_publish:
            raise ConnectionError("publication failed")
        values = self.connection.values.copy()
        for operation, key, value in self.changes:
            if operation == "set":
                values[key] = value
            else:
                values.pop(key, None)
        self.connection.values = values


class Collection:
    def __init__(self, metadata, fail=False, wrong_count=False):
        self.metadata = metadata
        self.rows = {}
        self.fail = fail
        self.wrong_count = wrong_count

    def add(self, ids, documents, embeddings, metadatas):
        if self.fail:
            raise RuntimeError("upload failed")
        self.rows.update({id_: (text, vector, meta) for id_, text, vector, meta
                          in zip(ids, documents, embeddings, metadatas)})

    def count(self):
        return 0 if self.wrong_count else len(self.rows)


class Client:
    def __init__(self):
        self.collections = {"old-index": Collection({})}
        self.fail = False
        self.wrong_count = False

    def create_collection(self, name, metadata):
        collection = Collection(metadata, self.fail, self.wrong_count)
        self.collections[name] = collection
        return collection


@pytest.fixture
def storage(monkeypatch):
    connection, client = Redis(), Client()
    generation = "a" * 32
    connection.values = {
        "rahbar:index:rahbar:active": json.dumps({"collection": "old-index", "generation": generation}),
        f"rahbar:cache:rahbar:{generation}:answer": "old answer",
        "unrelated-key": "keep",
    }
    monkeypatch.setattr("pipeline.store.get_redis", lambda settings: connection)
    monkeypatch.setattr("pipeline.store.get_client", lambda settings: client)
    return connection, client


def rows():
    return [Chunk("id1", "Evidence", "rules.pdf", "Registration", 1, "2026", False)]


def test_publish_keeps_old_index_and_invalidates_only_its_cache(storage):
    connection, client = storage
    assert store(rows(), [[1, 2, 3]], replace(get_settings(), embed_dimension=3)) == 1
    catalog = json.loads(connection.values["rahbar:index:rahbar:active"])
    assert catalog["collection"] in client.collections and catalog["collection"] != "old-index"
    assert "old-index" in client.collections
    collection = client.collections[catalog["collection"]]
    assert collection.metadata["embed_model"] == get_settings().embed_model
    assert collection.metadata["dimension"] == 3
    assert collection.metadata["chunks_sha256"] == hashlib.sha256(
        rows()[0].export_line().encode("utf-8")
    ).hexdigest()
    assert set(collection.rows["id1"][2]) == {"source", "section", "page", "doc_version", "superseded"}
    assert connection.values["unrelated-key"] == "keep"
    assert not any(key.startswith("rahbar:cache:") for key in connection.values)


@pytest.mark.parametrize("failure", ["upload", "count", "publish", "busy"])
def test_failed_run_never_replaces_old_catalog(storage, failure):
    connection, client = storage
    previous = connection.values.copy()
    client.fail = failure == "upload"
    client.wrong_count = failure == "count"
    connection.fail_publish = failure == "publish"
    connection.writer.busy = failure == "busy"
    with pytest.raises((RuntimeError, ConnectionError)):
        store(rows(), [[1, 2, 3]], replace(get_settings(), embed_dimension=3))
    assert connection.values == previous
    assert "old-index" in client.collections


def test_empty_or_invalid_vectors_cannot_publish(storage):
    connection, client = storage
    with pytest.raises(ValueError, match="empty"):
        store([], [], get_settings())
    with pytest.raises(ValueError, match="dimension"):
        store(rows(), [[1, 2]], get_settings())
    assert list(client.collections) == ["old-index"]
