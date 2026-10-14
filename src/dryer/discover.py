"""Find source files and decide which language each one is written in.

The extensions and the skipped directories match crapper and mutator, with
`.cljd` added because dry4clj reads it.

A `.cs` file in a C# test project, or in its project's `bin/` or `obj/`, is left
out by the rule crapper and skillflow's measure use too (bandoyer/skillflow#270
and #271). The file's project is the nearest folder at or above it that holds a
`.csproj`. It is a test project when its folder's name ends in `Tests` or has a
dot-separated part `Test` or `Tests`, or when a `.csproj` there marks itself a
test project. A file with no project isn't in one. Change the three together.
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
# Microsoft.Testing.Platform isn't one: a test runner references it as a library.
_CSHARP_TEST_PACKAGES = {
    "microsoft.net.test.sdk",
    "nunit",
    "xunit",
    "xunit.v3",
    "mstest",
    "mstest.testframework",
}
_CSHARP_BUILD_DIRS = {"bin", "obj"}


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


def _csharp_test_name(name: str) -> bool:
    """A name ending in Test isn't enough: Stryker.TestRunner.VsTest is production code."""

    return name.endswith("Tests") or not {"Test", "Tests"}.isdisjoint(name.split("."))


def _mstest_sdk(sdks: str) -> bool:
    """`MSTest.Sdk` among `;`-separated SDKs, with or without a `/version`."""

    return any(sdk.split("/")[0].strip().lower() == "mstest.sdk" for sdk in sdks.split(";"))


def _marks_a_test_project(project: Path) -> bool:
    """Read as XML by local names, as crapper reads it, so a comment marks nothing
    and quoting doesn't matter. A file that isn't XML marks nothing."""

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
        if tag == "Project" and _mstest_sdk(element.get("Sdk", "")):
            return True
        if tag == "Sdk" and _mstest_sdk(element.get("Name", "")):
            return True
    return False


@lru_cache(maxsize=None)
def _csharp_project(folder: Path) -> Path | None:
    for current in (folder, *folder.parents):
        if any(current.glob("*.csproj")):
            return current
    return None


@lru_cache(maxsize=None)
def _csharp_test_project(project: Path) -> bool:
    if _csharp_test_name(project.name):
        return True
    return any(_marks_a_test_project(csproj) for csproj in project.glob("*.csproj"))


def _csharp_left_out(file_path: Path) -> bool:
    folder = file_path.absolute().parent
    project = _csharp_project(folder)
    if project is None:
        return False
    if not _CSHARP_BUILD_DIRS.isdisjoint(folder.relative_to(project).parts):
        return True
    return _csharp_test_project(project)


def is_test_file(path: str | Path) -> bool:
    file_path = Path(path)
    name = file_path.name
    if _native_test(file_path):
        return True
    if file_path.suffix == ".cs" and _csharp_left_out(file_path):
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
