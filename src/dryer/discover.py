"""Find source files and decide which language each one is written in.

The extensions and the skipped directories match crapper and mutator, with
`.cljd` added because dry4clj reads it.

A C# test project is found by the rule skillflow's measure uses
(bandoyer/skillflow#270): a folder whose name ends in `Tests` or has a
dot-separated part `Test` or `Tests`, or a `.csproj` that marks itself a test
project. The nearest folder at or above a `.cs` file that holds a `.csproj`
decides the second.
"""

import os
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

EXTENSIONS = {
    ".c": "c",
    **dict.fromkeys(
        (".h", ".cc", ".cpp", ".cxx", ".c++", ".C", ".hpp", ".hh",
         ".hxx", ".h++", ".H", ".ipp", ".inl", ".tcc"), "cpp",
    ),
    ".clj": "clojure",
    ".cljc": "clojure",
    ".cljs": "clojure",
    ".cljd": "clojure",
    ".bb": "clojure",
    ".java": "java",
    ".go": "go",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".rs": "rust",
    ".py": "python",
    ".cs": "csharp",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".idea",
    ".venv",
    "venv",
    "node_modules",
    "vendor",
    "target",
    "dist",
    "build",
    "out",
    "coverage",
    ".metrics",
    "testdata",
    "__pycache__",
    ".clj-kondo",
}

TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__"}

# A PackageReference to one of these marks a C# test project. NuGet ids ignore case.
_CSHARP_TEST_PACKAGES = {
    "microsoft.net.test.sdk",
    "nunit",
    "xunit",
    "mstest",
    "microsoft.testing.platform",
}


def language_of(path: str | Path) -> str | None:
    file_path = Path(path)
    name = file_path.name
    if name.endswith(".d.ts"):
        return None
    return EXTENSIONS.get(file_path.suffix)


def _native_test(file_path: Path) -> bool:
    return language_of(file_path) in {"c", "cpp"} and (
        file_path.stem.startswith("test_") or file_path.stem.endswith(("_test", "_tests"))
    )


def _csharp_test_folder(name: str) -> bool:
    return name.endswith("Tests") or not {"Test", "Tests"}.isdisjoint(name.split("."))


def _marks_a_test_project(project: Path) -> bool:
    try:
        root = ElementTree.parse(project).getroot()
    except (OSError, ElementTree.ParseError):
        return False
    for element in root.iter():
        tag = element.tag.rpartition("}")[2]
        if tag == "IsTestProject" and (element.text or "").strip().lower() == "true":
            return True
        package = element.get("Include", "").strip().lower()
        if tag == "PackageReference" and package in _CSHARP_TEST_PACKAGES:
            return True
    return False


@lru_cache(maxsize=None)
def _in_marked_test_project(folder: Path) -> bool:
    for current in (folder, *folder.parents):
        projects = sorted(current.glob("*.csproj"))
        if projects:
            return any(_marks_a_test_project(project) for project in projects)
    return False


def _csharp_test_file(file_path: Path) -> bool:
    if any(_csharp_test_folder(name) for name in file_path.parent.parts):
        return True
    return _in_marked_test_project(file_path.resolve().parent)


def is_test_file(path: str | Path) -> bool:
    file_path = Path(path)
    name = file_path.name
    if _native_test(file_path):
        return True
    if file_path.suffix == ".cs" and _csharp_test_file(file_path):
        return True
    if name.endswith("_test.go"):
        return True
    if name.endswith(("_test.clj", "_test.cljc", "_test.cljs", "_test.cljd", "_test.bb")):
        return True
    if name.endswith(
        (
            ".test.ts",
            ".spec.ts",
            ".test.tsx",
            ".spec.tsx",
            ".test.mts",
            ".spec.mts",
            ".test.cts",
            ".spec.cts",
        )
    ):
        return True
    if name == "conftest.py":
        return True
    if name.endswith("_test.py") or (name.startswith("test_") and name.endswith(".py")):
        return True
    return any(part in TEST_DIRS for part in file_path.parts)


def _skipped_dir(name: str) -> bool:
    return name in SKIP_DIRS or name in TEST_DIRS


def _walk(root: Path) -> list[Path]:
    if not root.exists():
        return []
    if root.is_file():
        return [root]
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not _skipped_dir(name)]
        for name in filenames:
            path = Path(dirpath) / name
            if language_of(path) is None or is_test_file(path):
                continue
            found.append(path)
    return found


def iter_source_files(roots: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        for path in _walk(root):
            files.add(path.resolve())
    return sorted(files, key=lambda path: path.as_posix())
