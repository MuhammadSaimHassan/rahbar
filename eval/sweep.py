#!/usr/bin/env python3
"""Measure chunk recall and labeled cache similarity using published Chroma indexes.

Run from the repository root with PYTHONPATH=api and the API dependency settings.
The sweep reads indexes and runs embeddings. It does not invoke chat or write Redis.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path
from statistics import mean

import yaml

from app.config import get_settings
from app.retrieval.chroma import ChromaRetriever, Evidence, edition
from app.services.cache import AnswerCache
from run_eval import GOLDEN, HERE, load_golden, load_projection, recall_at_k, write_json


class Experiment:
    def __init__(self, collection: str, projection: dict) -> None:
        self.settings = replace(get_settings(), collection=collection)
        self.retriever = ChromaRetriever(self.settings)
        self.projection = projection
        self.generation: str | None = None
        self.evidence: dict[str, Evidence] = {}

    def search(self, question: str) -> Evidence:
        if question not in self.evidence:
            evidence = self.retriever.search(question, 5, edition(question))
            if evidence.chunks_sha256 != self.projection["chunks_sha256"]:
                raise ValueError(f"chunk hash mismatch for {self.settings.collection}")
            if self.generation is not None and self.generation != evidence.generation:
                raise ValueError(f"index changed during sweep for {self.settings.collection}")
            self.generation = evidence.generation
            self.evidence[question] = evidence
        return self.evidence[question]

    def recall(self, questions: list[dict]) -> dict:
        rows = []
        for question in questions:
            evidence = self.search(question["question"])
            units = self.projection["questions"][question["id"]]
            ranked = [passage.model_dump() for passage in evidence.passages]
            relevant_ids = {chunk_id for unit in units for chunk_id in unit["chunk_ids"]}
            relevant_scores = [p.score for p in evidence.passages if p.chunk_id in relevant_ids]
            rows.append({
                "id": question["id"], "type": question["type"],
                "recall@3": recall_at_k(units, ranked, 3),
                "recall@5": recall_at_k(units, ranked, 5),
                "best_score": ranked[0]["score"] if ranked else None,
                "best_relevant_score": max(relevant_scores, default=None),
            })

        def averages(group: list[dict]) -> dict:
            result = {}
            for metric in ("recall@3", "recall@5"):
                values = [row[metric] for row in group if row[metric] is not None]
                result[metric] = mean(values) if values else None
            return result

        return {
            **averages(rows),
            "collection": self.settings.collection, "generation": self.generation,
            "chunks_sha256": self.projection["chunks_sha256"],
            "by_type": {kind: averages([row for row in rows if row["type"] == kind])
                        for kind in sorted({row["type"] for row in rows})},
            "per_question": rows,
        }

    def cache_scope(self, question: str) -> tuple[Evidence, AnswerCache, bool]:
        evidence = self.search(question)
        eligible = [p for p in evidence.passages if p.score >= self.settings.relevance_floor]
        cache = AnswerCache(self.retriever.redis, self.settings, evidence, eligible,
                            edition(question), question)
        return evidence, cache, bool(eligible)

    def cache_sweep(self, questions: list[dict], thresholds: list[float]) -> dict:
        by_id = {question["id"]: question["question"] for question in questions}
        labels = yaml.safe_load((HERE / "cache_tests.yaml").read_text(encoding="utf-8"))
        pairs = []
        for pair in labels["pairs"]:
            seed = by_id[pair["seed_question_id"]]
            candidate = pair.get("candidate") or by_id[pair["candidate_question_id"]]
            left, left_cache, left_eligible = self.cache_scope(seed)
            right, right_cache, right_eligible = self.cache_scope(candidate)
            pairs.append({
                "id": pair["id"], "expected_hit": pair["expected_hit"], "reason": pair["reason"],
                "cosine": sum(a * b for a, b in zip(left.vector, right.vector, strict=True)),
                "guard_match": (left_eligible and right_eligible
                                and left_cache.key == right_cache.key
                                and left_cache.anchors == right_cache.anchors),
            })
        results = []
        for threshold in sorted(set(thresholds)):
            raw_hits = [pair for pair in pairs if pair["cosine"] >= threshold]
            hits = [pair for pair in raw_hits if pair["guard_match"]]
            results.append({
                "threshold": threshold,
                "raw_false_hits": [pair["id"] for pair in raw_hits if not pair["expected_hit"]],
                "false_hits": [pair["id"] for pair in hits if not pair["expected_hit"]],
                "true_hits": [pair["id"] for pair in hits if pair["expected_hit"]],
            })
        return {
            "collection": self.settings.collection, "generation": self.generation,
            "assumes_seed_answer_passed_validation": True,
            "relevance_floor": self.settings.relevance_floor,
            "pairs": pairs, "thresholds": results,
            "lowest_zero_false_hit_threshold": next(
                (result["threshold"] for result in results if not result["false_hits"]), None,
            ),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", nargs=3, action="append", required=True,
                        metavar=("LABEL", "COLLECTION", "PROJECTION"))
    parser.add_argument("--cache-case", help="case label for the cache threshold sweep")
    parser.add_argument("--threshold", type=float, nargs="+", default=[0.85, 0.90, 0.95])
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    labels = [label for label, _, _ in args.case]
    if len(labels) != len(set(labels)) or (args.cache_case and args.cache_case not in labels):
        parser.error("case labels must be unique and --cache-case must name a case")
    if not all(0 <= threshold <= 1 for threshold in args.threshold):
        parser.error("cosine thresholds must be between zero and one")
    questions = load_golden(GOLDEN)
    cases = {}
    cache = None
    for label, collection, path in args.case:
        experiment = Experiment(collection, load_projection(Path(path), GOLDEN, questions))
        cases[label] = experiment.recall(questions)
        if label == args.cache_case:
            cache = experiment.cache_sweep(questions, args.threshold)
    write_json(args.out, {"chunk_cases": cases, "cache_sweep": cache})


if __name__ == "__main__":
    main()
