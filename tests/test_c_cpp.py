import pytest

from dryer.discover import iter_source_files, language_of
from dryer.extract import entries_in_source
from dryer.scan import find_duplicates, scan_files


@pytest.mark.parametrize('suffix, language', [('.c', 'c'), ('.cpp', 'cpp'), ('.h', 'cpp'), ('.hpp', 'cpp'), ('.cc', 'cpp'), ('.C', 'cpp')])
def test_detects_c_cpp(suffix, language):
    assert language_of('source' + suffix) == language


@pytest.mark.parametrize('language, suffix', [('c', '.c'), ('cpp', '.cpp')])
def test_finds_renamed_functions_and_preserves_called_operations(tmp_path, language, suffix):
    sources = {
        'left': 'int alpha(int x) {\n int y = filter(x);\n return map(y) + 12;\n}\n',
        'right': 'int beta(int arg) {\n int kept = filter(arg);\n return map(kept) + 99;\n}\n',
        'different': 'int gamma(int arg) {\n int kept = select(arg);\n return map(kept) + 99;\n}\n',
    }
    for name, source in sources.items():
        (tmp_path / (name + suffix)).write_text(source)
    entries, warnings = scan_files(iter_source_files([tmp_path]), tmp_path, 1, 1)
    assert warnings == []
    pairs = find_duplicates(entries, 0.99)
    assert len(pairs) == 1
    assert pairs[0].language == language
    assert pairs[0].score == 1.0


def test_cpp_inline_methods_templates_and_nested_functions():
    source = '''int declared(int);
namespace demo {
struct Box {
    int run(int x) { return x + 1; }
};
template<class T> T twice(T x) {
    auto fn = [](int n) { return n + 1; };
    struct Local { int hidden() { return 0; } };
    return x + x;
}
}
'''
    entries, warning = entries_in_source('cpp', source, 'box.hpp', 'box.hpp')
    assert warning is None
    assert [(entry.start_line, entry.end_line) for entry in entries] == [(4, 4), (6, 10)]


def test_cpp_members_normalize_but_callee_names_stay():
    left, _ = entries_in_source('cpp', 'int a(Box x) { return x.filter(x.total); }', 'a.cpp', 'a.cpp')
    right, _ = entries_in_source('cpp', 'int b(Box y) { return y.filter(y.count); }', 'b.cpp', 'b.cpp')
    assert find_duplicates(left + right, 0.99)[0].score == 1.0


def test_does_not_compare_c_and_cpp():
    source = 'int f(int n) { return n + 1; }'
    c, _ = entries_in_source('c', source, 'a.c', 'a.c')
    cpp, _ = entries_in_source('cpp', source, 'b.cpp', 'b.cpp')
    assert c and cpp
    assert find_duplicates(c + cpp, 0.0) == []
