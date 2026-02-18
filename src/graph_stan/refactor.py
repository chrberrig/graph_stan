#!/usr/bin/env python3
# coding: utf-8

"""
graph_stan_refactor.py

Stan dependency graph visualizer:
- Builds a symbol table from declarations (new+old array syntax)
- Parses statements with a lightweight scanner (semicolon-aware, bracket/paren-aware)
- Tracks loop indices as scoped locals (plate/index awareness)
- Extracts dependencies from expressions without losing function arguments
- Renders Graphviz graph

Usage:
  python graph_stan_refactor.py model.stan -o deps --explicit
  python graph_stan_refactor.py model.stan --greek --shorten-expr 80
"""

from __future__ import annotations

import os
import argparse
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import graphviz


# ----------------------------
# Utilities: comments, scanning
# ----------------------------

def remove_comments(stan: str) -> str:
    # remove // comments
    stan = re.sub(r"//.*?$", "", stan, flags=re.MULTILINE)
    # remove /* ... */ comments
    stan = re.sub(r"/\*.*?\*/", "", stan, flags=re.DOTALL)
    return stan


def find_all_blocks(content: str) -> Dict[str, str]:
    """
    Extracts top-level Stan blocks.
    Handles names like "transformed parameters".
    """
    blocks: Dict[str, str] = {}
    # match a block name followed by {
    block_pattern = r'(\w+(?:\s+\w+)*)\s*\{'
    matches = list(re.finditer(block_pattern, content))

    for match in matches:
        block_name = match.group(1).strip()
        start = match.end()
        depth = 1
        end = start
        while depth > 0 and end < len(content):
            if content[end] == "{":
                depth += 1
            elif content[end] == "}":
                depth -= 1
            end += 1
        blocks[block_name] = content[start:end - 1].strip()
    return blocks


def split_statements(block_src: str) -> List[str]:
    """
    Tokenize block source into:
      - statements ending in ';' (outside (), [], {})
      - standalone '{' and '}' tokens (outside (), [], and strings)
      - loop/if/while headers ending with '{' as their own tokens
    This makes loop bodies parseable.
    """
    out: List[str] = []
    buf: List[str] = []

    par = brk = 0
    in_str = False
    esc = False

    def flush():
        s = "".join(buf).strip()
        if s:
            out.append(s)
        buf.clear()

    for ch in block_src:
        buf.append(ch)

        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue

        if ch == "(":
            par += 1
        elif ch == ")":
            par = max(0, par - 1)
        elif ch == "[":
            brk += 1
        elif ch == "]":
            brk = max(0, brk - 1)

        # We only treat braces specially when not inside () or []
        if par == 0 and brk == 0 and not in_str:
            if ch == "{":
                # emit everything before '{' as a token, then emit '{'
                # but keep '{' attached to headers like 'for (...) {'
                # by flushing as one token if header exists.
                s = "".join(buf).strip()
                if s.endswith("{"):
                    out.append(s)
                    buf.clear()
                else:
                    flush()
                    out.append("{")
            elif ch == "}":
                flush()
                out.append("}")
            elif ch == ";":
                flush()

    flush()
    return out


# def split_statements(block_src: str) -> List[str]:
#     """
#     Split block source into statements by semicolons, but ignore semicolons inside
#     parentheses/brackets/braces and strings.
# 
#     Also returns braces/for statements as standalone tokens when possible.
#     """
#     stmts: List[str] = []
#     buf: List[str] = []
# 
#     par = brk = brc = 0
#     in_str = False
#     esc = False
# 
#     for ch in block_src:
#         buf.append(ch)
# 
#         if in_str:
#             if esc:
#                 esc = False
#             elif ch == "\\":
#                 esc = True
#             elif ch == '"':
#                 in_str = False
#             continue
# 
#         if ch == '"':
#             in_str = True
#             continue
# 
#         if ch == "(":
#             par += 1
#         elif ch == ")":
#             par = max(0, par - 1)
#         elif ch == "[":
#             brk += 1
#         elif ch == "]":
#             brk = max(0, brk - 1)
#         elif ch == "{":
#             brc += 1
#         elif ch == "}":
#             brc = max(0, brc - 1)
# 
#         if ch == ";" and par == 0 and brk == 0 and brc == 0:
#             stmt = "".join(buf).strip()
#             if stmt:
#                 stmts.append(stmt)
#             buf = []
# 
#     tail = "".join(buf).strip()
#     if tail:
#         stmts.append(tail)
# 
#     return stmts


# ----------------------------
# Symbol table: declarations
# ----------------------------

BLOCK_KIND = {
    "data": "data",
    "transformed data": "transformed data",
    "parameters": "parameters",
    "transformed parameters": "transformed parameters",
    "model": "model",
    "generated quantities": "generated quantities",
}

@dataclass(frozen=True)
class VarInfo:
    name: str
    base_type: str
    dims: Tuple[str, ...] = field(default_factory=tuple)
    block: str = "unknown"


# Regex bits for declarations
# Covers: constraints <lower=...> etc, qualifiers not handled deeply.
_CONSTRAINT = r"(?:<[^>]*>)?"
_WS = r"\s+"

# new syntax examples:
#   array[N] int X;
#   array[N, M] real y;
#   array[N] vector[K] beta; (we treat base_type "vector" dims add K and array dims)
#
# old syntax examples:
#   int X[N];
#   vector[K] beta;
#   matrix[N, K] A;
#
# We'll normalize to: base_type in {int, real, vector, matrix, array?} and dims tuple of strings.

_DECL_NEW_ARRAY = re.compile(
    r"^\s*array\s*\[(?P<adims>[^\]]+)\]\s*(?P<type>(?:int|real|vector|matrix)\b(?:\s*<[^>]*>)?(?:\s*\[[^\]]+\])?)\s+(?P<name>\w+)\s*;",
    flags=re.IGNORECASE
)

# For vector/matrix dims in type (e.g. vector[K], matrix[N,K])
_TYPE_WITH_DIMS = re.compile(r"^(?P<bt>int|real|vector|matrix)\b\s*(?P<const><[^>]*>)?\s*(?P<tdims>\[[^\]]+\])?\s*$", flags=re.IGNORECASE)

_DECL_OLD = re.compile(
    r"^\s*(?P<type>(?:int|real|vector|matrix)\b(?:\s*<[^>]*>)?(?:\s*\[[^\]]+\])?)\s+(?P<name>\w+)\s*(?P<vdims>\[[^\]]+\])?\s*;",
    flags=re.IGNORECASE
)

def _parse_dims(dim_text: Optional[str]) -> Tuple[str, ...]:
    if not dim_text:
        return tuple()
    # dim_text includes brackets like "[N, K]" or "[N]"
    inner = dim_text.strip()[1:-1].strip()
    if not inner:
        return tuple()
    parts = [p.strip() for p in inner.split(",")]
    return tuple(p for p in parts if p)

def _normalize_type(type_text: str) -> Tuple[str, Tuple[str, ...]]:
    """
    Returns (base_type, type_dims)
    type_text can include constraints and dims: "vector[K]" or "real<lower=0>"
    """
    m = _TYPE_WITH_DIMS.match(type_text.strip())
    if not m:
        # fallback
        return (type_text.strip(), tuple())
    bt = m.group("bt").lower()
    tdims = _parse_dims(m.group("tdims"))
    return bt, tdims

def extract_declarations(block_src: str, block_name: str) -> Dict[str, VarInfo]:
    """
    Extract variable declarations from a block.
    We only consider declarations ending with semicolon.
    """
    infos: Dict[str, VarInfo] = {}
    for stmt in split_statements(block_src):
        s = stmt.strip()
        if not s.endswith(";"):
            continue

        # new array syntax
        m = _DECL_NEW_ARRAY.match(s)
        if m:
            adims = _parse_dims("[" + m.group("adims") + "]")
            bt, tdims = _normalize_type(m.group("type"))
            name = m.group("name")
            dims = adims + tdims
            infos[name] = VarInfo(name=name, base_type=bt, dims=dims, block=BLOCK_KIND.get(block_name, block_name))
            continue

        # old syntax (also catches vector/matrix)
        m = _DECL_OLD.match(s)
        if m:
            bt, tdims = _normalize_type(m.group("type"))
            name = m.group("name")
            vdims = _parse_dims(m.group("vdims"))
            dims = tdims + vdims
            # exclude obvious non-declarations (like function calls) by requiring known base types
            if bt in {"int", "real", "vector", "matrix"}:
                infos[name] = VarInfo(name=name, base_type=bt, dims=dims, block=BLOCK_KIND.get(block_name, block_name))
            continue

    return infos


# ----------------------------
# Expression dependency extraction
# ----------------------------

_IDENT = re.compile(r"\b[A-Za-z_]\w*\b")

STAN_KEYWORDS = {
    "for", "in", "if", "else", "while", "break", "continue", "return",
    "target", "print", "reject", "increment_log_prob",
    "int", "real", "vector", "matrix", "array",
    "lower", "upper", "simplex", "ordered", "positive_ordered",
    "cholesky_factor_corr", "cholesky_factor_cov", "corr_matrix", "cov_matrix",
    "row_vector",
    "true", "false",
}

# A small list of common Stan functions to avoid treating them as deps
# (we still keep their arguments in labels; we just don't want edges to them)
STAN_FUNCTIONS = {
    "log", "exp", "logit", "inv_logit", "sqrt", "fabs", "abs",
    "mean", "sd", "variance", "sum", "prod", "min", "max",
    "dot_product", "rows_dot_product", "columns_dot_product",
    "diag_pre_multiply", "diag_post_multiply",
    "append_row", "append_col",
    "rep_vector", "rep_matrix", "rep_array",
    "to_vector", "to_matrix", "to_array_1d", "to_array_2d",
}

def shorten_expr_preserve_args(expr: str, max_len: int) -> str:
    """
    Shorten expression to <= max_len characters, but try to preserve the outer function call
    with arguments (balanced parentheses), or at least keep informative start.
    """
    expr = expr.strip()
    if max_len <= 0 or len(expr) <= max_len:
        return expr

    # Prefer to keep something like f(....) if it starts with identifier + '('
    m = re.match(r"^([A-Za-z_]\w*)\s*\(", expr)
    if m:
        fn = m.group(1)
        # attempt to capture balanced parens for the outer call
        i = expr.find("(")
        depth = 0
        end = None
        for j in range(i, len(expr)):
            if expr[j] == "(":
                depth += 1
            elif expr[j] == ")":
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break
        if end is not None:
            outer = expr[:end]
            if len(outer) <= max_len:
                return outer
            # shrink inside
            head = f"{fn}("
            tail = ")"
            inside_budget = max_len - len(head) - len(tail) - 3
            inside = expr[i + 1:end - 1].strip()
            if inside_budget > 0:
                return head + inside[:inside_budget].rstrip() + "..." + tail

    # fallback: hard truncate
    return expr[: max_len - 3].rstrip() + "..."


def extract_dependencies_from_expr(expr: str, global_symbols: Set[str], locals_scoped: Set[str]) -> Set[str]:
    """
    Extract identifier dependencies from an expression, excluding keywords, functions,
    and local scoped variables (e.g. loop indices).
    """
    deps: Set[str] = set()
    for ident in _IDENT.findall(expr):
        if ident in locals_scoped:
            continue
        if ident in STAN_KEYWORDS:
            continue
        if ident in STAN_FUNCTIONS:
            continue
        if ident in global_symbols:
            deps.add(ident)
    return deps


# ----------------------------
# Statement parsing (lightweight)
# ----------------------------

_ASSIGN_RE = re.compile(r"^\s*(?P<lhs>[A-Za-z_]\w*(?:\s*\[[^\]]+\]\s*)*)\s*=\s*(?P<rhs>.+)\s*;\s*$", flags=re.DOTALL)
_SAMPLE_RE = re.compile(r"^\s*(?P<lhs>[A-Za-z_]\w*(?:\s*\[[^\]]+\]\s*)*)\s*~\s*(?P<dist>[A-Za-z_]\w*)\s*(?P<args>\(.*\))\s*;\s*$", flags=re.DOTALL)
_TARGET_RE = re.compile(r"^\s*target\s*\+\=\s*(?P<rhs>.+)\s*;\s*$", flags=re.DOTALL)

_FOR_HEADER_RE = re.compile(r"^\s*for\s*\(\s*(?P<idx>[A-Za-z_]\w*)\s+in\s+(?P<range>.+?)\s*\)\s*\{\s*$")
_BLOCK_CLOSE_RE = re.compile(r"^\s*\}\s*$")

def _strip_indices(lhs: str) -> str:
    # Turn "x[i, j]" -> "x"
    return re.sub(r"\s*\[[^\]]+\]\s*", "", lhs).strip()

def _collect_indices(lhs: str) -> List[str]:
    # Return index tokens used in the lhs brackets (best-effort)
    inds: List[str] = []
    for m in re.finditer(r"\[([^\]]+)\]", lhs):
        inner = m.group(1)
        # split by comma, then pull identifiers
        for part in inner.split(","):
            part = part.strip()
            for ident in _IDENT.findall(part):
                inds.append(ident)
    return inds

@dataclass
class NodeDetails:
    relation: str            # "=" or "~" or "target+="
    expression: str          # rhs or dist(args)
    dependencies: Set[str]   # global deps
    block: str               # block name
    indices: Tuple[str, ...] = field(default_factory=tuple)  # index names on lhs (best-effort)


def parse_block_dependencies(
    block_name: str,
    block_src: str,
    symbols: Dict[str, VarInfo],
) -> Dict[str, NodeDetails]:
    """
    Parse a block and return node details for assignments/sampling/target increments.
    Tracks scoped loop indices to avoid spurious deps and for plate annotations.
    """
    global_names = set(symbols.keys())
    nodes: Dict[str, NodeDetails] = {}

    # We do a simple line-based brace tracker to support loop-index scoping.
    # We'll scan by lines for `{` and `}` boundaries, but parse statements with split_statements
    # while also tracking "for (...) {" lines.
    locals_stack: List[Set[str]] = [set()]
    loop_index_stack: List[str] = []

    # Pre-scan by lines to update scope stacks, but parse actual statements from statement splitter.
    # We'll create a quick map from "statement index" -> locals scope snapshot by walking the source charwise.
    # Simpler: iterate statements; update scope if statement looks like for-header or "}" alone.
    stmts = split_statements(block_src)
    for stmt in stmts:
        raw = stmt.strip()

        # scope open: for (...) {
        m_for = _FOR_HEADER_RE.match(raw)
        if m_for:
            idx = m_for.group("idx")
            # push a new scope that contains this loop index
            new_scope = set(locals_stack[-1])
            new_scope.add(idx)
            locals_stack.append(new_scope)
            loop_index_stack.append(idx)
            continue

        # scope close: a statement that's just "}" (happens when braces fall on their own statement)
        if _BLOCK_CLOSE_RE.match(raw):
            if len(locals_stack) > 1:
                locals_stack.pop()
            if loop_index_stack:
                loop_index_stack.pop()
            continue

        locals_scoped = locals_stack[-1]

        # Sampling statement
        m = _SAMPLE_RE.match(raw)
        if m:
            lhs = m.group("lhs")
            var = _strip_indices(lhs)
            dist = m.group("dist")
            args = m.group("args").strip()
            expr = f"{dist}{args}"
            deps = extract_dependencies_from_expr(args, global_names, locals_scoped)
            # also include deps in lhs indices? (plate awareness handled separately)
            indices = tuple(i for i in _collect_indices(lhs) if i in locals_scoped)
            nodes[var] = NodeDetails(
                relation="~",
                expression=expr,
                dependencies=deps,
                block=BLOCK_KIND.get(block_name, block_name),
                indices=indices,
            )
            continue

        # Assignment
        m = _ASSIGN_RE.match(raw)
        if m:
            lhs = m.group("lhs")
            rhs = m.group("rhs").strip()
            var = _strip_indices(lhs)
            deps = extract_dependencies_from_expr(rhs, global_names, locals_scoped)
            indices = tuple(i for i in _collect_indices(lhs) if i in locals_scoped)
            nodes[var] = NodeDetails(
                relation="=",
                expression=rhs,
                dependencies=deps,
                block=BLOCK_KIND.get(block_name, block_name),
                indices=indices,
            )
            continue

        # target += ...
        m = _TARGET_RE.match(raw)
        if m:
            rhs = m.group("rhs").strip()
            deps = extract_dependencies_from_expr(rhs, global_names, locals_scoped)
            # attach to a pseudo-node "target"
            # (keeps information without inventing a data/param variable)
            cur = nodes.get("target")
            if cur is None:
                nodes["target"] = NodeDetails(
                    relation="target+=",
                    expression=rhs,
                    dependencies=deps,
                    block=BLOCK_KIND.get(block_name, block_name),
                    indices=tuple(loop_index_stack),
                )
            else:
                # merge multiple target increments
                nodes["target"] = NodeDetails(
                    relation="target+=",
                    expression=cur.expression + " + " + rhs,
                    dependencies=cur.dependencies | deps,
                    block=cur.block,
                    indices=tuple(set(cur.indices) | set(loop_index_stack)),
                )
            continue

        # Could add more patterns here (e.g. `foo = bar ? baz : qux;` already covered by assignment)

    return nodes


# ----------------------------
# Graph building / squish
# ----------------------------

def build_symbol_table(blocks: Dict[str, str]) -> Dict[str, VarInfo]:
    symbols: Dict[str, VarInfo] = {}
    for block_name, src in blocks.items():
        decls = extract_declarations(src, block_name)
        # last declaration wins (rare but possible); keep first if you prefer
        symbols.update(decls)
    return symbols


def build_dependency_tree(blocks: Dict[str, str], verbose: bool = False) -> Tuple[Dict[str, NodeDetails], Dict[str, VarInfo]]:
    symbols = build_symbol_table(blocks)
    if verbose:
        print("Symbols:")
        for k in sorted(symbols):
            v = symbols[k]
            print(f"  {v.name}: {v.base_type} dims={list(v.dims)} block={v.block}")
        print("--" * 20)

    nodes: Dict[str, NodeDetails] = {}
    for block_name, src in blocks.items():
        parsed = parse_block_dependencies(block_name, src, symbols)
        if verbose and parsed:
            print(f"Block: {block_name}")
            for var, det in parsed.items():
                print(f"  {var} {det.relation} {det.expression}")
                print(f"    deps={sorted(det.dependencies)} indices={det.indices} block={det.block}")
            print("--" * 20)
        nodes.update(parsed)

    return nodes, symbols


def squish_out_variable(nodes: Dict[str, NodeDetails], var_to_eliminate: str) -> Dict[str, NodeDetails]:
    if var_to_eliminate not in nodes:
        raise ValueError(f"Variable '{var_to_eliminate}' not found in dependency tree.")
    inherited = nodes[var_to_eliminate].dependencies

    new_nodes: Dict[str, NodeDetails] = {}
    for var, det in nodes.items():
        if var == var_to_eliminate:
            continue
        deps = set(det.dependencies)
        if var_to_eliminate in deps:
            deps.remove(var_to_eliminate)
            deps |= inherited
        new_nodes[var] = NodeDetails(
            relation=det.relation,
            expression=det.expression,
            dependencies=deps,
            block=det.block,
            indices=det.indices,
        )
    return new_nodes


# ----------------------------
# Labels: greek + shapes + expr display
# ----------------------------

GREEK_MAP = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "iota": "ι",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "upsilon": "υ",
    "phi": "φ",
    "chi": "χ",
    "psi": "ψ",
    "omega": "ω",
}

def load_label_mappings(label_file: str) -> Dict[str, str]:
    label_mappings: Dict[str, str] = {}
    with open(label_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            original, new_label = line.split(None, 1)
            label_mappings[original] = new_label.strip()
    return label_mappings


def format_var_label(
    var: str,
    symbols: Dict[str, VarInfo],
    label_mappings: Dict[str, str],
    greek: bool,
    show_shape: bool,
) -> str:
    base = label_mappings.get(var, var)
    if greek and base in GREEK_MAP:
        base = GREEK_MAP[base]

    if show_shape and var in symbols:
        dims = symbols[var].dims
        if dims:
            base = f"{base}[{', '.join(dims)}]"
    return base


def node_shape_for_block(block: str) -> str:
    # you can tweak these
    if block in {"data", "transformed data"}:
        return "box"
    if block in {"parameters", "transformed parameters"}:
        return "ellipse"
    if block in {"generated quantities"}:
        return "diamond"
    if block == "model":
        return "circle"
    if block == "unknown":
        return "circle"
    return "circle"


# ----------------------------
# Rendering
# ----------------------------

def render_dependency_tree(
    nodes: Dict[str, NodeDetails],
    symbols: Dict[str, VarInfo],
    label_mappings: Dict[str, str],
    explicit: bool,
    shorten_expr: int,
    greek: bool,
    show_shape: bool,
    show_edge_indices: bool,
) -> graphviz.Digraph:
    dot = graphviz.Digraph(graph_attr={"splines": "false"})
    added: Set[str] = set()

    def render_node(var: str):
        if var in added:
            return
        det = nodes.get(var)
        block = det.block if det else (symbols.get(var).block if var in symbols else "unknown")

        var_label = format_var_label(var, symbols, label_mappings, greek=greek, show_shape=show_shape)

        if det is None:
            # declared but no statement parsed, or purely dependency-only
            dot.node(var, label=var_label, shape=node_shape_for_block(block))
            added.add(var)
            return

        expr = det.expression if explicit else shorten_expr_preserve_args(det.expression, shorten_expr)
        relation = det.relation

        spacer = "\n" if relation in {"~", "target+="} else " "
        label = f"{var_label}{spacer}{relation}{spacer}{expr}"

        dot.node(var, label=label, shape=node_shape_for_block(block))
        added.add(var)

    # ensure all declared vars are at least present if they appear in deps
    all_vars = set(nodes.keys())
    for det in nodes.values():
        all_vars |= set(det.dependencies)

    def render_rec(var: str):
        render_node(var)
        det = nodes.get(var)
        if not det:
            return
        for dep in sorted(det.dependencies):
            render_node(dep)
            if show_edge_indices and det.indices:
                dot.edge(dep, var, label=",".join(det.indices))
            else:
                dot.edge(dep, var)

    for v in sorted(all_vars):
        render_rec(v)

    return dot


# ----------------------------
# Main
# ----------------------------

def parse_stan_file(file_path: str, verbose: bool = False) -> Tuple[Dict[str, NodeDetails], Dict[str, VarInfo]]:
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = remove_comments(content)
    blocks = find_all_blocks(content)
    return build_dependency_tree(blocks, verbose=verbose)


def parse_stan_string(stan_code: str, verbose: bool = False):
    content = remove_comments(stan_code)
    blocks = find_all_blocks(content)
    return build_dependency_tree(blocks, verbose=verbose)


def main():
    p = argparse.ArgumentParser(description="Visualize a Stan model dependency graph.")
    p.add_argument("stan_file", type=str, help="Path to Stan model file")
    p.add_argument("-o", "--output", type=str, default="dependencies", help="Base name for output files")
    p.add_argument("-l", "--labels", type=str, help="Path to label mapping file (two columns: original label)")
    p.add_argument("-s", "--squish", nargs="*", type=str, help="Variable(s) to squish out")
    p.add_argument("-e", "--explicit", action="store_true", help="Show full expressions (no shortening)")
    p.add_argument("--format", choices=["svg", "png", "pdf"], default="svg", help="Output format (default: svg)")
    p.add_argument("--shorten-expr", type=int, default=60, help="Max expression length when not --explicit")
    p.add_argument("--greek", action="store_true", help="Relabel common greek-named vars (alpha->α) for display")
    p.add_argument("--show-shape", action="store_true", help="Append declared shapes like beta[K] to labels")
    p.add_argument("--edge-indices", action="store_true", help="Label edges with loop indices (plate hints)")
    p.add_argument("--cleanup", action="store_true", help="Remove generated files after creation")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose parsing output")

    args = p.parse_args()

    nodes, symbols = parse_stan_file(args.stan_file, verbose=args.verbose)

    label_mappings = load_label_mappings(args.labels) if args.labels else {}

    if args.squish:
        for v in args.squish:
            nodes = squish_out_variable(nodes, v)

    dot = render_dependency_tree(
        nodes=nodes,
        symbols=symbols,
        label_mappings=label_mappings,
        explicit=args.explicit,
        shorten_expr=args.shorten_expr,
        greek=args.greek,
        show_shape=args.show_shape,
        show_edge_indices=args.edge_indices,
    )

    dot_path = f"{args.output}.dot"
    dot.save(dot_path)
    dot.render(args.output, format=args.format, cleanup=True)
    output_file = f"{args.output}.{args.format}"

    print(f"Wrote: {dot_path} and {output_file}")

    if args.cleanup:
        try:
            os.remove(dot_path)
            os.remove(output_file)
            print("Cleaned up generated files.")
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    main()

