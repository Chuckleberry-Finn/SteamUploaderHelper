# regex_tool.py — batch find & replace and file rename logic. No tkinter.

import fnmatch
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════════════
#  State
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class RegexState:
    folders:          list = field(default_factory=list)
    file_patterns:    list = field(default_factory=list)
    recursive:        bool = True
    exclude_patterns: list = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
#  Result types
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ContentMatch:
    filepath: str
    line_no:  int
    original: str
    proposed: str


@dataclass
class RenamePreview:
    folder:   str
    original: str
    proposed: str
    error:    str = ""

    @property
    def changed(self) -> bool:
        return self.original != self.proposed

    @property
    def path_original(self) -> str:
        return os.path.join(self.folder, self.original)

    @property
    def path_proposed(self) -> str:
        return os.path.join(self.folder, self.proposed)


# ═══════════════════════════════════════════════════════════════════════════════
#  Folder exclusion engine
# ═══════════════════════════════════════════════════════════════════════════════

_CI = os.name == "nt"


def _norm_pat(p: str) -> str:
    return p.replace("\\", "/").strip("/")


def compile_exclusions(patterns: list) -> list:
    """Pre-split each raw pattern once, instead of per-directory in the walk."""
    compiled = []
    for raw in patterns:
        pat = raw.strip()
        if not pat or pat.startswith("#"):
            continue
        anchored  = pat.startswith("/")
        norm      = _norm_pat(pat)
        pat_parts = tuple((p.lower() if _CI else p) for p in norm.split("/") if p)
        if pat_parts:
            compiled.append((anchored, "/" in norm, pat_parts))
    return compiled


def is_dir_excluded(rel_parts: tuple, compiled: list) -> bool:
    for anchored, has_slash, pat_parts in compiled:
        n = len(pat_parts)
        if anchored or has_slash:
            if anchored:
                if len(rel_parts) == n and all(
                    fnmatch.fnmatch(rel_parts[i], pat_parts[i]) for i in range(n)
                ):
                    return True
            else:
                for off in range(len(rel_parts) - n + 1):
                    if all(
                        fnmatch.fnmatch(rel_parts[off + i], pat_parts[i])
                        for i in range(n)
                    ):
                        return True
        elif any(fnmatch.fnmatch(part, pat_parts[0]) for part in rel_parts):
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
#  File collection
# ═══════════════════════════════════════════════════════════════════════════════

def matches_file_patterns(name: str, patterns: list) -> bool:
    if not patterns:
        return True
    target = name.lower() if _CI else name
    return any(fnmatch.fnmatch(target, p.lower() if _CI else p) for p in patterns)


def collect_files(state: RegexState) -> list:
    compiled = compile_exclusions(state.exclude_patterns)
    results  = []
    for folder in state.folders:
        root = Path(folder)
        if state.recursive:
            for dirpath, dirnames, filenames in os.walk(root):
                dp  = Path(dirpath)
                rel = dp.relative_to(root).parts
                dirnames[:] = [
                    d for d in dirnames
                    if not is_dir_excluded(
                        rel + ((d.lower() if _CI else d),), compiled)
                ]
                for fname in filenames:
                    if matches_file_patterns(fname, state.file_patterns):
                        results.append(dp / fname)
        else:
            for fp in root.iterdir():
                if fp.is_file() and matches_file_patterns(fp.name, state.file_patterns):
                    results.append(fp)
    return sorted(set(results))


def safe_read(path: Path) -> Optional[str]:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, PermissionError):
            continue
    return None


# ═══════════════════════════════════════════════════════════════════════════════
#  Regex helpers
# ═══════════════════════════════════════════════════════════════════════════════

def expand_repl(repl: str) -> str:
    # Normalise editor-style replacement syntax ($1, ${name}) to re.sub's \1, \g<name>
    repl = repl.replace("\\n", "\n").replace("\\t", "\t").replace("\\r", "\r")
    repl = re.sub(r"\$\{([^}]+)\}", r"\\g<\1>", repl)
    repl = re.sub(r"\$(\d+)", r"\\\1", repl)
    return repl


def build_flags(ignorecase: bool = False,
                multiline:  bool = False,
                dotall:     bool = False) -> int:
    f = 0
    if ignorecase: f |= re.IGNORECASE
    if multiline:  f |= re.MULTILINE
    if dotall:     f |= re.DOTALL
    return f


def compile_pattern(pattern: str, flags: int):
    try:
        return re.compile(pattern, flags), None
    except re.error as e:
        return None, str(e)


def parse_file_filter(raw: str) -> list:
    patterns = []
    for tok in raw.split(","):
        tok = tok.strip()
        if not tok:
            continue
        if tok.startswith(".") and "*" not in tok and "?" not in tok:
            tok = "*" + tok
        patterns.append(tok)
    return patterns


# ═══════════════════════════════════════════════════════════════════════════════
#  Content find & replace
# ═══════════════════════════════════════════════════════════════════════════════

def scan_content(state: RegexState, rx, replacement: str) -> list:
    matches = []
    for fp in collect_files(state):
        text = safe_read(fp)
        if text is None:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if rx.search(line):
                matches.append(ContentMatch(
                    filepath=str(fp),
                    line_no=i,
                    original=line,
                    proposed=rx.sub(replacement, line),
                ))
    return matches


def apply_content(state: RegexState, rx, replacement: str,
                  backup: bool = False) -> tuple:
    changed_paths = []
    skipped = errors = 0

    for fp in collect_files(state):
        text = safe_read(fp)
        if text is None:
            skipped += 1
            continue
        new_text = rx.sub(replacement, text)
        if new_text == text:
            continue
        try:
            if backup:
                shutil.copy2(fp, str(fp) + ".bak")
            fp.write_text(new_text, encoding="utf-8")
            changed_paths.append(str(fp))
        except OSError:
            errors += 1

    return changed_paths, skipped, errors


# ═══════════════════════════════════════════════════════════════════════════════
#  File rename
# ═══════════════════════════════════════════════════════════════════════════════

def scan_renames(state: RegexState, rx, replacement: str,
                 scope: str) -> list:
    previews = []
    for fp in collect_files(state):
        p = Path(fp)
        if scope == "stem":
            new_name = rx.sub(replacement, p.stem) + p.suffix
        elif scope == "ext":
            suf = p.suffix.lstrip(".")
            new_name = p.stem + "." + rx.sub(replacement, suf) if suf else p.name
        else:
            new_name = rx.sub(replacement, p.name)
        previews.append(RenamePreview(folder=str(p.parent),
                                      original=p.name, proposed=new_name))

    seen: dict = {}
    for i, pv in enumerate(previews):
        if not pv.changed:
            continue
        key = (pv.folder, pv.proposed.lower() if _CI else pv.proposed)
        if key in seen:
            pv.error = "conflict"
            previews[seen[key]].error = "conflict"
        else:
            seen[key] = i

    return previews


def apply_renames(previews: list, backup: bool = False) -> tuple:
    renamed_paths = []
    errors = 0

    for pv in previews:
        if not pv.changed or pv.error:
            continue
        try:
            src, dst = Path(pv.path_original), Path(pv.path_proposed)
            if dst.exists():
                raise FileExistsError("Target already exists: " + dst.name)
            if backup:
                shutil.copy2(src, str(src) + ".bak")
            src.rename(dst)
            renamed_paths.append(str(dst))
        except OSError as e:
            pv.error = str(e)
            errors += 1

    return renamed_paths, errors
