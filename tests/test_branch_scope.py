import subprocess

from dryer.cli import parse_args, run, select_files


def git(root, *args):
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True, capture_output=True,
    )


def write(root, name, text):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path.resolve()


def init(root):
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")


def test_changed_since_uses_merge_base_and_working_edits(tmp_path):
    init(tmp_path)
    for name in ("base", "edited", "deleted"):
        write(tmp_path, f"src/{name}.py", "def value():\n    return 0\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    git(tmp_path, "switch", "-c", "feature")
    committed = write(tmp_path, "src/committed.py", "def value():\n    return 1\n")
    git(tmp_path, "rm", "src/deleted.py")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "feature")
    git(tmp_path, "switch", "main")
    write(tmp_path, "src/upstream.py", "def value():\n    return 2\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "upstream")
    git(tmp_path, "switch", "feature")
    edited = write(tmp_path, "src/edited.py", "def value():\n    return 3\n")
    staged = write(tmp_path, "src/staged.py", "def value():\n    return 4\n")
    git(tmp_path, "add", "src/staged.py")
    untracked = write(tmp_path, "src/space é.py", "def value():\n    return 5\n")
    write(tmp_path, "tests/test_value.py", "def test_value():\n    assert True\n")
    write(tmp_path, "notes.md", "notes")
    options = parse_args(["--root", str(tmp_path), "--changed-since", "main"])
    assert set(select_files(options)) == {committed, edited, staged, untracked}
    options.project_root = tmp_path / "src"
    assert set(select_files(options)) == {committed, edited, staged, untracked}


def test_changed_since_validation_and_git_errors(tmp_path, capsys):
    assert parse_args(["--changed-since"]).exit_code == 1
    assert parse_args(["--changed", "--changed-since", "main"]).exit_code == 1
    init(tmp_path)
    write(tmp_path, "value.py", "def value():\n    return 0\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    assert run(["--root", str(tmp_path), "--changed-since", "missing"]) != 0
    assert capsys.readouterr().err.strip()
    assert not (tmp_path / ".metrics").exists()


def test_against_repo_reports_only_pairs_touching_selected_files(tmp_path, capsys):
    body = "def value(x):\n    y = abs(x)\n    z = abs(y)\n    return abs(z)\n"
    for name in ("selected.py", "old_a.py", "old_b.py"):
        write(tmp_path, name, body)
    args = ["--root", str(tmp_path), "--min-nodes", "1", "selected.py"]
    assert run(args) == 0
    assert "DUPLICATE" not in capsys.readouterr().out
    assert run([*args, "--against-repo"]) == 0
    output = capsys.readouterr().out
    assert output.count("DUPLICATE") == 2
    assert output.count("selected.py:") == 2
    assert "old_a.py:" in output and "old_b.py:" in output
    assert run([*args, "--against-repo", "--edn"]) == 0
    assert capsys.readouterr().out.count(':score ') == 2


def test_against_repo_with_no_changed_files_writes_empty_report(tmp_path, capsys):
    init(tmp_path)
    body = "def value(x):\n    y = abs(x)\n    z = abs(y)\n    return abs(z)\n"
    for name in ("a.py", "b.py"):
        write(tmp_path, name, body)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    assert run(["--root", str(tmp_path), "--changed-since", "main", "--against-repo"]) == 0
    assert "DUPLICATE" not in capsys.readouterr().out
    assert (tmp_path / ".metrics" / "dry.edn").read_text() == "{:candidates []}\n"


def test_changed_against_repo_and_path_filter(tmp_path, capsys):
    init(tmp_path)
    body = "int value(int x) {\n    int y = abs(x);\n    int z = abs(y);\n    return abs(z);\n}\n"
    write(tmp_path, "old.cpp", body)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    write(tmp_path, "new.cpp", body)
    args = ["--root", str(tmp_path), "--changed", "--min-nodes", "1"]
    assert run(args) == 0
    assert "DUPLICATE" not in capsys.readouterr().out
    assert run([*args, "--against-repo"]) == 0
    assert capsys.readouterr().out.count("DUPLICATE") == 1
    assert run(["--root", str(tmp_path), "--against-repo", "new", "--min-nodes", "1"]) == 0
    assert capsys.readouterr().out.count("DUPLICATE") == 1
