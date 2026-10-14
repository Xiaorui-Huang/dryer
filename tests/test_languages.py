from pathlib import Path

import pytest

from dryer.extract import entries_in_source
from dryer.model import Entry, Span
from dryer.scan import _keep, find_duplicates, scan_files
from dryer.shape import jaccard
from dryer.treesitter import descendants, end_line, parse


def write_source(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def pairs(root: Path):
    files = sorted(path for path in root.rglob("*") if path.is_file())
    entries, warnings = scan_files(files, root, min_lines=1, min_nodes=1)
    assert warnings == []
    return find_duplicates(entries, threshold=0.99)


JAVA_LEFT = """\
class Left {
  int alpha(int[] xs) {
    int[] ys = filter(xs, odd);
    return map(ys, inc);
  }
}
"""

JAVA_RIGHT = """\
class Right {
  int beta(int[] items) {
    int[] kept = filter(items, even);
    return map(kept, dec);
  }
}
"""

GO_LEFT = """\
package demo

func (b *Board) alpha(xs []int) []int {
	ys := filter(xs, odd)
	return mapFn(ys, inc)
}
"""

GO_RIGHT = """\
package demo

func (p *Panel) beta(items []int) []int {
	kept := filter(items, even)
	return mapFn(kept, dec)
}
"""

PY_LEFT = """\
class Board:
    def alpha(self, xs):
        ys = filter(xs, odd)
        return map(ys, inc)
"""

PY_RIGHT = """\
class Panel:
    def beta(self, items):
        kept = filter(items, even)
        return map(kept, dec)
"""

TS_LEFT = """\
export function alpha(xs: number[]): number[] {
  const ys = filter(xs, odd);
  return map(ys, inc);
}
"""

TS_RIGHT = """\
export function beta(items: number[]): number[] {
  const kept = filter(items, even);
  return map(kept, dec);
}
"""

TSX_LEFT = """\
export const alpha = (xs: number[]): number[] => {
  const ys = filter(xs, odd);
  return map(ys, inc);
};
"""

TSX_RIGHT = """\
export const beta = (items: number[]): number[] => {
  const kept = filter(items, even);
  return map(kept, dec);
};
"""

RUST_LEFT = """\
pub fn alpha(xs: Vec<i32>) -> Vec<i32> {
    let ys = filter(xs, odd);
    map(ys, inc)
}
"""

RUST_RIGHT = """\
pub fn beta(items: Vec<i32>) -> Vec<i32> {
    let kept = filter(items, even);
    map(kept, dec)
}
"""

CS_LEFT = """\
class Left
{
    int[] Alpha(int[] xs)
    {
        var ys = Filter(xs, odd);
        return Map(ys, inc);
    }
}
"""

CS_RIGHT = """\
class Right
{
    int[] Beta(int[] items)
    {
        var kept = Filter(items, even);
        return Map(kept, dec);
    }
}
"""


def test_each_language_matches_renamed_locals(tmp_path):
    samples = {
        "left.java": JAVA_LEFT,
        "right.java": JAVA_RIGHT,
        "left.go": GO_LEFT,
        "right.go": GO_RIGHT,
        "left.py": PY_LEFT,
        "right.py": PY_RIGHT,
        "left.ts": TS_LEFT,
        "right.ts": TS_RIGHT,
        "left.tsx": TSX_LEFT,
        "right.tsx": TSX_RIGHT,
        "left.rs": RUST_LEFT,
        "right.rs": RUST_RIGHT,
        "left.cs": CS_LEFT,
        "right.cs": CS_RIGHT,
    }
    for name, source in samples.items():
        write_source(tmp_path, name, source)
    found = pairs(tmp_path)
    by_language = {}
    for item in found:
        by_language.setdefault(item.language, []).append(item)
    assert set(by_language) == {"java", "go", "python", "typescript", "rust", "csharp"}
    assert [(item.left.file, item.right.file) for item in by_language["typescript"]] == [
        ("left.ts", "right.ts"),
        ("left.tsx", "right.tsx"),
    ]
    for language, group in by_language.items():
        assert all(item.score == 1.0 for item in group), language


def test_an_unrelated_csharp_method_pairs_with_neither_copy(tmp_path):
    write_source(tmp_path, "Left.cs", CS_LEFT)
    write_source(tmp_path, "Right.cs", CS_RIGHT)
    write_source(
        tmp_path,
        "Other.cs",
        """\
class Other
{
    void Gamma(string path)
    {
        if (File.Exists(path))
        {
            File.Delete(path);
        }
        Console.WriteLine(path);
    }
}
""",
    )
    files = sorted(tmp_path.glob("*.cs"))
    entries, warnings = scan_files(files, tmp_path, min_lines=1, min_nodes=1)
    assert warnings == []
    found = find_duplicates(entries, threshold=0.82)
    assert [(item.left.file, item.right.file, item.score) for item in found] == [
        ("Left.cs", "Right.cs", 1.0)
    ]

def test_a_csharp_file_with_a_byte_order_mark_and_crlf_still_pairs(tmp_path):
    (tmp_path / "Left.cs").write_bytes(b"\xef\xbb\xbf" + CS_LEFT.replace("\n", "\r\n").encode("utf-8"))
    write_source(tmp_path, "Right.cs", CS_RIGHT)
    assert [(item.left, item.right, item.score) for item in pairs(tmp_path)] == [
        (Span("Left.cs", 3, 7), Span("Right.cs", 3, 7), 1.0)
    ]

def test_different_callee_is_not_the_same_structure(tmp_path):
    write_source(
        tmp_path,
        "a.py",
        "def alpha(xs):\n    return filter(xs, odd)\n",
    )
    write_source(
        tmp_path,
        "b.py",
        "def beta(xs):\n    return select(xs, odd)\n",
    )
    files = sorted(tmp_path.glob("*.py"))
    entries, warnings = scan_files(files, tmp_path, min_lines=1, min_nodes=1)
    assert warnings == []
    found = find_duplicates(entries, threshold=0.0)
    assert len(found) == 1
    assert found[0].score < 1.0


def test_nested_functions_stay_inside_the_enclosing_function(tmp_path):
    write_source(
        tmp_path,
        "a.py",
        """\
def alpha(xs):
    def inner(ys):
        return filter(ys, odd)
    return inner(xs)
""",
    )
    write_source(
        tmp_path,
        "b.py",
        """\
def beta(items):
    def inner(kept):
        return filter(kept, even)
    return inner(items)
""",
    )
    found = pairs(tmp_path)
    assert len(found) == 1
    assert found[0].score == 1.0
    assert found[0].left.start_line == 1


def test_rust_tests_module_is_not_production_code(tmp_path):
    write_source(
        tmp_path,
        "a.rs",
        """\
pub fn alpha(xs: Vec<i32>) -> Vec<i32> {
    let ys = filter(xs, odd);
    map(ys, inc)
}

mod tests {
    pub fn helper(xs: Vec<i32>) -> Vec<i32> {
        let ys = filter(xs, odd);
        map(ys, inc)
    }
}
""",
    )
    write_source(tmp_path, "b.rs", RUST_RIGHT)
    found = pairs(tmp_path)
    assert len(found) == 1
    assert found[0].left.file == "a.rs"
    assert found[0].left.start_line == 1


def test_an_extra_statement_lowers_the_score(tmp_path):
    write_source(tmp_path, "a.java", JAVA_LEFT)
    write_source(
        tmp_path,
        "b.java",
        """\
class Right {
  int beta(int[] items) {
    int[] kept = filter(items, even);
    int[] extra = filter(kept, even);
    return map(extra, dec);
  }
}
""",
    )
    files = sorted(tmp_path.glob("*.java"))
    entries, warnings = scan_files(files, tmp_path, min_lines=1, min_nodes=1)
    assert warnings == []
    found = find_duplicates(entries, threshold=0.5)
    assert len(found) == 1
    assert found[0].score < 1.0


def _suffix(language: str) -> str:
    return {"python": "py", "go": "go", "rust": "rs", "java": "java", "typescript": "ts"}[language]


def test_callee_names_stay_and_member_names_do_not(tmp_path):
    samples = {
        "left.py": """\
def alpha(xs):
    ys = xs.filter(odd)
    return (len)(xs.total)
""",
        "right.py": """\
def beta(items):
    kept = items.filter(even)
    return (len)(items.count)
""",
        "left.go": """\
package demo

func alpha(xs []int) {
	fmt.Println(xs)
}
""",
        "right.go": """\
package demo

func beta(items []int) {
	log.Println(items)
}
""",
        "left.rs": """\
pub fn alpha(xs: Vec<i32>) -> Vec<i32> {
    let ys = Vec::new();
    let zs = HashMap::<String, i32>::new();
    xs.iter()
}
""",
        "right.rs": """\
pub fn beta(items: Vec<i32>) -> Vec<i32> {
    let kept = Vec::new();
    let rows = HashMap::<Integer, i32>::new();
    items.iter()
}
""",
        "left.java": """\
class Left {
  int alpha(List xs) {
    List ys = new ArrayList<String>();
    ys.add(xs);
    return xs.total;
  }
}
""",
        "right.java": """\
class Right {
  int beta(List items) {
    List kept = new ArrayList<Integer>();
    kept.add(items);
    return items.count;
  }
}
""",
        "left.ts": """\
export function alpha(xs: number[]): number {
  return foo<string>(xs.bar);
}
""",
        "right.ts": """\
export function beta(items: number[]): number {
  return foo<number>(items.baz);
}
""",
    }
    for name, source in samples.items():
        write_source(tmp_path, name, source)
    found = pairs(tmp_path)
    by_language = {}
    for item in found:
        by_language.setdefault(item.language, []).append(item)
    assert set(by_language) == {"python", "go", "rust", "java", "typescript"}
    for language, group in by_language.items():
        assert [(item.left.file, item.right.file, item.score) for item in group] == [
            (f"left.{_suffix(language)}", f"right.{_suffix(language)}", 1.0)
        ], language


def test_a_different_callee_name_lowers_the_score(tmp_path):
    write_source(tmp_path, "a.py", "def alpha(xs):\n    return xs.filter(odd)\n")
    write_source(tmp_path, "b.py", "def beta(items):\n    return items.select(even)\n")
    write_source(tmp_path, "a.rs", "fn alpha() {\n    Vec::new()\n}\n")
    write_source(tmp_path, "b.rs", "fn beta() {\n    Vec::with_capacity(1)\n}\n")
    files = sorted(path for path in tmp_path.rglob("*") if path.is_file())
    entries, warnings = scan_files(files, tmp_path, min_lines=1, min_nodes=1)
    assert warnings == []
    found = find_duplicates(entries, threshold=0.0)
    assert len(found) == 2
    assert all(item.score < 1.0 for item in found)


def forms(language: str, source: str, file: str) -> list[Entry]:
    entries, warning = entries_in_source(language, source, file, file)
    assert warning is None
    return entries


def spans(language: str, source: str, file: str) -> list[tuple[int, int]]:
    return [(entry.start_line, entry.end_line) for entry in forms(language, source, file)]


def test_a_parenthesized_callee_matches_the_bare_call():
    wrapped = forms("python", "def alpha(xs):\n    return (len)(xs)\n", "a.py")
    bare = forms("python", "def beta(items):\n    return len(items)\n", "b.py")
    assert any("len" in item for item in wrapped[0].fingerprints)
    found = find_duplicates(wrapped + bare, threshold=0.99)
    assert len(found) == 1
    assert found[0].score == 1.0


def test_a_string_and_a_number_normalize_to_the_same_literal():
    string = forms("python", 'def alpha(xs):\n    return "xs"\n', "a.py")
    number = forms("python", "def beta(items):\n    return 1\n", "b.py")
    assert any(item == ":literal" for item in number[0].fingerprints)
    found = find_duplicates(string + number, threshold=0.99)
    assert len(found) == 1
    assert found[0].score == 1.0


def test_an_interpolated_string_is_not_a_plain_literal():
    plain = forms("python", 'def alpha(xs):\n    return "xs"\n', "a.py")
    interpolated = forms("python", 'def beta(items):\n    return f"{items}"\n', "b.py")
    found = find_duplicates(plain + interpolated, threshold=0.0)
    assert len(found) == 1
    assert found[0].score < 1.0


_BODIES = {
    "rust": ("a.rs", "fn f(x: T, y: T) {{\n    {}\n}}\n"),
    "python": ("a.py", "def f(x, y):\n    {}\n"),
    "typescript": ("a.ts", "function f(x, y) {{\n  {};\n}}\n"),
    "go": ("a.go", "package demo\n\nfunc f(x int, y int, c chan int) {{\n\t{}\n}}\n"),
    "csharp": ("a.cs", "class C {{\n  object f(object x, object y) {{\n    {}\n  }}\n}}\n"),
}


def _function(language: str, body: str) -> Entry:
    file, template = _BODIES[language]
    [entry] = forms(language, template.format(body), file)
    return entry


def _pair_score(language: str, left: str, right: str) -> float:
    return jaccard(_function(language, left).fingerprints, _function(language, right).fingerprints)


@pytest.mark.parametrize(
    ("language", "left", "right"),
    [
        ("rust", "x..y", "x..=y"),
        ("rust", 'format!("{}", approve(x))', 'format!("{}", reject(x))'),
        ("rust", "assert!(x.approve())", "assert!(x.reject())"),
        ("rust", 'format!("{}", vec![x])', 'format!("{}", dbg![x])'),
        ("rust", 'println!("{}", x)', 'panic!("{}", x)'),
        ("rust", 'std::println!("{}", x)', 'std::panic!("{}", x)'),
        ("python", "return x in y", "return x is y"),
        ("python", "return x not in y", "return x is not y"),
        ("python", "return x in y", "return x not in y"),
        ("python", "return x // y", "return x @ y"),
        ("python", "x **= y", "x //= y"),
        ("python", "x @= y", "x //= y"),
        ("typescript", "return `${approve(x)}`", "return `${reject(x)}`"),
        ("typescript", "return x in y", "return x instanceof y"),
        ("typescript", "return typeof x", "return void x"),
        ("typescript", "return delete x.a", "return typeof x.a"),
        ("typescript", "x &&= y", "x ??= y"),
        ("typescript", "x ||= y", "x **= y"),
        ("csharp", "return x.Filter(y);", "return x.Select(y);"),
        ("csharp", "return Console.WriteLine(x);", "return Console.Write(x);"),
        ("csharp", "return this.Approve(x);", "return this.Reject(x);"),
        ("csharp", "return base.Approve(x);", "return base.Reject(x);"),
        ("csharp", "return x?.Approve();", "return x?.Reject();"),
        ("csharp", "return x?.A.Approve();", "return x?.A.Reject();"),
        ("csharp", "return Approve<int>(x);", "return Reject<int>(x);"),
        ("csharp", "return Outer.Approve<int>(x);", "return Outer.Reject<int>(x);"),
        ("csharp", "return new List<int>();", "return new HashSet<int>();"),
        ("csharp", "return new System.Text.StringBuilder();", "return new System.IO.StringWriter();"),
        ("csharp", "return new Foo { A = 1 };", "return new Bar { A = 1 };"),
        ("csharp", "return new Foo(x) { A = Approve(x) };", "return new Foo(x) { A = Reject(x) };"),
        ("csharp", 'return $"{Approve(x)}";', 'return $"{Reject(x)}";'),
        ("csharp", "return new global::Foo();", "return new global::Bar();"),
        ("csharp", "return new Alias::Foo();", "return new Alias::Bar();"),
    ],
)
def test_a_different_operator_or_embedded_call_lowers_the_score(language, left, right):
    assert _pair_score(language, left, right) < 1.0


@pytest.mark.parametrize(
    ("language", "left", "right"),
    [
        ("rust", "x..=y", "y..=x"),
        ("rust", 'format!("left {}", approve(x))', 'format!("right {:?}", approve(y))'),
        ("rust", "assert_eq!(x.len, y)", "assert_eq!(y.size, x)"),
        ("python", "return x not in y", "return y not in x"),
        ("python", 'return f"left {approve(x)}"', 'return f"right {approve(y)}"'),
        ("typescript", "return typeof x", "return typeof y"),
        ("typescript", "return `left ${approve(x)}`", "return `right ${approve(y)}`"),
        ("typescript", "return `left ${approve(x)}`", "return `${approve(y)}`"),
        ("typescript", "return `a\\n${approve(x)}`", "return `a${approve(y)}`"),
        ("python", 'return f"left {approve(x)}"', 'return f"{approve(y)}"'),
        ("python", 'return f"a\\n{approve(x)}"', 'return f"a{approve(y)}"'),
        ("go", "return x &^ y", "return y &^ x"),
        ("csharp", "return x.Filter(y);", "return y.Filter(x);"),
        ("csharp", "return x.Length;", "return y.Count;"),
        ("csharp", "return x?.Length;", "return y?.Count;"),
        ("csharp", "return 1;", "return 2.5;"),
        ("csharp", 'return "a";', 'return @"b";'),
        ("csharp", 'return $"t";', 'return "t";'),
        ("csharp", 'return $"left {Approve(x)}";', 'return $"right {Approve(y)}";'),
        ("csharp", "return new Foo { A = 1 };", "return new Foo { B = 2 };"),
    ],
)
def test_renamed_locals_and_literal_text_still_match(language, left, right):
    assert _pair_score(language, left, right) == 1.0


@pytest.mark.parametrize(
    ("language", "commented", "plain"),
    [
        ("rust", "foo /* c */ (x)", "foo(x)"),
        ("typescript", "return foo /* c */ (x)", "return foo(x)"),
        ("go", "_ = foo /* c */ (x)", "_ = foo(x)"),
        ("csharp", "return Foo /* c */ (x);", "return Foo(x);"),
        ("csharp", "return x.Foo /* c */ (y);", "return x.Foo(y);"),
    ],
)
def test_a_comment_between_a_callee_and_its_arguments_is_skipped(language, commented, plain):
    assert _pair_score(language, commented, plain) == 1.0


@pytest.mark.parametrize(
    ("body", "operator"),
    [
        ("_ = x &^ y", "&^"),
        ("x &^= y", "&^="),
        ("_ = <-c", "<-"),
    ],
)
def test_a_go_operator_stays_in_the_fingerprint(body, operator):
    assert f'[:symbol "{operator}"]' in _function("go", body).fingerprints


def test_constructed_names_stay_in_the_fingerprint():
    rust = forms(
        "rust",
        """\
pub fn alpha() {
    let ys = Vec::new();
    let zs = HashMap::<String, i32>::new();
}
""",
        "a.rs",
    )
    java = forms(
        "java",
        """\
class Left {
  int alpha() {
    return new ArrayList<String>();
  }
}
""",
        "a.java",
    )
    rust_names = " ".join(rust[0].fingerprints)
    java_names = " ".join(java[0].fingerprints)
    assert "Vec" in rust_names
    assert "new" in rust_names
    assert "HashMap" in rust_names
    assert "ArrayList" in java_names


def test_a_class_contributes_its_method_only():
    assert spans(
        "python",
        "class Board:\n    def alpha(self, xs):\n        return xs\n",
        "a.py",
    ) == [(2, 3)]


def test_java_keeps_the_method_that_has_its_own_body():
    assert spans(
        "java",
        """\
abstract class Left {
  abstract int declared(int[] xs);
  int alpha(int[] xs) {
    class Inner {
      int run(int[] ys) {
        return ys.length;
      }
    }
    return xs.length;
  }
}
""",
        "a.java",
    ) == [(3, 10)]


def test_a_go_function_needs_a_body():
    assert spans(
        "go",
        """\
package demo

func declared(xs []int)

func alpha(xs []int) int {
	return len(xs)
}
""",
        "a.go",
    ) == [(5, 7)]


def test_a_closure_in_a_let_stays_inside_the_function():
    assert spans(
        "rust",
        """\
fn alpha() {
    let f = || { let x = 1; };
}
""",
        "a.rs",
    ) == [(1, 3)]


def test_a_method_nested_in_a_function_is_not_its_own_candidate():
    assert spans(
        "typescript",
        """\
export function outer(xs: number[]): number[] {
  class Hidden {
    run(ys: number[]): number[] {
      return ys;
    }
  }
  return xs;
}
""",
        "a.ts",
    ) == [(1, 8)]


def test_rust_keeps_helpers_and_skips_tests_and_signatures():
    assert spans(
        "rust",
        """\
fn declared();

fn alpha(xs: Vec<i32>) -> usize {
    xs.len()
}

mod helpers {
    fn beta(xs: Vec<i32>) -> usize {
        xs.len()
    }
}

mod tests {
    fn gamma(xs: Vec<i32>) -> usize {
        xs.len()
    }
}
""",
        "a.rs",
    ) == [(3, 5), (8, 10)]


_CSHARP_MEMBERS = """\
namespace Demo;

public abstract class Board
{
    public Board(int start)
    {
        total = start;
    }
    ~Board()
    {
        Dispose();
    }
    public abstract void Declared();
    public partial void Later();
    public int Alpha(int[] xs)
    {
        int Local(int q) { return q + 1; }
        Func<int, int> f = x => { return x * 2; };
        return Local(xs.Length) + f(1);
    }
    public int Beta() => total + 1;
    public int Auto { get; set; }
    public int Count => total;
    public int Kept
    {
        get { return total; }
        set { total = value; }
    }
    public int this[int i] => items[i];
    public static Board operator +(Board a, Board b) { return a; }
    public static implicit operator int(Board b) => b.total;
    public event EventHandler Changed
    {
        add { handlers += value; }
        remove { handlers -= value; }
    }
}

public interface IShape
{
    double Area();
    double Twice() { return Area() * 2; }
}

public record Point(int X, int Y)
{
    public int Sum() { return X + Y; }
}

public struct Cell
{
    public int Value() { return 1; }
}
"""


def test_csharp_keeps_members_that_have_a_body():
    """Local functions and lambdas stay in the member that holds them."""

    assert spans("csharp", _CSHARP_MEMBERS, "a.cs") == [
        (5, 8),
        (9, 12),
        (15, 20),
        (21, 21),
        (23, 23),
        (26, 26),
        (27, 27),
        (29, 29),
        (30, 30),
        (31, 31),
        (34, 34),
        (35, 35),
        (42, 42),
        (47, 47),
        (52, 52),
    ]

def test_typescript_keeps_methods_and_skips_nested_functions():
    assert spans(
        "typescript",
        """\
export class Box {
  run(xs: number[]): number[] {
    return xs;
  }
}
export function outer(xs: number[]): number[] {
  function inner(ys: number[]): number[] {
    return ys;
  }
  const cb = (zs: number[]) => zs;
  return inner(xs);
}
xs.map((item: number) => item + 1);
""",
        "a.ts",
    ) == [(2, 4), (6, 12)]


def test_a_private_field_name_is_not_part_of_the_structure():
    entries = forms(
        "typescript",
        """\
export class Box {
  value(): number {
    return this.#total;
  }
  run(xs: number[]): number[] {
    return this.#hidden(xs);
  }
}
""",
        "a.ts",
    )
    assert [(entry.start_line, entry.end_line) for entry in entries] == [(2, 4), (5, 7)]
    printed = " ".join(item for entry in entries for item in entry.fingerprints)
    assert "#total" not in printed
    assert "#hidden" not in printed


def test_end_line_uses_the_last_occupied_row():
    source = "def alpha(xs):\n    return xs\n"
    _data, tree = parse(source, "python")
    function = next(node for node in descendants(tree.root_node) if node.type == "function_definition")
    assert end_line(tree.root_node) == 2
    assert end_line(function) == 2
    assert spans("python", source, "a.py") == [(1, 2)]


def _entry(
    file: str,
    start: int,
    end: int,
    names: set[str],
    language: str = "python",
    nodes: int = 20,
    offset: int = 0,
):
    return Entry(language, file, start, end, offset, nodes, frozenset(names))


def test_the_same_form_is_not_a_pair():
    assert find_duplicates([
        _entry("a.py", 1, 4, {"q"}),
        _entry("a.py", 1, 4, {"q"}),
    ], 0.0) == []
    assert len(find_duplicates([
        _entry("a.py", 1, 4, {"q"}),
        _entry("b.py", 1, 4, {"q"}),
    ], 0.5)) == 1
    assert len(find_duplicates([
        _entry("a.py", 1, 1, {"q"}, offset=0),
        _entry("a.py", 1, 1, {"q"}, offset=30),
    ], 0.5)) == 1


_NESTED_RUST = """\
fn outer() { impl S { fn inner(&self) -> i32 {
    let a = self.x + 1;
    let b = self.y * 2;
    if a > b { a - b } else { b - a }
} } }
"""


@pytest.mark.parametrize(
    ("language", "file", "source"),
    [
        ("rust", "a.rs", "fn a() -> i32 { return 1 + 2; } fn b() -> i32 { return 3 + 4; }\n"),
        ("typescript", "a.ts", "function a() { return 1 + 2; } function b() { return 3 + 4; }\n"),
        ("typescript", "a.ts", "class A { a = () => { return 1 + 2; }; b = () => { return 3 + 4; } }\n"),
        ("go", "a.go", "package p\nfunc a() int { return 1 + 2 }; func b() int { return 3 + 4 }\n"),
        ("rust", "a.rs", _NESTED_RUST),
    ],
)
def test_functions_that_share_a_line_range_are_a_pair(language, file, source):
    entries = forms(language, source, file)
    assert len(entries) == 2
    assert len(find_duplicates(entries, 0.0)) == 1


def test_a_function_extracted_twice_is_not_paired_with_itself():
    source = "fn a() -> i32 { return 1 + 2; }\n"
    assert find_duplicates(forms("rust", source, "a.rs") + forms("rust", source, "a.rs"), 0.0) == []


def test_a_score_equal_to_the_threshold_is_kept():
    left = _entry("a.rs", 1, 4, {"x", "y"}, language="rust")
    right = _entry("b.rs", 1, 4, {"x", "z"}, language="rust")
    assert len(find_duplicates([left, right], 1 / 3)) == 1
    assert find_duplicates([left, right], 1 / 3 + 0.01) == []


def test_the_higher_score_is_reported_first():
    exact = [
        _entry("a.py", 1, 4, {"only"}),
        _entry("b.py", 1, 4, {"only"}),
    ]
    partial = [
        _entry("a.rs", 1, 4, {"x", "y"}, language="rust"),
        _entry("b.rs", 10, 14, {"x", "z"}, language="rust"),
    ]
    found = find_duplicates(partial + exact, 0.3)
    assert [item.score for item in found] == [1.0, 1 / 3]


def test_keep_uses_the_line_and_node_minimums():
    assert _keep(_entry("a.py", 1, 4, {"q"}, nodes=20), 4, 20) is True
    assert _keep(_entry("a.py", 1, 3, {"q"}, nodes=20), 4, 20) is False
    assert _keep(_entry("a.py", 1, 4, {"q"}, nodes=19), 4, 20) is False


def test_a_deep_expression_is_read():
    expr = " + ".join(["1"] * 1200)
    entries, warning = entries_in_source("python", f"def place():\n    return {expr}\n", "app.py", "app.py")
    assert warning is None
    assert entries
    nested = "(inc " * 1200 + "x" + ")" * 1200
    entries, warning = entries_in_source("clojure", f"(defn place [] {nested})\n", "app.clj", "app.clj")
    assert warning is None
    assert entries


def test_threshold_zero_pairs_forms_that_share_no_fingerprint():
    def form(file: str, fingerprints: set[str]) -> Entry:
        return Entry("python", file, 1, 5, 0, 20, frozenset(fingerprints))

    found = find_duplicates([form("a.py", {"x", "y"}), form("b.py", {"z"})], 0.0)
    assert [(item.left.file, item.right.file, item.score) for item in found] == [("a.py", "b.py", 0.0)]


def test_a_match_is_found_whatever_size_order_the_forms_come_in():
    shared = {f"f{index}" for index in range(10)}
    small = Entry("python", "small.py", 1, 5, 0, 20, frozenset(shared))
    large = Entry("python", "large.py", 1, 5, 0, 20, frozenset(shared | {"extra"}))
    for entries in ([small, large], [large, small]):
        found = find_duplicates(entries, 0.9)
        assert [round(item.score, 3) for item in found] == [0.909]
