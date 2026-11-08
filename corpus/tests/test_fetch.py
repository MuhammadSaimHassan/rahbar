"""Downloader integrity tests; no requests reach the university website."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest
import yaml

spec = importlib.util.spec_from_file_location("corpus_fetch", Path(__file__).parents[1] / "fetch.py")
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "RAW", tmp_path / "raw")
    monkeypatch.setattr(fetch, "SOURCES", tmp_path / "sources.yaml")
    monkeypatch.setattr(fetch, "MANIFEST", tmp_path / "MANIFEST.md")
    monkeypatch.setattr(fetch, "PAUSE_SECONDS", 0)
    doc = {"name": "Policy", "url": "https://example.test/policy.pdf", "superseded": False}
    fetch.SOURCES.write_text(yaml.safe_dump({"documents": [doc]}), encoding="utf-8")
    return doc


def mock_download(monkeypatch, content, content_type="application/pdf"):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=content, headers={"content-type": content_type})

    original = httpx.Client
    monkeypatch.setattr(fetch.httpx, "Client", lambda **kwargs: original(
        **kwargs, transport=httpx.MockTransport(handler),
    ))
    return calls


def test_cached_download_is_reused_and_verified(workspace, monkeypatch):
    calls = mock_download(monkeypatch, b"%PDF-1.4\nfixture")
    assert fetch.fetch(False) == 0
    assert fetch.fetch(False) == 0
    assert len(calls) == 1
    assert fetch.verify() == 0


def test_corrupt_cache_is_not_blessed_by_a_new_manifest(workspace, monkeypatch):
    mock_download(monkeypatch, b"%PDF-1.4\nfixture")
    assert fetch.fetch(False) == 0
    original = fetch.MANIFEST.read_text()
    (fetch.RAW / "policy.pdf").write_bytes(b"tampered")
    assert fetch.fetch(False) == 1
    assert fetch.MANIFEST.read_text() == original
    assert fetch.verify() == 1


def test_html_error_page_cannot_be_saved_as_pdf(workspace, monkeypatch):
    mock_download(monkeypatch, b"<html>Not found</html>", "text/html")
    assert fetch.fetch(False) == 1
    assert not (fetch.RAW / "policy.html").exists()
    assert json.loads((fetch.RAW / "_index.json").read_text()) == []
    assert fetch.verify() == 1


def test_source_hash_must_match_before_writing(workspace, monkeypatch):
    workspace["sha256"] = "0" * 64
    fetch.SOURCES.write_text(yaml.safe_dump({"documents": [workspace]}))
    mock_download(monkeypatch, b"%PDF-1.4\nfixture")
    assert fetch.fetch(False) == 1
    assert not (fetch.RAW / "policy.pdf").exists()


def test_duplicate_filenames_are_rejected(workspace):
    duplicate = {**workspace, "name": "Policy!"}
    fetch.SOURCES.write_text(yaml.safe_dump({"documents": [workspace, duplicate]}))
    with pytest.raises(SystemExit, match="duplicate filename slug"):
        fetch.load_sources()


def test_verify_rejects_incomplete_corpus(workspace, monkeypatch):
    mock_download(monkeypatch, b"%PDF-1.4\nfixture")
    assert fetch.fetch(False) == 0
    other = {**workspace, "name": "Other policy"}
    fetch.SOURCES.write_text(yaml.safe_dump({"documents": [workspace, other]}))
    assert fetch.verify() == 1


def test_changed_source_pin_cannot_reuse_cached_bytes(workspace, monkeypatch):
    mock_download(monkeypatch, b"%PDF-1.4\nfixture")
    assert fetch.fetch(False) == 0
    workspace["sha256"] = "0" * 64
    fetch.SOURCES.write_text(yaml.safe_dump({"documents": [workspace]}))
    assert fetch.fetch(False) == 1
    assert fetch.verify() == 1
