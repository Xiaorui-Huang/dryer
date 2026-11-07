# dryer

dryer finds candidate duplicate code in Clojure, Java, Go, TypeScript, Rust, Python, and C#. One run detects the language of each source file, normalizes that language's forms, and reports pairs whose structure is close enough to review.

Clojure follows [dry4clj](https://github.com/unclebob/dry4clj). The other languages use the same idea on the functions and methods [crapper](https://github.com/unclebob/crapper) and [mutator](https://github.com/unclebob/mutator) already treat as one unit. A form is only compared with forms written in the same language.

The score is Jaccard similarity of structural fingerprints:

```text
score = shared fingerprints / all fingerprints seen in either form
```

A score of `1.0` means the normalized structures have the same fingerprint set. The default `--threshold 0.82` reports candidates close enough to be worth review.

These two functions score `1.0`. The names, locals, predicates, and mapped functions differ, and those incidental symbols normalize away. A default run still skips them: they are three lines, and the default minimum is four.

```clojure
(defn alpha [xs]
  (let [ys (filter odd? xs)]
    (map inc ys)))

(defn beta [items]
  (let [kept (filter even? items)]
    (map dec kept)))
```

The same shape in the other languages scores `1.0` too: the called function or method stays, and the locals do not.

```java
int alpha(int[] xs) {
  int[] ys = filter(xs, odd);
  return map(ys, inc);
}
```

```python
def beta(items):
    kept = filter(items, even)
    return map(kept, dec)
```

What stays is the call or method name, the operator, and the shape of the tree. What drops out is the local name, the field name, the literal, and the keyword. A Clojure keyword call `(:kind m)` and `(:id row)` is the same shape. So is `order.total` and `row.amount`.

## Run

```bash
./dryer
```

The first run creates `.venv` and installs the tool. On Windows, run `dryer.cmd`, which does the same with `.venv\Scripts\python.exe`. From a project root it walks the tree, skips `test`, `spec`, `vendor`, `node_modules`, `target`, and C# test projects, and writes two results:

- a report on stdout, closest match first
- `.metrics/dry.edn`, replaced on every successful analysis

```bash
./dryer src/demo src/ui          # these files and trees
./dryer --changed                # git additions and edits
./dryer --changed-since origin/main  # branch commits and working edits
./dryer --changed-since origin/main --against-repo
./dryer billing                  # path fragment
./dryer --threshold 0.9 src
./dryer --edn --min-lines 3 src
```

Selection options choose whole files, not changed lines. By default, only
selected files are compared with each other. `--changed-since <ref>` uses the
merge base with HEAD, plus staged/unstaged edits and untracked source files;
it excludes deletions and commits only on the target. It requires an explicit
ref and cannot be combined with `--changed`. No PR or default branch is inferred.

`--against-repo` adds all discoverable source files under `--root` to the
comparison, but reports only pairs touching a selected file. Explicit paths,
filters, and `--source-root` select the files of interest, not the repository
comparison pool. Existing test/vendor/build exclusions still apply. With no
selected files, the report is empty. Output formats and thresholds are unchanged.

```text
--threshold N    Minimum structural similarity score, from 0 to 1, default 0.82
--min-lines N    Minimum source lines in a candidate form, default 4
--min-nodes N    Minimum normalized syntax nodes, default 20
--format F       text or edn, default text
--edn            Same as --format edn
--text           Same as --format text
```

Normalized syntax nodes are the structural pieces left after incidental names and literals are replaced. `--min-nodes` drops forms smaller than that before comparison.

Default text output for the invoice and receipt from dry4clj. They differ by one extra binding:

```text
DUPLICATE score=0.89
  src/billing/invoice.clj:3-13
  src/billing/receipt.clj:3-14
```

`.metrics/dry.edn` is the same report dry4clj prints as EDN, with the language added:

```clojure
{:candidates
 [{:score 0.890909090909
   :language "clojure"
   :left {:file "src/billing/invoice.clj", :start-line 3, :end-line 13}
   :right {:file "src/billing/receipt.clj", :start-line 3, :end-line 14}
   :left-nodes 158
   :right-nodes 166}]}
```

## What each language compares

| Language | Candidate | Left out |
| --- | --- | --- |
| Clojure | every top-level form except `ns` | reader-conditional branches other than `:clj` |
| Java | methods with a body | constructors, abstract methods, methods inside anonymous or local classes |
| Go | functions and methods with a body | function literals stay inside the enclosing function |
| TypeScript | functions, methods, and top-level arrow functions | callbacks nested inside another function |
| Rust | functions and methods with a body | functions inside `mod tests`, and closures |
| Python | functions and methods | functions nested inside another function |
| C# | methods, constructors, destructors, operators, and accessors with a body; properties and indexers with their own `=>` body | bodiless members, test projects, and local functions and lambdas, which stay inside their member |

A `.cs` file's project is the nearest folder at or above it that holds a `.csproj`. The project is a test project when its folder's name ends in `Tests` or has a dot-separated part `Test` or `Tests`, such as `App.Tests`, `App.UnitTests`, or `App.Test.Unit`. It is one too when its `.csproj` sets `<IsTestProject>true</IsTestProject>`, uses the `MSTest.Sdk` project SDK, or has a PackageReference to Microsoft.NET.Test.Sdk, NUnit, xunit, xunit.v3, MSTest, or MSTest.TestFramework. A test project's `.cs` files are skipped unless you name them, and so are those in any C# project's `bin/` and `obj/`. This is the rule crapper and skillflow's measure use.

Clojure reader conditionals keep the `:clj` branch, as dry4clj does. Syntax-quote is kept as a `syntax-quote` form rather than expanded.

A missing or unreadable Clojure form is reported on stderr. Forms read before it are still compared. The run exits `0` after a report, `1` on a usage error, and `2` on an unknown `--format`.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## C/C++ support in this fork

Supported extensions: `.c`, `.cc`, `.cpp`, `.cxx`, `.c++`, `.C`, `.h`, `.hpp`,
`.hh`, `.hxx`, `.h++`, `.H`, `.ipp`, `.inl`, `.tcc`. `.c` files are parsed
as C; all others, including `.h`, are parsed as C++. The walk skips
`test_*`, `*_test`, `*_tests` and test directories.

The tool compares function and method definitions, including those inline
in headers, constructors, operators and template definitions. Declarations
without a body are not compared. Lambdas and local classes remain part of
the enclosing function. Variable names and literal values are normalized;
names of called functions and methods, operators and structure are preserved.
C candidates are compared only with C, and C++ only with C++.

```bash
./dryer --root /path/to/project src include
./dryer --root /path/to/project --threshold 0.8 src include
```

No compiler or build is required. The preprocessor is not run, so functions
generated entirely by macros may be missed by the comparison.

```bash
.venv/bin/python -m pytest -q tests/test_c_cpp.py
```
