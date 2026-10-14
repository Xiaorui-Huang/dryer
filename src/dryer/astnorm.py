"""Normalize a tree-sitter tree the way dry4clj normalizes a Clojure form.

The name in call position stays: `filter`, `Println`, `map`, an operator, the
type constructed by `new`. Local names, field names, type names in argument
position, and literals become generic markers. Two functions that call the
same operations in the same shape therefore share a fingerprint set even when
their locals differ.
"""

from __future__ import annotations

from dryer.shape import K
from dryer.treesitter import node_text

# Comments, and the literal text around an interpolation: only the
# interpolated code of a string counts.
_SKIP = {
    "comment",
    "line_comment",
    "block_comment",
    "documentation_comment",
    "doc_comment",
    "string_fragment",
    "string_content",
    "escape_sequence",
}

_IDENTIFIERS = {
    "namespace_identifier",
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "shorthand_property_identifier",
    "shorthand_property_identifier_pattern",
    "package_identifier",
}

_LITERALS = {
    "number_literal",
    "concatenated_string",
    "nullptr",
    "string",
    "string_literal",
    "interpreted_string_literal",
    "raw_string_literal",
    "char_literal",
    "rune_literal",
    "character_literal",
    "number",
    "integer",
    "float",
    "decimal_integer_literal",
    "hex_integer_literal",
    "octal_integer_literal",
    "binary_integer_literal",
    "decimal_floating_point_literal",
    "hex_floating_point_literal",
    "int_literal",
    "float_literal",
    "imaginary_literal",
    "integer_literal",
    "true",
    "false",
    "null",
    "nil",
    "none",
    "undefined",
    "null_literal",
    "boolean_literal",
    "template_string",
    "regex",
    "regex_literal",
    "real_literal",
    "verbatim_string_literal",
    "interpolated_string_expression",
}

_OPERATORS = {
    "+",
    "-",
    "*",
    "/",
    "%",
    "**",
    "==",
    "!=",
    "<",
    ">",
    "<=",
    ">=",
    "===",
    "!==",
    "&&",
    "||",
    "&",
    "|",
    "^",
    "<<",
    ">>",
    ">>>",
    "+=",
    "-=",
    "*=",
    "/=",
    "%=",
    "&=",
    "|=",
    "^=",
    "<<=",
    ">>=",
    ">>>=",
    "!",
    "~",
    "++",
    "--",
    "and",
    "or",
    "not",
    "??",
    "?.",
    "=",
    ":=",
    "=>",
    "?",
    "..",
    "..=",
}

# The grammar names an expression's operator token in one of these fields. Any
# token there stays, so an operator missing from _OPERATORS still counts.
_OPERATOR_FIELDS = {"operator", "operators"}

_CALLS = {
    "call",
    "call_expression",
    "method_invocation",
    "object_creation_expression",
    "new_expression",
    "macro_invocation",
    "invocation_expression",
}

_ATTRIBUTES = {
    "attribute",
    "member_expression",
    "selector_expression",
    "field_access",
    "field_expression",
    "member_access_expression",
    "conditional_access_expression",
    "member_binding_expression",
}

# Read as a path when called or constructed, so each name in it stays.
_SCOPED = {
    "qualified_identifier",
    "scoped_identifier",
    "scoped_type_identifier",
    "generic_type",
    "qualified_name",
    "generic_name",
}

# What follows the callee: the argument list, and C#'s object initializer, as in
# `new Foo(x) { A = 1 }` and `new Foo { A = 1 }`.
_CALL_TAILS = {"argument_list", "arguments", "token_tree", "initializer_expression"}
_INTERPOLATIONS = {"interpolation", "template_substitution"}
_TYPE_ARGS = {"type_arguments", "type_parameters"}

_DATA: bytes = b""


def normalize(node, data: bytes):
    """Normalized tree for `node`, or None when the node is only punctuation."""

    global _DATA
    _DATA = data
    return _normalize(node)


def _text(node) -> str:
    return node_text(_DATA, node)


_PENDING = object()


def _is_literal(node) -> bool:
    """A literal's text drops out. A string that interpolates code is not a literal."""

    if node.type not in _LITERALS:
        return False
    return not any(child.type in _INTERPOLATIONS for child in node.children)


def _named_before_args(node):
    """The callee's parts, and the argument list and initializer that follow."""

    named = node.named_children
    for index, child in enumerate(named):
        if child.type in _CALL_TAILS:
            return named[:index], [item for item in named[index:] if item.type in _CALL_TAILS]
    return named, []


def _without_type_args(nodes):
    type_args = [child for child in nodes if child.type in _TYPE_ARGS]
    rest = [child for child in nodes if child.type not in _TYPE_ARGS]
    return rest, type_args


def _callee_leaf(node):
    if node.type in _IDENTIFIERS:
        return [K("symbol"), _text(node)]
    return _PENDING


def _named_leaf(node, head: bool):
    if node.type in _IDENTIFIERS:
        if head:
            return [K("symbol"), _text(node)]
        return K("symbol")
    if _is_literal(node):
        return K("literal")
    return _PENDING


def _try_leaf(node, mode: str, head: bool):
    if mode == "callee":
        return _callee_leaf(node)
    if mode == "path":
        return _PENDING
    if mode == "operator":
        return [K("symbol"), node.type]
    if node.type in _SKIP:
        return None
    if node.type in _OPERATORS:
        return [K("symbol"), node.type]
    if not node.is_named:
        return None
    return _named_leaf(node, head)


def _called_in_tokens(children, index: int) -> bool:
    """In a macro's token tree, `name(` is a call and `name!` is a macro.

    A token tree always ends with its closing delimiter (tree-sitter inserts a
    missing one), so an identifier always has a following token.
    """

    if children[index].type != "identifier":
        return False
    following = children[index + 1]
    if following.type == "!":
        return True
    return following.type == "token_tree" and following.children[0].type == "("


def _child_mode(node, children, index: int) -> str:
    if node.field_name_for_child(index) in _OPERATOR_FIELDS:
        return "operator"
    if node.type == "token_tree" and _called_in_tokens(children, index):
        return "callee"
    return "norm"


def _child_jobs(node):
    children = node.children
    return [(child, _child_mode(node, children, index), False) for index, child in enumerate(children)]


def _call_jobs(node):
    incoming, args = _named_before_args(node)
    rest, type_args = _without_type_args(incoming)
    jobs = []
    if rest:
        *receivers, callee = rest
        jobs.extend((child, "norm", False) for child in receivers)
        jobs.append((callee, "callee", False))
    jobs.extend((child, "norm", False) for child in type_args)
    jobs.extend((child, "norm", False) for child in args)
    return jobs


def _attr_jobs(node, head: bool):
    named = list(node.named_children)
    if not named:
        return []
    *objects, name = named
    jobs = [(obj, "norm", False) for obj in objects]
    if name.type in _IDENTIFIERS:
        return jobs
    if head:
        jobs.append((name, "callee", False))
    else:
        jobs.append((name, "norm", False))
    return jobs


def _path_jobs(node):
    jobs = []
    for child in node.named_children:
        if child.type in _IDENTIFIERS:
            continue
        if child.type in _SCOPED:
            jobs.append((child, "path", False))
        else:
            jobs.append((child, "norm", False))
    return jobs


def _callee_jobs(node):
    if node.type in _ATTRIBUTES:
        return _attr_jobs(node, True)
    if node.type in _SCOPED:
        return _path_jobs(node)
    return [(node, "norm", True)]


def _jobs(node, mode: str, head: bool):
    if mode == "callee":
        return _callee_jobs(node)
    if mode == "path":
        return _path_jobs(node)
    if node.type == "parenthesized_expression" and len(node.named_children) == 1:
        return [(node.named_children[0], "norm", head)]
    if node.type in _CALLS:
        return _call_jobs(node)
    if node.type in _ATTRIBUTES:
        return _attr_jobs(node, head)
    return _child_jobs(node)


def _name_value(name, head: bool, cache):
    """Keep a member's spelling when it is the thing being called."""

    if name.type in _IDENTIFIERS:
        if head:
            return [K("symbol"), _text(name)]
        return K("symbol")
    if head:
        return cache[(id(name), "callee", False)]
    return cache[(id(name), "norm", False)]


def _assemble_call(node, cache):
    incoming, args = _named_before_args(node)
    rest, type_args = _without_type_args(incoming)
    out = [K(node.type)]
    if rest:
        *receivers, callee = rest
        for child in receivers:
            norm = cache[(id(child), "norm", False)]
            if norm is not None:
                out.append(norm)
        out.append(cache[(id(callee), "callee", False)])
    for child in [*type_args, *args]:
        norm = cache[(id(child), "norm", False)]
        if norm is not None:
            out.append(norm)
    return out


def _assemble_attr(node, head: bool, cache):
    named = list(node.named_children)
    if not named:
        return [K(node.type)]
    *objects, name = named
    parts = [K(node.type)]
    for obj in objects:
        norm = cache[(id(obj), "norm", False)]
        if norm is not None:
            parts.append(norm)
    nested = _name_value(name, head, cache)
    if nested is not None:
        parts.append(nested)
    return parts


def _assemble_path(node, cache):
    """A callee path keeps each name in the path. Type arguments stay structural."""

    parts = [K(node.type)]
    for child in node.named_children:
        if child.type in _IDENTIFIERS:
            parts.append([K("symbol"), _text(child)])
        elif child.type in _SCOPED:
            parts.append(cache[(id(child), "path", False)])
        else:
            norm = cache[(id(child), "norm", False)]
            if norm is not None:
                parts.append(norm)
    return parts


def _callee_value(node, cache):
    if node.type in _ATTRIBUTES:
        return _assemble_attr(node, True, cache)
    if node.type in _SCOPED:
        return _assemble_path(node, cache)
    return cache[(id(node), "norm", True)]


def _assemble_children(node, cache):
    children = []
    for child, mode, head in _child_jobs(node):
        norm = cache[(id(child), mode, head)]
        if norm is not None:
            children.append(norm)
    return [K(node.type), *children]


def _assemble(node, mode: str, head: bool, cache):
    if mode == "callee":
        return _callee_value(node, cache)
    if mode == "path":
        return _assemble_path(node, cache)
    if node.type == "parenthesized_expression" and len(node.named_children) == 1:
        child = node.named_children[0]
        return cache[(id(child), "norm", head)]
    if node.type in _CALLS:
        return _assemble_call(node, cache)
    if node.type in _ATTRIBUTES:
        return _assemble_attr(node, head, cache)
    return _assemble_children(node, cache)


def _normalize(node, head: bool = False):
    # Post-order. A 1,200-deep expression must not raise RecursionError.
    cache = {}
    stack = [(node, "norm", head, False)]
    while stack:
        current, mode, is_head, expanded = stack.pop()
        key = (id(current), mode, is_head)
        if not expanded:
            if key in cache:
                continue
            leaf = _try_leaf(current, mode, is_head)
            if leaf is not _PENDING:
                cache[key] = leaf
                continue
            stack.append((current, mode, is_head, True))
            for child, child_mode, child_head in reversed(_jobs(current, mode, is_head)):
                stack.append((child, child_mode, child_head, False))
            continue
        cache[key] = _assemble(current, mode, is_head, cache)
    return cache[(id(node), "norm", head)]
