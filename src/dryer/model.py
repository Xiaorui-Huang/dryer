from dataclasses import dataclass


@dataclass(frozen=True)
class Span:
    """Where one candidate form sits in a source file."""

    file: str
    start_line: int
    end_line: int


@dataclass(frozen=True)
class Duplicate:
    """One pair of forms whose normalized structure is similar enough to report."""

    score: float
    language: str
    left: Span
    right: Span
    left_nodes: int
    right_nodes: int


@dataclass(frozen=True)
class Entry:
    """A normalized form ready to compare. Forms are only compared within one language.

    `offset` is where the form starts in its file. It tells apart forms that share
    lines; the line range is only for the report.
    """

    language: str
    file: str
    start_line: int
    end_line: int
    offset: int
    nodes: int
    fingerprints: frozenset[str]
