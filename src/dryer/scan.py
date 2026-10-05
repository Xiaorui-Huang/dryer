"""Read source files and pair the forms that clear the similarity threshold."""

from __future__ import annotations

import math
from collections import Counter
from pathlib import Path

from dryer.discover import language_of
from dryer.extract import entries_in_source
from dryer.model import Duplicate, Entry, Span
from dryer.shape import jaccard


def display_path(path: Path, root: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def _keep(entry: Entry, min_lines: int, min_nodes: int) -> bool:
    lines = entry.end_line - entry.start_line + 1
    return lines >= min_lines and entry.nodes >= min_nodes


def scan_files(
    files: list[Path], root: Path, min_lines: int, min_nodes: int
) -> tuple[list[Entry], list[str]]:
    entries: list[Entry] = []
    warnings: list[str] = []
    for path in files:
        language = language_of(path)
        if language is None:
            continue
        source = path.read_text(encoding="utf-8", errors="replace")
        file = display_path(path, root)
        found, warning = entries_in_source(language, source, path.as_posix(), file)
        if warning:
            warnings.append(f"{file}:{warning}")
        entries.extend(entry for entry in found if _keep(entry, min_lines, min_nodes))
    return entries, warnings


def _same_form(left: Entry, right: Entry) -> bool:
    if left.file != right.file:
        return False
    return left.offset == right.offset


def _duplicate_key(item: Duplicate):
    score = -item.score
    return (
        score,
        item.language,
        item.left.file,
        item.left.start_line,
        item.right.file,
        item.right.start_line,
    )


def _prefix_length(size: int, threshold: float) -> int:
    """How many of a set's rarest fingerprints a match must share at least one of.

    Jaccard >= t needs an overlap of at least t * size, so a match shares one of
    any size - floor(t * size) + 1 fingerprints. Rounding down keeps it safe.
    """

    return min(size, size - math.floor(threshold * size) + 1)


def _candidate_pairs(group: list[Entry], threshold: float) -> set[tuple[int, int]]:
    """Index pairs that can reach the threshold; every other pair cannot."""

    if threshold <= 0:
        return {(i, j) for i in range(len(group)) for j in range(i + 1, len(group))}
    frequency = Counter(token for entry in group for token in entry.fingerprints)
    index: dict[str, list[int]] = {}
    pairs: set[tuple[int, int]] = set()
    for position in sorted(range(len(group)), key=lambda i: len(group[i].fingerprints)):
        tokens = sorted(group[position].fingerprints, key=lambda token: (frequency[token], token))
        size = len(tokens)
        for token in tokens[: _prefix_length(size, threshold)]:
            for other in index.setdefault(token, []):
                if len(group[other].fingerprints) >= threshold * size:
                    pairs.add((min(position, other), max(position, other)))
            index[token].append(position)
    return pairs


def find_duplicates(entries: list[Entry], threshold: float) -> list[Duplicate]:
    """Pair forms of the same language. Each unordered pair is reported once."""

    by_language: dict[str, list[Entry]] = {}
    for entry in entries:
        by_language.setdefault(entry.language, []).append(entry)

    found: list[Duplicate] = []
    for language, group in by_language.items():
        for index, other in sorted(_candidate_pairs(group, threshold)):
            left, right = group[index], group[other]
            if _same_form(left, right):
                continue
            score = jaccard(left.fingerprints, right.fingerprints)
            if score < threshold:
                continue
            found.append(
                Duplicate(
                    score=score,
                    language=language,
                    left=Span(left.file, left.start_line, left.end_line),
                    right=Span(right.file, right.start_line, right.end_line),
                    left_nodes=left.nodes,
                    right_nodes=right.nodes,
                )
            )
    found.sort(key=_duplicate_key)
    return found
