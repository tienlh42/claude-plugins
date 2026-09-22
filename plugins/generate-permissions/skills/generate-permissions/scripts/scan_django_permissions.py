#!/usr/bin/env python3
"""
Quet tinh (khong import Django) mot repo Django backend BAT KY de liet ke
endpoint (class-based view), method, va api_pattern - phuc vu tao du lieu
Permission ma khong can go tay CSV.

Moi lan chay chi phuc vu DUNG 1 repo. Muon quet nhieu backend thi chay
nhieu lan, moi lan 1 repo root khac nhau.

Usage:
    python scan_django_permissions.py REPO_ROOT
        [--gate-class NAME [--gate-class NAME ...]]
        [--api-pattern-style {inline-kwargs,tail-kwargs}]
        [--service NAME]
        [--project-package DIR]
        [--methods get,post,put,patch,delete]
        [--include-unrouted]
        [--out FILE]

Xem SKILL.md cung thu muc de biet cach chon --gate-class / --api-pattern-style
cho 1 repo lay - day KHONG phai gia tri tu suy dien duoc, phai tu doc code
gate class cua repo do truoc.
"""
import argparse
import csv
import os
import re
import sys

EXCLUDE_DIRS = {
    ".git", ".hg", ".svn", "node_modules", ".venv", "venv", "env",
    "__pycache__", "site-packages", ".tox", ".mypy_cache", ".pytest_cache",
    "build", "dist", "migrations", "static", "media",
}
DEFAULT_METHODS = ("get", "post", "put", "patch", "delete")
MAX_INCLUDE_DEPTH = 12


def strip_leading_module_docstring(source):
    """Bo docstring dau file (Django hay tu sinh vd path('', Home.as_view())
    trong docstring cua urls.py mau) de khong bi hieu lam la code thuc."""
    m = re.match(r"^(\s*)(\"\"\"|''')", source)
    if not m:
        return source
    quote = m.group(2)
    start = m.end()
    end = source.find(quote, start)
    if end == -1:
        return source
    return source[:m.start(2)] + source[end + len(quote):]


def read_source(path, file_cache):
    if path not in file_cache:
        with open(path, encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        file_cache[path] = strip_leading_module_docstring(raw)
    return file_cache[path]


def warn(msg):
    print(f"[WARN] {msg}", file=sys.stderr)


def info(msg):
    print(f"[INFO] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------
# Balanced-paren call scanning (khong dung ast, vi urls.py co the co cu phap
# ma ast khong can thiet phai xu ly dung 100% - regex + balanced-paren la du
# va don gian hon nhieu so voi viet 1 python parser day du).
# --------------------------------------------------------------------------

def find_matching_paren(s, open_idx):
    depth = 0
    in_str = None
    i = open_idx
    n = len(s)
    while i < n:
        c = s[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == in_str:
                in_str = None
        else:
            if c in ("'", '"'):
                in_str = c
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return i
        i += 1
    return -1


def iter_calls(source, names):
    """Yield (name, call_start_idx, args_str) for every top-level call to
    one of `names` found anywhere in source (balanced-paren aware)."""
    pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\s*\(")
    for m in pattern.finditer(source):
        open_idx = m.end() - 1
        close_idx = find_matching_paren(source, open_idx)
        if close_idx == -1:
            continue
        yield m.group(1), m.start(), source[open_idx + 1:close_idx]


STRING_LITERAL_RE = re.compile(r"""^\s*r?(["'])((?:\\.|(?!\1).)*)\1""", re.DOTALL)


def leading_string_literal(args):
    m = STRING_LITERAL_RE.match(args)
    if not m:
        return None, None
    return m.group(2), m.end()


NAME_KWARG_RE = re.compile(r"""\bname\s*=\s*(["'])((?:\\.|(?!\1).)*)\1""")
AS_VIEW_RE = re.compile(r"""([\w.]+)\.as_view\(\s*\)""")
KWARG_SEGMENT_RE = re.compile(r"<(?:\w+:)?(\w+)>")


def parse_path_call(args):
    """Parse the args of a path()/re_path() call.
    Returns one of:
      ("include", route, include_module_spec) or
      ("view", route, qual_or_none, view_name, url_name) or
      (None, None, None) if not recognized (skip silently).
    """
    route, after = leading_string_literal(args)
    if route is None:
        return (None, None, None)
    remainder = args[after:]

    inc_m = re.search(r"\binclude\s*\(", remainder)
    if inc_m:
        inc_open = inc_m.end() - 1
        inc_close = find_matching_paren(remainder, inc_open)
        inc_args = remainder[inc_open + 1:inc_close] if inc_close != -1 else ""
        mod_spec, _ = leading_string_literal(inc_args.lstrip("("))
        if mod_spec is None:
            # co the la tuple form include(("mod.urls", "app_name"))
            m2 = re.search(r"""(["'])((?:\\.|(?!\1).)*)\1""", inc_args)
            mod_spec = m2.group(2) if m2 else None
        return ("include", route, mod_spec)

    av_m = AS_VIEW_RE.search(remainder)
    if av_m:
        dotted = av_m.group(1)
        if "." in dotted:
            qual, view_name = dotted.rsplit(".", 1)
        else:
            qual, view_name = None, dotted
        name_m = NAME_KWARG_RE.search(remainder)
        url_name = name_m.group(2) if name_m else None
        return ("view", route, (qual, view_name, url_name))

    return (None, None, None)


# --------------------------------------------------------------------------
# Module index: map dotted module path -> file, de resolve import.
# --------------------------------------------------------------------------

def build_module_index(repo_root):
    module_index = {}    # "feedback.modules.get_feedback" -> abs file path
    package_index = {}   # "feedback.modules" -> abs dir path

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            stem = fn[:-3]
            parts = [] if stem == "__init__" else [stem]
            cur = dirpath
            while os.path.isfile(os.path.join(cur, "__init__.py")):
                parts.insert(0, os.path.basename(cur))
                parent = os.path.dirname(cur)
                if parent == cur:
                    break
                cur = parent
            if not parts:
                continue
            fqn = ".".join(parts)
            module_index[fqn] = full
            if stem == "__init__":
                package_index[fqn] = dirpath
    return module_index, package_index


def resolve_module(spec, module_index, package_index, repo_root):
    if not spec:
        return None
    if spec in module_index:
        return module_index[spec]
    if spec in package_index:
        return os.path.join(package_index[spec], "__init__.py")
    # suffix fallback: repo khong co __init__.py (namespace package)
    suffix = spec.replace(".", os.sep)
    candidates = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        cand = os.path.join(dirpath, suffix + ".py")
        if os.path.isfile(cand):
            candidates.append(cand)
        cand_init = os.path.join(dirpath, suffix, "__init__.py")
        if os.path.isfile(cand_init):
            candidates.append(cand_init)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        warn(f"module '{spec}' mo ho ({len(candidates)} noi khop), bo qua")
    return None


# --------------------------------------------------------------------------
# Import parsing trong 1 file urls.py, de biet view class nam o file nao.
# --------------------------------------------------------------------------

FROM_IMPORT_RE = re.compile(
    r"^\s*from\s+(\.*)([\w.]*)\s+import\s+(.+?)(?=\n(?:\S|\Z)|\Z)",
    re.MULTILINE | re.DOTALL,
)
IMPORT_RE = re.compile(r"^\s*import\s+([\w.]+)(?:\s+as\s+(\w+))?\s*$", re.MULTILINE)


def join_logical_import_block(src):
    """Django urls.py thuong viet from X import (\n A,\n B,\n) nhieu dong -
    gop cac dong bi ngat trong () lai thanh 1 dong logic truoc khi regex."""
    out = []
    depth = 0
    for line in src.splitlines():
        out.append(line)
        depth += line.count("(") - line.count(")")
    # danh dau cac dong dang o giua 1 block (...) bang cach thay newline
    # ben trong parens bang space - lam bang cach quet ky tu thay vi dong.
    result = []
    depth = 0
    for ch in src:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == "\n" and depth > 0:
            result.append(" ")
        else:
            result.append(ch)
    return "".join(result)


def resolve_relative(dots, tail, cur_pkg):
    if not dots:
        return tail
    pkg_parts = cur_pkg.split(".") if cur_pkg else []
    drop = len(dots) - 1
    base_parts = pkg_parts[:-drop] if drop and drop <= len(pkg_parts) else (pkg_parts if drop == 0 else [])
    base = ".".join(base_parts)
    if tail:
        return f"{base}.{tail}" if base else tail
    return base


def split_import_names(blob):
    blob = blob.strip()
    if blob.startswith("("):
        end = blob.rfind(")")
        blob = blob[1:end] if end != -1 else blob[1:]
    names = []
    for raw in blob.split(","):
        raw = raw.strip()
        if not raw or raw == "*":
            if raw == "*":
                names.append("*")
            continue
        raw = raw.split("#")[0].strip()
        if not raw:
            continue
        m = re.match(r"^([\w]+)(?:\s+as\s+(\w+))?$", raw)
        if m:
            names.append((m.group(1), m.group(2) or m.group(1)))
    return names


def parse_imports(src, cur_pkg, module_index, package_index, repo_root):
    joined = join_logical_import_block(src)
    name_to_module = {}
    module_aliases = {}
    star_modules = []

    for m in FROM_IMPORT_RE.finditer(joined):
        dots, tail, names_blob = m.groups()
        base = resolve_relative(dots, tail, cur_pkg)
        names_blob = names_blob.strip()
        if names_blob.startswith("*"):
            star_modules.append(base)
            continue
        for orig, alias in split_import_names(names_blob):
            candidate = f"{base}.{orig}" if base else orig
            if resolve_module(candidate, module_index, package_index, repo_root):
                module_aliases[alias] = candidate
            else:
                name_to_module[alias] = base

    for m in IMPORT_RE.finditer(joined):
        mod, alias = m.group(1), m.group(2)
        alias = alias or mod.split(".")[0]
        module_aliases[alias] = mod

    return name_to_module, module_aliases, star_modules


# --------------------------------------------------------------------------
# Class body location + inspection
# --------------------------------------------------------------------------

def find_class_block(source, class_name):
    header_re = re.compile(rf"^class\s+{re.escape(class_name)}\b", re.MULTILINE)
    m = header_re.search(source)
    if not m:
        return None
    # tim dau ':' ket thuc header (co the wrap nhieu dong vi base class list dai)
    i = m.end()
    depth = 0
    while i < len(source):
        c = source[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == ":" and depth == 0:
            i += 1
            break
        i += 1
    body_start = i
    next_top = re.search(r"^(class|def|@)\s", source[body_start:], re.MULTILINE)
    body_end = body_start + next_top.start() if next_top else len(source)
    return source[body_start:body_end]


def locate_view_class(qual, view_name, imports, app_dir, cur_pkg, repo_root,
                       module_index, package_index, file_cache):
    name_to_module, module_aliases, star_modules = imports
    candidates = []

    if qual:
        if qual in module_aliases:
            candidates.append(resolve_module(module_aliases[qual], module_index, package_index, repo_root))
        else:
            direct = resolve_module(qual, module_index, package_index, repo_root)
            if direct:
                candidates.append(direct)
            scoped = resolve_module(f"{cur_pkg}.{qual}" if cur_pkg else qual,
                                     module_index, package_index, repo_root)
            if scoped:
                candidates.append(scoped)
    else:
        if view_name in name_to_module:
            candidates.append(resolve_module(name_to_module[view_name], module_index, package_index, repo_root))
        for star_mod in star_modules:
            candidates.append(resolve_module(star_mod, module_index, package_index, repo_root))
        legacy = os.path.join(app_dir, "views.py")
        if os.path.isfile(legacy):
            candidates.append(legacy)

    for f in candidates:
        if not f or not os.path.isfile(f):
            continue
        body = find_class_block(read_source(f, file_cache), view_name)
        if body is not None:
            return f, body

    # deep fallback: tim dinh nghia class nay o bat ky dau trong repo
    hits = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            full = os.path.join(dirpath, fn)
            if re.search(rf"^class\s+{re.escape(view_name)}\b", read_source(full, file_cache), re.MULTILINE):
                hits.append(full)
    if len(hits) == 1:
        return hits[0], find_class_block(read_source(hits[0], file_cache), view_name)
    if len(hits) > 1:
        warn(f"view class '{view_name}' mo ho ({len(hits)} noi dinh nghia), bo qua")
    else:
        warn(f"khong tim thay dinh nghia class '{view_name}'")
    return None, None


GATE_LINE_RE_CACHE = {}


def gate_line_matches(class_body, gate_classes):
    if not gate_classes:
        return True
    for line in class_body.splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped or "permission_classes" not in stripped:
            continue
        for gate in gate_classes:
            key = gate
            pat = GATE_LINE_RE_CACHE.get(key)
            if pat is None:
                pat = re.compile(r"\b" + re.escape(gate) + r"\b")
                GATE_LINE_RE_CACHE[key] = pat
            if pat.search(stripped):
                return True
    return False


def defined_methods(class_body, methods):
    found = []
    for m in methods:
        if re.search(rf"^\s+(?:async\s+)?def\s+{m}\s*\(", class_body, re.MULTILINE):
            found.append(m)
    return found


DOCSTRING_RE = re.compile(r'\s*("""(.*?)"""|\'\'\'(.*?)\'\'\')', re.DOTALL)
METHOD_DOC_RE = re.compile(r"(GET|POST|PUT|PATCH|DELETE):\s*(.*?)(?=(?:GET|POST|PUT|PATCH|DELETE):|\Z)", re.DOTALL)


def class_docstring(class_body):
    m = DOCSTRING_RE.match(class_body)
    if not m:
        return ""
    return " ".join((m.group(2) or m.group(3) or "").split())


def method_docstring(class_body, method):
    m = re.search(rf"^\s+(?:async\s+)?def\s+{method}\s*\([^)]*\)\s*:\s*\n(\s+)(\"\"\"|''')",
                   class_body, re.MULTILINE)
    text = ""
    if m:
        quote = m.group(2)
        start = m.end()
        end = class_body.find(quote, start)
        if end != -1:
            text = " ".join(class_body[start:end].split())
    if text:
        return text
    class_doc = class_docstring(class_body)
    for tag, seg in METHOD_DOC_RE.findall(class_doc):
        if tag == method.upper():
            return " ".join(seg.split()).rstrip(".")
    return ""


# --------------------------------------------------------------------------
# api_pattern
# --------------------------------------------------------------------------

def build_api_pattern_inline(full_route):
    segments = [s for s in full_route.strip("/").split("/") if s]
    out = []
    for seg in segments:
        m = re.fullmatch(r"<(?:\w+:)?(\w+)>", seg)
        out.append(m.group(1) if m else seg)
    return " ".join(out)


def build_api_pattern_tail(full_route, ends_with_slash):
    segments = [s for s in full_route.strip("/").split("/") if s]
    kwarg_names = KWARG_SEGMENT_RE.findall(full_route)
    n = len(kwarg_names)
    if n == 0:
        return " ".join(segments), True
    flags = [bool(re.fullmatch(r"<(?:\w+:)?\w+>", s)) for s in segments]
    if sum(flags) != n or flags[-n:] != [True] * n:
        return None, False
    for idx, key in enumerate(kwarg_names):
        segments[idx - n] = key
    pattern = " ".join(segments).strip()
    if ends_with_slash:
        warn(f"route ket thuc bang '/' co kwarg - tail-kwargs co the sai (bug F7 da biet): {full_route}")
    return pattern, True


# --------------------------------------------------------------------------
# URL tree walk
# --------------------------------------------------------------------------

def find_project_package(repo_root, override):
    if override:
        override = os.path.abspath(override)
        if not os.path.isfile(os.path.join(override, "urls.py")):
            print(f"[ERROR] --project-package '{override}' khong co urls.py", file=sys.stderr)
            sys.exit(1)
        return override

    candidates = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        if "settings.py" in filenames and "urls.py" in filenames:
            candidates.append(dirpath)
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) == 0:
        print("[ERROR] khong tim thay thu muc co ca settings.py va urls.py. "
              "Dung --project-package de chi ro.", file=sys.stderr)
        sys.exit(1)
    print("[ERROR] tim thay nhieu ung vien project package, dung --project-package de chon:", file=sys.stderr)
    for c in candidates:
        print(f"    {c}", file=sys.stderr)
    sys.exit(1)


def app_module_name(app_urls_path, repo_root, module_index):
    for fqn, path in module_index.items():
        if path == app_urls_path:
            return fqn.rsplit(".", 1)[0] if fqn.endswith(".urls") else fqn
    return os.path.basename(os.path.dirname(app_urls_path))


def walk_urls(urls_path, prefix_segments, module_index, package_index, repo_root,
              gate_classes, api_pattern_style, methods, rows, file_cache,
              visited, depth=0):
    if depth > MAX_INCLUDE_DEPTH:
        warn(f"do sau include() vuot qua {MAX_INCLUDE_DEPTH}, dung lai tai {urls_path}")
        return
    key = (urls_path, tuple(prefix_segments))
    if key in visited:
        return
    visited.add(key)

    if not os.path.isfile(urls_path):
        warn(f"khong doc duoc urls.py: {urls_path}")
        return
    src = read_source(urls_path, file_cache)

    app_dir = os.path.dirname(urls_path)
    cur_pkg = app_module_name(urls_path, repo_root, module_index)
    imports = parse_imports(src, cur_pkg, module_index, package_index, repo_root)
    feature = os.path.basename(app_dir)

    for call_name, _, args in iter_calls(src, ("path", "re_path")):
        kind, route, payload = parse_path_call(args)
        if kind is None:
            continue
        route_clean = route.lstrip("^").rstrip("$") if call_name == "re_path" else route

        if kind == "include":
            mod_spec = payload
            if not mod_spec:
                warn(f"khong parse duoc include() trong {urls_path}: {args[:80]!r}")
                continue
            child = resolve_module(mod_spec, module_index, package_index, repo_root)
            if not child:
                warn(f"khong resolve duoc include('{mod_spec}') trong {urls_path}")
                continue
            new_prefix = prefix_segments + [s for s in route_clean.strip("/").split("/") if s]
            walk_urls(child, new_prefix, module_index, package_index, repo_root,
                      gate_classes, api_pattern_style, methods, rows, file_cache,
                      visited, depth + 1)
            continue

        qual, view_name, url_name = payload
        full_route = "/".join(prefix_segments + [s for s in route_clean.strip("/").split("/") if s])
        src_file, body = locate_view_class(qual, view_name, imports, app_dir, cur_pkg,
                                            repo_root, module_index, package_index, file_cache)
        if body is None:
            continue
        if not gate_line_matches(body, gate_classes):
            continue

        ends_with_slash = route_clean.endswith("/")
        if api_pattern_style == "tail-kwargs":
            api_pattern, ok = build_api_pattern_tail(full_route, ends_with_slash)
            if not ok:
                warn(f"bo qua route (kwarg khong nam cuoi path, tail-kwargs khong khop duoc): {full_route}")
                continue
        else:
            api_pattern = build_api_pattern_inline(full_route)

        class_doc = class_docstring(body)
        rel_src = os.path.relpath(src_file, repo_root)
        for method in defined_methods(body, methods):
            rows.append({
                "service": None,  # dien o main()
                "feature": feature,
                "url_name": url_name or "",
                "view_class": view_name,
                "method": method.upper(),
                "api_pattern": api_pattern,
                "route": "/" + full_route,
                "source_file": rel_src,
                "class_doc": class_doc,
                "method_doc": method_docstring(body, method),
            })


def find_unrouted_urls_py(repo_root, visited_paths):
    unrouted = []
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        if "urls.py" in filenames:
            full = os.path.join(dirpath, "urls.py")
            if full not in visited_paths:
                unrouted.append(full)
    return unrouted


FIELDNAMES = [
    "service", "feature", "url_name", "view_class", "method",
    "api_pattern", "route", "source_file", "class_doc", "method_doc",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                      formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("repo_root")
    parser.add_argument("--gate-class", action="append", default=[],
                         help="Chi liet ke view co class nay trong permission_classes (co the lap lai). Khong truyen = liet ke tat ca.")
    parser.add_argument("--api-pattern-style", choices=["inline-kwargs", "tail-kwargs"],
                         default="inline-kwargs")
    parser.add_argument("--service", default=None)
    parser.add_argument("--project-package", default=None)
    parser.add_argument("--methods", default=",".join(DEFAULT_METHODS))
    parser.add_argument("--include-unrouted", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    repo_root = os.path.abspath(args.repo_root)
    if not os.path.isdir(repo_root):
        print(f"[ERROR] repo_root khong ton tai: {repo_root}", file=sys.stderr)
        sys.exit(1)
    service = args.service or os.path.basename(repo_root)
    methods = [m.strip().lower() for m in args.methods.split(",") if m.strip()]

    project_package = find_project_package(repo_root, args.project_package)
    root_urls = os.path.join(project_package, "urls.py")

    info("dang xay module index (co the mat vai giay voi repo lon)...")
    module_index, package_index = build_module_index(repo_root)

    rows = []
    file_cache = {}
    visited = set()
    walk_urls(root_urls, [], module_index, package_index, repo_root,
              args.gate_class, args.api_pattern_style, methods, rows,
              file_cache, visited, depth=0)

    for r in rows:
        r["service"] = service

    out = open(args.out, "w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    finally:
        if args.out:
            out.close()

    info(f"tong so dong: {len(rows)}")
    if args.include_unrouted:
        visited_paths = {p for (p, _prefix) in visited}
        for u in find_unrouted_urls_py(repo_root, visited_paths):
            info(f"urls.py khong duoc include tu root (dead route): {os.path.relpath(u, repo_root)}")


if __name__ == "__main__":
    main()
