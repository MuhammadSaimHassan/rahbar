#!/usr/bin/env python3
"""Score a running RAHBAR and gate CI on its retrieval and grounding metrics."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from statistics import mean

import httpx
import yaml

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden.yaml"
MAX_RECALL5_DROP = 0.05
MIN_CITATION_VALIDITY = 0.95
REQUIRED_ABSTENTION = 1.0


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_text(encoding="utf-8").encode("utf-8")).hexdigest()


def load_golden(path: Path) -> list[dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    questions = data.get("questions") or []
    if not questions or len({q["id"] for q in questions}) != len(questions):
        raise ValueError(f"empty golden set or duplicate question IDs in {path}")
    return questions


def load_projection(path: Path, golden: Path, questions: list[dict]) -> dict:
    projection = json.loads(path.read_text(encoding="utf-8"))
    if projection["schema_version"] != 1 or projection["golden_sha256"] != digest(golden):
        raise ValueError("projection does not match the golden set")
    units = projection["questions"]
    if projection["unmapped"] or set(units) != {q["id"] for q in questions}:
        raise ValueError("projection has missing or unmapped questions")
    for question in questions:
        actual = units[question["id"]]
        expected = question.get("relevant") or []
        if len(actual) != len(expected):
            raise ValueError(f"incomplete projection for {question['id']}")
        for unit, source in zip(actual, expected, strict=True):
            if not unit["chunk_ids"] or any(unit[key] != source[key] for key in ("source", "section", "pages")):
                raise ValueError(f"invalid evidence projection for {question['id']}")
    return projection


def recall_at_k(relevant: list[dict], retrieved: list[dict], k: int) -> float | None:
    """Score each evidence unit once, even when it spans alternative chunks."""
    if not relevant:
        return None
    hits = retrieved[:k]
    ids = {hit.get("chunk_id") for hit in hits}
    pairs = {(hit["source"], hit["section"]) for hit in hits}
    return sum(
        bool(ids.intersection(unit["chunk_ids"])) if "chunk_ids" in unit
        else (unit["source"], unit["section"]) in pairs
        for unit in relevant
    ) / len(relevant)


def citation_key(item: dict) -> tuple:
    return item["source"], item["section"], item.get("page")


def citation_counts(response: dict) -> tuple[int, int]:
    retrieved = {citation_key(passage) for passage in response["retrieved"]}
    citations = response["citations"]
    return sum(citation_key(citation) in retrieved for citation in citations), len(citations)


def citation_validity(response: dict) -> float | None:
    valid, total = citation_counts(response)
    return valid / total if total else None


def average(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return mean(present) if present else None


def summarise(rows: list[dict]) -> dict:
    scored = []
    for row in rows:
        response = row["response"]
        valid, total = citation_counts(response)
        declined = (
            response["answered_from_context"] is False
            and not response["citations"]
            and row.get("outcome") != "fallback"
        )
        scored.append({
            "id": row["id"], "type": row["type"],
            "recall@3": recall_at_k(row["relevant"], response["retrieved"], 3),
            "recall@5": recall_at_k(row["relevant"], response["retrieved"], 5),
            "citation_validity": valid / total if total else None,
            "valid_citations": valid, "citations": total,
            "abstention_correct": declined if row["must_abstain"] else None,
            "outcome": row.get("outcome"),
            "seconds": row.get("seconds"),
            "question": row.get("question"),
            "answer_facts": row.get("answer_facts", []),
            "response": response,
        })
    groups = {}
    for kind in sorted({row["type"] for row in scored}):
        subset = [row for row in scored if row["type"] == kind]
        groups[kind] = {
            "questions": len(subset),
            **{metric: average([row[metric] for row in subset]) for metric in ("recall@3", "recall@5")},
        }
    valid = sum(row["valid_citations"] for row in scored)
    total = sum(row["citations"] for row in scored)
    abstentions = [row["abstention_correct"] for row in scored if row["abstention_correct"] is not None]
    return {
        **{metric: average([row[metric] for row in scored]) for metric in ("recall@3", "recall@5")},
        "citation_validity": valid / total if total else None,
        "citations": total,
        "abstention_correctness": mean(abstentions) if abstentions else None,
        "by_type": groups,
        "per_question": scored,
    }


def gate(results: dict, baseline: dict | None) -> list[str]:
    failures = []
    current = results["recall@5"]
    if current is None:
        failures.append("recall@5 has no answerable questions")
    if baseline is not None:
        previous = baseline.get("recall@5")
        if baseline.get("golden_sha256") != results.get("golden_sha256"):
            failures.append("baseline uses a different golden set")
        elif (not isinstance(previous, (int, float)) or isinstance(previous, bool)
              or not 0 <= previous <= 1):
            failures.append("baseline has invalid recall@5")
        elif current is not None:
            limit = previous - MAX_RECALL5_DROP
            if current < limit and not math.isclose(current, limit, abs_tol=1e-12):
                failures.append(f"recall@5 fell from {previous:.1%} to {current:.1%}")
    validity = results["citation_validity"]
    if validity is None or validity < MIN_CITATION_VALIDITY:
        failures.append("citation validity must be at least 95% and have citations to score")
    if results["abstention_correctness"] != REQUIRED_ABSTENTION:
        failures.append("every must-abstain question must be declined without a fallback")
    return failures


def evaluate(args: argparse.Namespace) -> dict:
    golden = args.golden.resolve()
    questions = load_golden(golden)
    projection_path = args.projection
    if projection_path is None and golden == GOLDEN:
        projection_path = HERE / "relevance.current.json"
    projection = load_projection(projection_path, golden, questions) if projection_path else None
    if projection is None and any("anchors" in unit for q in questions for unit in q.get("relevant", [])):
        raise ValueError("source-annotated evidence requires a chunk projection")
    headers = {"Host": args.host} if args.host else {}
    rows = []
    generation = None
    checkpoint = args.checkpoint
    golden_hash = digest(golden)
    chunk_hash = projection["chunks_sha256"] if projection else None
    if checkpoint is not None and not projection:
        raise ValueError("checkpoints require a projected index with generation provenance")
    if checkpoint is not None and checkpoint.exists():
        state = json.loads(checkpoint.read_text(encoding="utf-8"))
        if state["golden_sha256"] != golden_hash or state["chunks_sha256"] != chunk_hash:
            raise ValueError("checkpoint does not match the evaluation inputs")
        rows, generation = state["rows"], state["generation"]
        if ([row["id"] for row in rows] != [q["id"] for q in questions[:len(rows)]]
                or not generation or len(rows) >= len(questions)):
            raise ValueError("checkpoint must contain a partial, ordered run")
        print(f"Resuming after {len(rows)} validated questions.")
    with httpx.Client(timeout=args.timeout, headers=headers) as client:
        for question in questions[len(rows):]:
            started = time.perf_counter()
            url = f"{args.api.rstrip('/')}/api/ask"
            payload = {"question": question["question"]}
            reply = client.post(url, json=payload)
            reply.raise_for_status()
            if (projection and not reply.headers.get("X-Index-Generation")
                    and reply.headers.get("X-Answer-Outcome") == "fallback"):
                time.sleep(1)
                reply = client.post(url, json=payload)
                reply.raise_for_status()
            response = reply.json()
            if projection:
                if response.get("provider") == "stub":
                    raise ValueError("real-corpus evaluation requires a live generation provider")
                if reply.headers.get("X-Index-Chunks-SHA256") != projection["chunks_sha256"]:
                    raise ValueError("live index chunk hash does not match the projection")
                current = reply.headers.get("X-Index-Generation")
                if not current or (generation is not None and current != generation):
                    raise ValueError("missing or changing index generation during evaluation")
                generation = current
            rows.append({
                "id": question["id"], "type": question.get("type", "ordinary"),
                "must_abstain": bool(question.get("must_abstain", False)),
                "relevant": (projection["questions"][question["id"]] if projection
                             else question.get("relevant") or []),
                "question": question["question"],
                "answer_facts": question.get("answer_facts", []),
                "outcome": reply.headers.get("X-Answer-Outcome"),
                "response": response,
                "seconds": round(time.perf_counter() - started, 2),
            })
            if checkpoint is not None and len(rows) < len(questions):
                pending = checkpoint.with_suffix(checkpoint.suffix + ".tmp")
                write_json(pending, {
                    "golden_sha256": golden_hash, "chunks_sha256": chunk_hash,
                    "generation": generation, "rows": rows,
                })
                pending.replace(checkpoint)
            print(f"  {question['id']:<5} {rows[-1]['seconds']:>6.2f}s  {question['question'][:60]}")
    return {
        **summarise(rows), "golden": golden.name, "golden_sha256": golden_hash,
        "questions": len(rows), "chunks_sha256": chunk_hash,
        "index_generation": generation,
    }


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", required=True, help="base URL, e.g. http://192.168.49.2")
    parser.add_argument("--host", help="Host header for a named Ingress")
    parser.add_argument("--golden", type=Path, default=GOLDEN)
    parser.add_argument("--projection", type=Path, help="chunk projection for a real-corpus index")
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--checkpoint", type=Path, help="save or resume a partial projected run")
    parser.add_argument("--timeout", type=float, default=300.0, help="seconds per API request")
    parser.add_argument("--update-baseline", action="store_true",
                        help="write a baseline only after the gates pass")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be a positive finite number")
    if args.baseline and not args.baseline.is_file() and not args.update_baseline:
        parser.error(f"baseline does not exist: {args.baseline}")
    if args.golden.resolve() == GOLDEN:
        args.baseline = args.baseline or HERE / "baseline.json"
        args.out = args.out or HERE / "results.json"
    else:
        args.out = args.out or HERE / "fixture-results.json"
    if args.update_baseline and args.baseline is None:
        parser.error("--update-baseline requires --baseline for an alternate golden set")
    if args.checkpoint and args.checkpoint.resolve() in {
        args.out.resolve(), args.baseline.resolve() if args.baseline else None,
    }:
        parser.error("--checkpoint must be separate from the result and baseline")
    if args.baseline and args.baseline.resolve() == args.out.resolve():
        parser.error("--baseline and --out must be separate files")
    try:
        results = evaluate(args)
        baseline = (json.loads(args.baseline.read_text(encoding="utf-8"))
                    if args.baseline and args.baseline.exists() else None)
        failures = gate(results, baseline)
        results["gate_failures"] = failures
        write_json(args.out, results)
        if args.checkpoint:
            args.checkpoint.unlink(missing_ok=True)
        print(f"\nresults written to {args.out}")
        if failures:
            print("\nGATE FAILED\n" + "\n".join(f"  - {failure}" for failure in failures))
            return 1
        if args.update_baseline:
            write_json(args.baseline, results)
            print(f"baseline updated: {args.baseline}")
    except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    print("gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
