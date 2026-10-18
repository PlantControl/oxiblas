#!/usr/bin/env python3
"""Trace calls among Rust free functions and impl methods in a crate source tree."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path


IDENT = r"[A-Za-z_]\w*"
TURBOFISH = r"(?:\s*::\s*<[^(){};]*>)?"
FN_RE = re.compile(rf"\bfn\s+({IDENT})")
IMPL_RE = re.compile(r"\bimpl\b")
PATH_CALL_RE = re.compile(rf"\b({IDENT})(?:\s*<[^(){{}};]*>)?\s*::\s*({IDENT}){TURBOFISH}\s*\(")
METHOD_CALL_RE = re.compile(rf"(\bself\s*)?\.\s*({IDENT}){TURBOFISH}\s*\(")
BARE_CALL_RE = re.compile(rf"(?<![\w.:])({IDENT}){TURBOFISH}\s*\(")
KEYWORDS = {
    "if", "while", "for", "match", "loop", "return", "fn", "let", "in", "as",
    "move", "unsafe", "Some", "Ok", "Err", "Box", "Vec", "impl", "where",
}


@dataclass(frozen=True)
class Func:
    key: str
    name: str
    owner: str | None
    path: Path
    line: int
    body: str


@dataclass(frozen=True)
class Edge:
    target: str | None
    label: str
    by_name: bool = False


def mask_noncode(text: str) -> str:
    """Blank comments and literals, preserving offsets and newlines.

    A quote starts a char literal only if it closes within a char or escape;
    otherwise it is a lifetime and is left alone.
    """
    out = list(text)
    n = len(text)

    def blank(i: int, j: int) -> None:
        for k in range(i, min(n, j)):
            if out[k] != "\n":
                out[k] = " "

    i = 0
    while i < n:
        if text.startswith("//", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
        elif text.startswith("/*", i):
            depth, j = 0, i
            while j < n:
                if text.startswith("/*", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("*/", j):
                    depth, j = depth - 1, j + 2
                    if depth == 0:
                        break
                else:
                    j += 1
            blank(i, j)
            i = j
        elif (m := re.match(r'b?r(#*)"', text[i:i + 260])) and (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_")):
            close = '"' + m.group(1)
            j = text.find(close, i + m.end())
            j = n if j < 0 else j + len(close)
            blank(i, j)
            i = j
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            blank(i, j + 1)
            i = j + 1
        elif text[i] == "'":
            m = re.match(r"'(?:\\(?:u\{[0-9A-Fa-f]+\}|x[0-9A-Fa-f]{2}|.)|[^\\'\n])'", text[i:i + 16])
            if m:
                blank(i, i + m.end())
                i += m.end()
            else:
                i += 1
        else:
            i += 1
    return "".join(out)


def matching(masked: str, start: int, open_c: str = "{", close_c: str = "}") -> int:
    depth = 0
    for i in range(start, len(masked)):
        if masked[i] == open_c:
            depth += 1
        elif masked[i] == close_c:
            depth -= 1
            if depth == 0:
                return i
    raise ValueError(f"unmatched {open_c!r} at offset {start}")


def skip_generics(masked: str, i: int) -> int:
    while i < len(masked) and masked[i].isspace():
        i += 1
    if i < len(masked) and masked[i] == "<":
        depth = 0
        while i < len(masked):
            if masked[i] == "<":
                depth += 1
            elif masked[i] == ">" and masked[i - 1] != "-":
                depth -= 1
                if depth == 0:
                    return i + 1
            i += 1
    return i


def impl_blocks(masked: str) -> list[tuple[int, int, str]]:
    blocks = []
    for m in IMPL_RE.finditer(masked):
        head_start = skip_generics(masked, m.end())
        brace = masked.find("{", head_start)
        if brace < 0:
            continue
        head = masked[head_start:brace]
        head = re.split(r"\bwhere\b", head)[0]
        if re.search(r"\bfor\b", head):
            head = re.split(r"\bfor\b", head)[-1]
        head = re.sub(r"<.*", "", head.strip(), flags=re.S)
        names = re.findall(IDENT, head)
        if names:
            blocks.append((brace, matching(masked, brace), names[-1]))
    return blocks


def fn_body_start(masked: str, i: int) -> int | None:
    depth = 0
    while i < len(masked):
        c = masked[i]
        if c in "([":
            depth += 1
        elif c in ")]":
            depth -= 1
        elif depth == 0 and c == ";":
            return None
        elif depth == 0 and c == "{":
            return i
        i += 1
    return None


def load_funcs(source_dir: Path) -> dict[str, Func]:
    funcs: dict[str, Func] = {}
    for path in sorted(source_dir.rglob("*.rs")):
        text = path.read_text(encoding="utf-8")
        masked = mask_noncode(text)
        blocks = impl_blocks(masked)
        rel = path.relative_to(source_dir)
        for m in FN_RE.finditer(masked):
            start = fn_body_start(masked, m.end())
            if start is None:
                continue
            end = matching(masked, start)
            owners = [b for b in blocks if b[0] < m.start() < b[1]]
            owner = min(owners, key=lambda b: b[1] - b[0])[2] if owners else None
            name = m.group(1)
            line = text.count("\n", 0, m.start()) + 1
            base = f"{owner}::{name}" if owner else name
            key = f"{base}@{rel}:{line}"
            funcs[key] = Func(key, name, owner, path, line, masked[start:end + 1])
    return funcs


def build_index(funcs: dict[str, Func]) -> tuple[dict[tuple[str, str], list[str]], dict[str, list[str]], dict[str, list[str]]]:
    by_method: dict[tuple[str, str], list[str]] = {}
    by_free: dict[str, list[str]] = {}
    by_name: dict[str, list[str]] = {}
    for f in funcs.values():
        if f.owner:
            by_method.setdefault((f.owner, f.name), []).append(f.key)
        else:
            by_free.setdefault(f.name, []).append(f.key)
        by_name.setdefault(f.name, []).append(f.key)
    return by_method, by_free, by_name


def pick(cands: list[str], funcs: dict[str, Func], caller: Func, label: str) -> Edge:
    if len(cands) > 1:
        same = [c for c in cands if funcs[c].path == caller.path]
        cands = same or cands
    if len(cands) == 1:
        return Edge(cands[0], label)
    return Edge(None, f"{label} [ambiguous: {', '.join(sorted(cands))}]")


def call_edges(f: Func, funcs: dict[str, Func], index) -> list[Edge]:
    by_method, by_free, by_name = index
    edges: dict[str, Edge] = {}
    body = f.body
    consumed: set[int] = set()

    for m in PATH_CALL_RE.finditer(body):
        qual, name = m.group(1), m.group(2)
        consumed.add(m.start(2))
        owner = f.owner if qual == "Self" else qual
        if owner and (owner, name) in by_method:
            e = pick(by_method[(owner, name)], funcs, f, f"{owner}::{name}")
        elif qual[0].islower() and name in by_free:
            mod = [c for c in by_free[name] if funcs[c].path.stem == qual or funcs[c].path.parent.name == qual]
            e = pick(mod or by_free[name], funcs, f, f"{qual}::{name}")
        else:
            continue
        edges.setdefault(e.target or e.label, e)

    for m in METHOD_CALL_RE.finditer(body):
        name = m.group(2)
        consumed.add(m.start(2))
        if m.group(1) and f.owner and (f.owner, name) in by_method:
            e = pick(by_method[(f.owner, name)], funcs, f, f"self.{name}")
        else:
            cands = [k for k in by_name.get(name, []) if funcs[k].owner]
            if not cands:
                continue
            e = pick(cands, funcs, f, f".{name}")
            e = Edge(e.target, e.label, by_name=True)
        edges.setdefault(e.target or e.label, e)

    for m in BARE_CALL_RE.finditer(body):
        name = m.group(1)
        if m.start(1) in consumed or name in KEYWORDS or name not in by_free:
            continue
        if body[m.end(1):].lstrip().startswith("!"):
            continue
        e = pick(by_free[name], funcs, f, name)
        edges.setdefault(e.target or e.label, e)

    return [e for e in edges.values() if e.target != f.key]


def resolve_roots(value: str, funcs: dict[str, Func]) -> list[str]:
    owner, _, name = value.rpartition("::")
    hits = [
        k for k, f in funcs.items()
        if f.name.lower() == name.lower() and (not owner or (f.owner or "").lower() == owner.lower())
    ]
    if not hits:
        raise SystemExit(f"unknown function: {value}")
    return sorted(hits)


def display(f: Func, root: Path) -> str:
    base = f"{f.owner}::{f.name}" if f.owner else f.name
    return f"{base}  {f.path.relative_to(root)}:{f.line}"


def print_tree(key, graph, funcs, root, ambiguous, prefix="", connector="", ancestry=frozenset(), expanded=None, note=""):
    expanded = set() if expanded is None else expanded
    cycle = " [cycle]" if key in ancestry else ""
    repeated = " [already shown]" if key in expanded and not cycle else ""
    print(f"{prefix}{connector}{display(funcs[key], root)}{note}{cycle}{repeated}")
    if cycle or repeated:
        return
    expanded.add(key)
    child_prefix = prefix + ("" if not connector else "    " if connector == "└── " else "│   ")
    children = [e for e in graph[key] if e.target or ambiguous]
    for i, edge in enumerate(children):
        branch = "└── " if i == len(children) - 1 else "├── "
        if edge.target is None:
            print(f"{child_prefix}{branch}?? {edge.label}")
        else:
            note = " [receiver unresolved; matched by name]" if edge.by_name else ""
            print_tree(edge.target, graph, funcs, root, ambiguous, child_prefix, branch, ancestry | {key}, expanded, note)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace transitive calls among Rust functions.")
    parser.add_argument("repo", type=Path, help="repository root")
    parser.add_argument("routines", nargs="+", help="entry points, such as Qz::compute or hessenberg_qz")
    parser.add_argument(
        "--source-dir",
        action="append",
        help="source directory relative to the repository root (repeatable; default crates/oxiblas-lapack/src)",
    )
    parser.add_argument(
        "--show-ambiguous",
        action="store_true",
        help="list method calls whose receiver type matches several definitions",
    )
    args = parser.parse_args()

    repo = args.repo.resolve()
    funcs: dict[str, Func] = {}
    for rel in args.source_dir or ["crates/oxiblas-lapack/src"]:
        source_dir = repo / rel
        if not source_dir.is_dir():
            raise SystemExit(f"source directory does not exist: {source_dir}")
        funcs.update(load_funcs(source_dir))
    index = build_index(funcs)
    graph = {k: call_edges(f, funcs, index) for k, f in funcs.items()}
    first = True
    for value in args.routines:
        for key in resolve_roots(value, funcs):
            if not first:
                print()
            first = False
            print_tree(key, graph, funcs, repo, args.show_ambiguous)


if __name__ == "__main__":
    main()
