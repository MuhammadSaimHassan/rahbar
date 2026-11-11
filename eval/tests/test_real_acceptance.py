from __future__ import annotations

import copy
import json

import pytest

from scripts.check_real_acceptance import (
    SOURCE, validate_abstention, validate_grounded, writer_measurements,
)


def grounded():
    ref = {"source": SOURCE, "section": "5.4 Academic Warning", "page": 24}
    body = {"provider": "ollama", "answered_from_context": True,
            "answer": "The minimum CGPA is 2.00.", "citations": [ref],
            "retrieved": [copy.deepcopy(ref)]}
    headers = {"x-answer-outcome": "grounded", "x-index-generation": "generation-a",
               "x-index-chunks-sha256": "a" * 64}
    return body, headers


def test_real_grounded_answer_requires_provider_evidence_and_frozen_index():
    body, headers = grounded()
    validate_grounded(body, headers, "a" * 64)


@pytest.mark.parametrize("failure", ["stub", "fallback", "wrong_fact", "forged_page", "wrong_index"])
def test_bad_acceptance_result_is_rejected(failure):
    body, headers = grounded()
    if failure == "stub":
        body["provider"] = "stub"
    elif failure == "fallback":
        headers["x-answer-outcome"] = "fallback"
    elif failure == "wrong_fact":
        body["answer"] = "The minimum CGPA is 3.00."
    elif failure == "forged_page":
        body["citations"][0]["page"] = 999
    else:
        headers["x-index-chunks-sha256"] = "b" * 64
    with pytest.raises(ValueError):
        validate_grounded(body, headers, "a" * 64)


def test_fallback_must_not_count_as_correct_absent_topic_abstention():
    body = {"provider": "ollama", "answered_from_context": False, "citations": []}
    validate_abstention(body, {"x-answer-outcome": "abstained"})
    with pytest.raises(ValueError):
        validate_abstention(body, {"x-answer-outcome": "fallback"})


def test_writer_report_keeps_container_peak_separate_from_parent_rss(tmp_path):
    report = {"mode": "published", "chunk_count": 950, "documents": [{}] * 9,
              "embed_model": "nomic-embed-text", "dimension": 768,
              "process_peak_rss_bytes": 10}
    p = tmp_path / "indexer.log"
    p.write_text("RAHBAR_INDEXER_REPORT_START\n" + json.dumps(report)
                 + "\nRAHBAR_INDEXER_REPORT_END\nRAHBAR_INDEXER_CGROUP_PEAK_BYTES=20\n")
    result = writer_measurements(p)
    assert result["process_peak_rss_bytes"] == 10
    assert result["whole_container_peak_bytes"] == 20
    assert result["memory_limit_bytes"] == 1024 ** 3
