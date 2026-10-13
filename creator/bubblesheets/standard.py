"""The standard sheets: ready to print, no choices to make.

Three kinds of question, each filling one side of a full page, with a bubbled
name (13 letters), a 9-digit student ID and an ANSWER KEY bubble. Every sheet
carries a bubbled name so the grader's results come back with names on them;
that is why there are no half pages (a name grid is taller than a half page).
Each is an ordinary Spec, so a standard sheet and the same settings made by
hand are the same sheet to the grader.
"""

from __future__ import annotations

from dataclasses import dataclass

from .layout import Spec

NAME_LETTERS = 13  # the most that leaves room for two columns of A-E beside the name
ID_DIGITS = 9  # the institution's student ID length; the Creator offers this or none


@dataclass(frozen=True)
class Standard:
    id: str
    kind: str
    blurb: str
    spec: Spec


def _s(questions, choices, labels):
    return Spec.simple(questions, choices, labels, id_digits=ID_DIGITS, name_letters=NAME_LETTERS)


STANDARD = [
    Standard("ae", "A–E", "70 questions on one side.", _s(70, 5, "letters")),
    Standard("tf", "True/False", "105 questions on one side.", _s(105, 2, "truefalse")),
    Standard("aj", "A–J", "35 questions with ten choices, for matching and long option lists.", _s(35, 10, "letters")),
]

BY_ID = {s.id: s for s in STANDARD}
