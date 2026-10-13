"""Scoring student sheets against a key.

Rules, chosen to match what a Scantron reader does and to leave doubt visible:
- The key's highest answered question sets the test length. Questions the key
  leaves blank inside that range are not scored.
- A student answer flagged "multiple" earns no credit, as on a machine.
- A "light" answer counts as read but is listed for a person to check.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime

from .reader import CHOICES, Sheet


@dataclass
class Result:
    sheet: Sheet
    responses: dict[int, str]  # question -> "A".."E", "" blank, "*" multiple
    correct: set[int]
    flags: dict[int, str]  # question -> "multiple" | "light"
    score: int
    possible: int

    @property
    def percent(self) -> float:
        return 100 * self.score / self.possible if self.possible else 0.0

    @property
    def label(self) -> str:
        return self.sheet.name or f"Sheet {self.sheet.number} (no name)"


@dataclass
class Item:
    question: int
    key: str
    counts: dict[str, int]  # "A".."E", "" blank, "*" multiple
    correct: int
    upper_correct: int = 0  # among the top third by score
    lower_correct: int = 0  # among the bottom third
    group: int = 0  # size of each third; 0 when fewer than three students
    students: int = 0

    @property
    def percent(self) -> float:
        return 100 * self.correct / self.students if self.students else 0.0

    @property
    def discrimination(self) -> float | None:
        """Top-third minus bottom-third proportion correct, -1..1."""
        if not self.group:
            return None
        return (self.upper_correct - self.lower_correct) / self.group

    @property
    def note(self) -> str:
        d = self.discrimination
        if d is not None and d < 0:
            return "Check the key: stronger students missed it more"
        if self.students and self.percent < 30:
            return "Very hard"
        if d is not None and d < 0.1 and self.percent < 90:
            return "Does not separate stronger from weaker"
        return ""


@dataclass
class Grading:
    key: Sheet
    key_answers: dict[int, str]
    key_warnings: list[str]
    results: list[Result]
    items: list[Item]
    skipped: list[str] = field(default_factory=list)
    title: str = ""
    course: str = ""
    sources: list[str] = field(default_factory=list)
    graded_at: datetime = field(default_factory=datetime.now)

    @property
    def heading(self) -> str:
        return self.title or "Test results"

    @property
    def by_name(self) -> list[Result]:
        """Named students alphabetically, then unnamed sheets in upload order."""
        return sorted(self.results, key=lambda r: (not r.sheet.name, r.sheet.name.lower(), r.sheet.number))

    def distribution(self) -> list[tuple[str, int]]:
        """Students per ten-point band, lowest band first; 100% joins 90-100."""
        bands = [0] * 10
        for r in self.results:
            bands[min(9, int(r.percent // 10))] += 1
        labels = [f"{10 * i}-{10 * i + 9}" for i in range(9)] + ["90-100"]
        return list(zip(labels, bands))

    @property
    def questions(self) -> list[int]:
        return sorted(self.key_answers)

    def stats(self) -> dict[str, float]:
        if not self.results:
            return {}
        pct = [r.percent for r in self.results]
        return {
            "count": len(pct),
            "mean": statistics.mean(pct),
            "median": statistics.median(pct),
            "high": max(pct),
            "low": min(pct),
            "stdev": statistics.pstdev(pct),
        }


def key_from(sheet: Sheet) -> tuple[dict[int, str], list[str]]:
    answers = sheet.answers
    warnings = []
    key = {}
    for q, a in answers.items():
        if a.flag == "multiple":
            warnings.append(
                f"Key question {q} has more than one bubble filled; "
                f"using the darkest, {a.choice}."
            )
        if a.choice:
            key[q] = a.choice
    if key:
        last = max(key)
        gaps = [q for q in range(1, last + 1) if q not in key]
        if gaps:
            shown = ", ".join(map(str, gaps[:15])) + ("..." if len(gaps) > 15 else "")
            warnings.append(f"Key leaves question(s) {shown} blank; they are not scored.")
    return key, warnings


def grade(key: Sheet, students: list[Sheet], skipped: list[str]) -> Grading:
    key_answers, warnings = key_from(key)
    qs = sorted(key_answers)
    results = []
    for s in students:
        ans = s.answers
        responses, flags, correct = {}, {}, set()
        for q in qs:
            a = ans.get(q)
            if a is None:  # that side was not scanned
                responses[q] = ""
                continue
            if a.flag:
                flags[q] = a.flag
            responses[q] = "*" if a.flag == "multiple" else a.choice
            if responses[q] == key_answers[q]:
                correct.add(q)
        if s.side1 is None and any(q <= 120 for q in qs):
            skipped.append(f"{s.name or f'Sheet {s.number}'}: side 1 was not in the upload.")
        if s.side2 is None and any(q > 120 for q in qs):
            skipped.append(
                f"{s.name or f'Sheet {s.number}'}: side 2 was not in the upload; "
                "questions 121+ scored as blank."
            )
        results.append(Result(s, responses, correct, flags, len(correct), len(qs)))

    ranked = sorted(results, key=lambda r: r.score, reverse=True)
    third = max(1, len(ranked) // 3) if len(ranked) >= 3 else 0
    upper, lower = ranked[:third], ranked[-third:] if third else []
    items = []
    for q in qs:
        counts = {c: 0 for c in list(CHOICES) + ["", "*"]}
        for r in results:
            counts[r.responses[q]] += 1
        items.append(
            Item(
                q,
                key_answers[q],
                counts,
                sum(1 for r in results if q in r.correct),
                sum(1 for r in upper if q in r.correct),
                sum(1 for r in lower if q in r.correct),
                third,
                len(results),
            )
        )
    return Grading(key, key_answers, warnings, results, items, skipped)
