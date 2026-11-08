"""Validate source-authored benchmark files and project evidence onto unranked chunks.

    python eval/prepare_golden.py --chunks corpus/raw/pipeline/chunks.jsonl
    python eval/prepare_golden.py --chunks corpus/raw/pipeline/chunks.jsonl --freeze
    python eval/prepare_golden.py --check-lock

No embedding, retrieval, generation or tuning is performed. The primary question and
source oracle stay unchanged when a new chunk configuration is projected.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
GOLDEN = ROOT / "eval/golden.yaml"
CACHE = ROOT / "eval/cache_tests.yaml"
LOCK = ROOT / "eval/golden.lock.json"
PROJECTION = ROOT / "eval/relevance.current.json"
MANIFEST = ROOT / "corpus/MANIFEST.md"
MINIMUM = {"ordinary": 8, "version": 2, "exact": 2, "abstain": 2, "injection": 1}


def digest(path: Path) -> str:
    # Git may convert text line endings on Windows; the oracle must survive a clean clone.
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_yaml(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise ValueError(f"invalid benchmark schema: {path.name}")
    return data


def source_metadata() -> dict:
    result = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip() for cell in line.split("|")[1:-1]]
        if len(cells) == 7 and re.fullmatch(r"`[0-9a-f]{64}`", cells[5]):
            result[cells[3].strip("`")] = {
                "version": cells[1], "superseded": cells[2] == "yes",
            }
    audit = json.loads((ROOT / "docs/evidence/corpus-audit.json").read_text())
    for source in audit["sources"]:
        if source["file"] in result:
            result[source["file"]]["pages"] = source["pages"] or 1
    return result


def validate() -> tuple[list[dict], dict]:
    questions = read_yaml(GOLDEN).get("questions", [])
    if not isinstance(questions, list) or len(questions) < 15:
        raise ValueError("at least 15 golden questions are required")
    sources = source_metadata()
    ids, texts = set(), set()
    version_pairs: dict[str, set[str]] = defaultdict(set)
    counts: Counter = Counter()
    for question in questions:
        id_, kind = question.get("id"), question.get("type")
        text = question.get("question", "")
        if not isinstance(id_, str) or id_ in ids or kind not in MINIMUM:
            raise ValueError(f"invalid/duplicate question id or type: {id_}")
        if not isinstance(text, str) or not 3 <= len(text) <= 500 or text.casefold() in texts:
            raise ValueError(f"invalid/duplicate question text: {id_}")
        ids.add(id_)
        texts.add(text.casefold())
        counts[kind] += 1
        relevant = question.get("relevant")
        abstain = question.get("must_abstain", False)
        if not isinstance(relevant, list) or not isinstance(abstain, bool):
            raise ValueError(f"invalid relevance/abstention schema: {id_}")
        if (kind == "abstain") != abstain or bool(relevant) == abstain:
            raise ValueError(f"abstention and relevance disagree: {id_}")
        facts = question.get("answer_facts")
        if not isinstance(facts, list) or not facts or any(not isinstance(fact, str) or not fact.strip() for fact in facts):
            raise ValueError(f"missing source-authored answer facts: {id_}")
        for unit in relevant:
            metadata = sources.get(unit.get("source"))
            if not metadata or unit.get("doc_version") != metadata["version"]:
                raise ValueError(f"unknown source/version: {id_}")
            pages = unit.get("pages")
            if not isinstance(pages, list) or not pages or any(type(page) is not int or not 1 <= page <= metadata["pages"] for page in pages):
                raise ValueError(f"invalid source page: {id_}")
            if not isinstance(unit.get("section"), str) or not unit["section"].strip():
                raise ValueError(f"missing source section: {id_}")
            anchors = unit.get("anchors")
            if not isinstance(anchors, list) or not anchors or any(not isinstance(anchor, str) or not anchor.strip() for anchor in anchors):
                raise ValueError(f"missing source anchors: {id_}")
            if metadata["superseded"] and not (kind == "version" and question.get("allow_superseded") is True):
                raise ValueError(f"superseded source without explicit version intent: {id_}")
            if kind == "version" and question.get("target_doc_version") != unit["doc_version"]:
                raise ValueError(f"version intent differs from source: {id_}")
        if kind == "version":
            if not question.get("version_pair"):
                raise ValueError(f"missing version-pair label: {id_}")
            version_pairs[question["version_pair"]].add(question["target_doc_version"])
    for kind, minimum in MINIMUM.items():
        if counts[kind] < minimum:
            raise ValueError(f"need {minimum} {kind} questions; found {counts[kind]}")
    if any(len(versions) < 2 for versions in version_pairs.values()):
        raise ValueError("every version pair must cover at least two editions")
    cache = read_yaml(CACHE)
    cache_ids = set()
    pair_counts: Counter = Counter()
    for pair in cache.get("pairs", []):
        if not isinstance(pair.get("id"), str) or pair["id"] in cache_ids or pair.get("seed_question_id") not in ids:
            raise ValueError("duplicate cache pair or unknown seed question")
        cache_ids.add(pair.get("id"))
        if type(pair.get("expected_hit")) is not bool:
            raise ValueError("cache pairs need explicit expected_hit booleans")
        if bool(pair.get("candidate")) == bool(pair.get("candidate_question_id")):
            raise ValueError("provide exactly one candidate text or question id")
        if pair.get("candidate_question_id") and pair["candidate_question_id"] not in ids:
            raise ValueError("unknown cache candidate question")
        if pair.get("candidate") and (not isinstance(pair["candidate"], str) or not 3 <= len(pair["candidate"]) <= 500):
            raise ValueError("cache candidate must satisfy the API question-length contract")
        reference = pair.get("candidate_reference")
        if reference:
            metadata = sources.get(reference.get("source"))
            if not metadata or not reference.get("section") or any(
                type(page) is not int or not 1 <= page <= metadata["pages"] for page in reference.get("pages", [])
            ):
                raise ValueError("invalid cache candidate source reference")
        pair_counts["hit" if pair["expected_hit"] else "miss"] += 1
    if min(pair_counts["hit"], pair_counts["miss"]) < 3:
        raise ValueError("cache set needs at least three paraphrases and three near misses")
    for case in cache.get("policy_cases", []):
        if case.get("expected_cacheable") is not False:
            raise ValueError("policy cases must explicitly refuse caching")
        references = case.get("history_question_ids", []) + ([case["question_id"]] if "question_id" in case else [])
        if any(reference not in ids for reference in references):
            raise ValueError("unknown question in cache policy case")
    return questions, {"question_types": dict(counts), "cache_pairs": dict(pair_counts),
                       "cache_policy_cases": len(cache.get("policy_cases", []))}


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).casefold()
    text = re.sub(r"(?<=\d)\s*\.\s*(?=\d)", ".", text)
    text = re.sub(r"(?<=\d),(?=\d)", "", text)
    text = re.sub(r"[^\w.%+-]+", " ", text)
    return " ".join(text.split())


def contains(text: str, anchor: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(normalise(anchor)) + r"(?!\w)", text) is not None


def project(questions: list[dict], path: Path) -> dict:
    chunks = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    result = {"schema_version": 1, "hash_mode": "utf8-lf", "golden_sha256": digest(GOLDEN),
              "chunks_sha256": digest(path), "method": "source-page-and-anchor; no ranked retrieval",
              "questions": {}, "unmapped": []}
    for question in questions:
        units = []
        for number, unit in enumerate(question["relevant"]):
            ids = [chunk["id"] for chunk in chunks
                   if chunk["source"] == unit["source"] and chunk["page"] in unit["pages"]
                   and chunk["doc_version"] == unit["doc_version"]
                   and all(contains(normalise(chunk["text"]), anchor) for anchor in unit["anchors"])]
            units.append({"source": unit["source"], "section": unit["section"],
                          "pages": unit["pages"], "chunk_ids": sorted(ids)})
            if not ids:
                result["unmapped"].append(f"{question['id']}:{number}")
        result["questions"][question["id"]] = units
    return result


def check_lock() -> None:
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    for name, path in {"golden": GOLDEN, "cache_tests": CACHE, "manifest": MANIFEST,
                       "projection": PROJECTION}.items():
        if digest(path) != lock["sha256"][name]:
            raise ValueError(f"{name} changed since the benchmark snapshot was frozen")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chunks", type=Path, help="project source annotations onto these unranked chunks")
    parser.add_argument("--projection-out", type=Path, default=PROJECTION,
                        help="write alternate chunk-configuration projections to a separate file")
    parser.add_argument("--freeze", action="store_true", help="record this reviewed pre-tuning snapshot")
    parser.add_argument("--check-lock", action="store_true", help="verify the frozen benchmark hashes")
    args = parser.parse_args()
    try:
        questions, summary = validate()
        print(json.dumps(summary, indent=2))
        if args.freeze and (not args.chunks or args.projection_out.resolve() != PROJECTION.resolve()):
            raise ValueError("--freeze requires --chunks and the default baseline projection output")
        if args.chunks:
            projection = project(questions, args.chunks)
            args.projection_out.parent.mkdir(parents=True, exist_ok=True)
            args.projection_out.write_text(json.dumps(projection, indent=2) + "\n", encoding="utf-8")
            if projection["unmapped"]:
                raise ValueError("source support not mapped; keep the questions and review: "
                                 + ", ".join(projection["unmapped"]))
            print(f"Projected {sum(bool(q['relevant']) for q in questions)} answerable questions.")
        if args.freeze:
            lock = {
                "schema_version": 1, "hash_mode": "utf8-lf",
                "frozen_on_pkt": datetime.now(timezone(timedelta(hours=5))).date().isoformat(),
                "method": "source-authored before tuning; projection uses no ranked retrieval",
                "team_review": "pending", "git_commit": "pending",
                "sha256": {"golden": digest(GOLDEN), "cache_tests": digest(CACHE),
                           "manifest": digest(MANIFEST), "projection": digest(PROJECTION)},
                "chunks_sha256": digest(args.chunks), **summary,
            }
            LOCK.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
            print("Recorded the local benchmark snapshot; no Git commit was made.")
        if args.check_lock:
            check_lock()
            print("Frozen benchmark hashes match.")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Benchmark validation failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
