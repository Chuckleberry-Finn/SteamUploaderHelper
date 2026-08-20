# uploader.py — config, PZ file parsing, and direct Steam Workshop upload.
# No tkinter. Can also run standalone as a CLI tool.

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path


# ═══════════════════════════════════════════════════════════════════════════════
#  Constants
# ═══════════════════════════════════════════════════════════════════════════════

PZ_APP_ID = 108600   # Project Zomboid Steam App ID

VISIBILITY_MAP = {
    "public":   0, "0": 0,
    "friends":  1, "1": 1,
    "private":  2, "2": 2, "hidden": 2,
    "unlisted": 3, "3": 3,
}

SCRIPT_DIR       = (Path(sys.executable).parent if getattr(sys, "frozen", False)
                    else Path(__file__).parent.parent)
CONFIG_PATH      = SCRIPT_DIR / "config.json"
DEFAULT_UPLOADER = SCRIPT_DIR / "steamUploader" / "SteamUploader.exe"


# ═══════════════════════════════════════════════════════════════════════════════
#  Config schema
# ═══════════════════════════════════════════════════════════════════════════════

CONFIG_SCHEMA = [
    {
        "key":     "workshop_dir",
        "label":   "Workshop folder",
        "prompt":  "Path to your Zomboid/Workshop folder",
        "default": None,
        "type":    "path",
    },
    {
        "key":     "uploader_exe",
        "label":   "SteamUploader.exe",
        "prompt":  (
            "Path to SteamUploader.exe\n"
            "    (leave blank to skip)"
        ),
        "default": None,
        "type":    "file",
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
#  Config
# ═══════════════════════════════════════════════════════════════════════════════

def _fill_runtime_defaults():
    for entry in CONFIG_SCHEMA:
        if entry["default"] is not None:
            continue
        if entry["key"] == "workshop_dir":
            base = (
                Path(os.environ.get("USERPROFILE", Path.home()))
                if platform.system() == "Windows"
                else Path.home()
            )
            entry["default"] = str(base / "Zomboid" / "Workshop")
        elif entry["key"] == "uploader_exe":
            entry["default"] = str(DEFAULT_UPLOADER) if DEFAULT_UPLOADER.exists() else ""


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            with CONFIG_PATH.open(encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            print("  Warning: could not read config.json, starting fresh.")
    return {}


def save_config(config: dict) -> None:
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print("  Config saved to " + str(CONFIG_PATH))


def _prompt_value(entry: dict, current) -> str:
    kind    = entry.get("type", "str")
    display = str(current) if current not in (None, "") else "(none)"
    while True:
        print("\n  " + entry["prompt"])
        print("  Current: " + display)
        raw    = input("  New value (Enter to keep): ").strip()
        chosen = raw if raw else (str(current) if current not in (None, "") else "")
        if kind == "path":
            p = Path(chosen) if chosen else None
            if p and p.is_dir():
                return str(p)
            print("  Directory not found: " + (chosen or "(empty)"))
        else:
            return chosen


def resolve_config(saved: dict, force_prompt: bool,
                   silent: bool = False) -> tuple:
    # silent=True fills defaults without prompting (GUI use); silent=False prompts (CLI use)
    _fill_runtime_defaults()
    config  = dict(saved)
    changed = False
    missing = [e["key"] for e in CONFIG_SCHEMA if e["key"] not in config]

    if not silent and (force_prompt or missing):
        print("\nConfigure settings  (Enter to keep current value):")
        print("-" * 50)

    for entry in CONFIG_SCHEMA:
        key         = entry["key"]
        raw_current = config.get(key, entry.get("default", ""))
        if key not in config or force_prompt:
            if silent:
                config[key] = str(raw_current or "")
            else:
                new_val = _prompt_value(entry, raw_current)
                if new_val != str(raw_current or ""):
                    changed = True
                config[key] = new_val

    return config, changed


def config_to_settings(config: dict) -> dict:
    exe_raw = config.get("uploader_exe", "").strip()
    return {
        "workshop_dir": Path(config["workshop_dir"]) if config.get("workshop_dir") else None,
        "uploader_exe": Path(exe_raw) if exe_raw else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  PZ file parsing
# ═══════════════════════════════════════════════════════════════════════════════

def parse_kv_file(path: Path) -> dict:
    # Parses key=value files (workshop.txt / mod.info); multi-line description= is joined
    result      = {}
    desc_lines  = []
    current_key = None

    if not path.exists():
        return result

    with path.open(encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")

            if (current_key and current_key != "description"
                    and line and line[0] in (" ", "\t")):
                result[current_key] += "\n" + line.strip()
                continue

            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                current_key = None
                continue

            if "=" in stripped:
                key, _, value = stripped.partition("=")
                key   = key.strip().lower()
                value = value.strip()
                if key == "description":
                    desc_lines.append(value)
                    current_key = "description"
                else:
                    result[key] = value
                    current_key = key
            else:
                current_key = None

    if desc_lines:
        result["description"] = "\n".join(desc_lines)
    return result


def parse_tags(raw: str) -> list:
    if not raw:
        return []
    sep = ";" if ";" in raw else ","
    return [t.strip() for t in raw.split(sep) if t.strip()]


def find_preview(mod_dir: Path) -> Path | None:
    for name in ("preview.png", "preview.jpg", "preview.gif", "preview.jpeg"):
        p = mod_dir / name
        if p.exists():
            return p
    return None


def is_mod_dir(path: Path) -> bool:
    return (path / "Contents").is_dir() or (path / "workshop.txt").exists()


def get_all_mod_dirs(workshop_dir: Path) -> list:
    return sorted(p for p in workshop_dir.iterdir()
                  if p.is_dir() and is_mod_dir(p))


def _first_mod_info_kv(mod_dir: Path) -> dict:
    contents_mods = mod_dir / "Contents" / "mods"
    if contents_mods.is_dir():
        for sub in sorted(contents_mods.iterdir()):
            kv = parse_kv_file(sub / "mod.info")
            if kv:
                return kv
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
#  Mod metadata  (no tkinter state)
# ═══════════════════════════════════════════════════════════════════════════════

class ModInfo:
    """Pure data object for one mod folder; GUI selection state lives in app.py."""

    def __init__(self, mod_dir: Path):
        self.path  = mod_dir
        self.name  = mod_dir.name

        kv         = parse_kv_file(mod_dir / "workshop.txt")
        self.title = kv.get("title", mod_dir.name)

        info_kv     = _first_mod_info_kv(mod_dir)
        self.mod_id = info_kv.get("modid", info_kv.get("id", ""))

    def matches(self, pattern: str, field: str) -> bool:
        terms = pattern.strip()
        if not terms:
            return True
        targets = [self.mod_id] if field == "modid" else [self.name, self.title]
        try:
            return all(
                any(re.search(t, s, re.IGNORECASE) for s in targets)
                for t in terms.split()
            )
        except re.error:
            return True

    def __repr__(self) -> str:
        return "ModInfo(%s)" % self.name


# ═══════════════════════════════════════════════════════════════════════════════
#  Upload helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_mod_ids(contents_path: str) -> list:
    mod_ids  = []
    mods_dir = Path(contents_path) / "mods"
    if mods_dir.is_dir():
        for sub in sorted(mods_dir.iterdir()):
            kv  = parse_kv_file(sub / "mod.info")
            mid = kv.get("modid", kv.get("id", "")).strip()
            if mid:
                mod_ids.append(mid)
    return mod_ids


def _write_desc_temp(desc_text: str, workshopid, mod_ids: list) -> Path | None:
    # Appends a "Workshop ID / Mod ID" footer after a blank line, per PZ convention
    try:
        footer = [""]
        if workshopid:
            footer.append("Workshop ID: " + str(workshopid))
        for mid in mod_ids:
            footer.append("Mod ID: " + mid)
        text = desc_text.rstrip() + "\n" + "\n".join(footer) + "\n"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".bbcode", delete=False, encoding="utf-8"
        )
        tmp.write(text)
        tmp.close()
        return Path(tmp.name)
    except OSError as e:
        print("    WARNING: could not write description temp file (" + str(e) + ")")
        return None


def _build_cmd(exe: Path, mod_dir: Path, workshop_kv: dict,
               mod_info_kv: dict, upload_mode: str,
               tmp_desc: Path | None) -> list:
    raw_wid    = workshop_kv.get("id") or workshop_kv.get("publishedfileid")
    workshopid = int(raw_wid) if raw_wid and str(raw_wid).isdigit() else None

    cmd = [str(exe), "-a", str(PZ_APP_ID)]

    if workshopid:
        cmd += ["-w", str(workshopid)]
    else:
        cmd.append("--new")

    if tmp_desc and tmp_desc.exists():
        cmd += ["-d", str(tmp_desc)]

    tags = parse_tags(workshop_kv.get("tags") or mod_info_kv.get("tags") or "")
    if tags:
        cmd += ["-T", ",".join(tags)]

    if upload_mode == "full":
        contents = mod_dir / "Contents"
        if contents.is_dir():
            cmd += ["-c", str(contents)]
        preview = find_preview(mod_dir)
        if preview:
            cmd += ["-p", str(preview)]

    return cmd


# ═══════════════════════════════════════════════════════════════════════════════
#  Direct upload
# ═══════════════════════════════════════════════════════════════════════════════

def run_direct_upload(mod_dirs: list, uploader_exe: Path | None,
                      dry_run: bool, upload_mode: str = "full") -> None:
    if uploader_exe is None:
        print("  No SteamUploader.exe configured.\n")
        return

    if not uploader_exe.exists() and not dry_run:
        print("  ERROR: Uploader not found at " + str(uploader_exe) + "\n")
        return

    print("  Uploading " + str(len(mod_dirs)) + " mod(s)\n")
    ok = fail = 0

    for mod_dir in mod_dirs:
        print("  [" + mod_dir.name + "]")
        tmp_desc = None

        try:
            workshop_kv = parse_kv_file(mod_dir / "workshop.txt")
            mod_info_kv = _first_mod_info_kv(mod_dir)

            raw_wid    = workshop_kv.get("id") or workshop_kv.get("publishedfileid")
            workshopid = int(raw_wid) if raw_wid and str(raw_wid).isdigit() else None
            desc_text  = workshop_kv.get("description", "").strip()
            mod_ids    = (_get_mod_ids(str(mod_dir / "Contents"))
                          if (mod_dir / "Contents").is_dir() else [])

            tmp_desc = _write_desc_temp(desc_text, workshopid, mod_ids)
            if tmp_desc:
                parts = (["Workshop ID: " + str(workshopid)] if workshopid else []) + \
                        ["Mod ID: " + m for m in mod_ids]
                if parts:
                    print("    Footer: " + " | ".join(parts))

            cmd = _build_cmd(uploader_exe, mod_dir, workshop_kv,
                             mod_info_kv, upload_mode, tmp_desc)

            if dry_run:
                label = " (desc+tags only)" if upload_mode == "desc_tags" else ""
                print("    DRY RUN" + label + " - would run:")
                print("      " + " ".join(cmd))
                ok += 1
            else:
                if upload_mode == "desc_tags":
                    print("    Mode: description + tags only")
                result = subprocess.run(cmd, capture_output=True, text=True)
                out    = (result.stdout + result.stderr).strip()
                if result.returncode == 0:
                    print("    OK")
                    for line in out.splitlines():
                        print("      " + line)
                    ok += 1
                else:
                    print("    FAILED (exit " + str(result.returncode) + ")")
                    for line in out.splitlines():
                        print("      " + line)
                    fail += 1

        except Exception as e:
            print("    ERROR: " + str(e))
            fail += 1

        finally:
            if tmp_desc and tmp_desc.exists():
                tmp_desc.unlink(missing_ok=True)

        print()

    print("-" * 50)
    print("  OK     : " + str(ok))
    if fail:
        print("  FAILED : " + str(fail))
    print()


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI entry point
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Upload Project Zomboid mods to the Steam Workshop."
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--reset",   action="store_true")
    args = parser.parse_args()

    print("=" * 50)
    print("  PZ Mod Uploader")
    print("=" * 50)

    if args.reset and CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
        print("\n  Config reset.\n")

    saved           = load_config()
    config, changed = resolve_config(saved, force_prompt=args.reset)

    print("\nSettings:")
    for entry in CONFIG_SCHEMA:
        print("  %-22s : %s" % (entry["label"], config.get(entry["key"]) or "(not set)"))

    if changed or any(e["key"] not in saved for e in CONFIG_SCHEMA):
        print()
        save_config(config)

    settings     = config_to_settings(config)
    workshop_dir = settings["workshop_dir"]
    uploader_exe = settings["uploader_exe"]

    if not workshop_dir or not workshop_dir.is_dir():
        print("\nERROR: Workshop directory not found: " + str(workshop_dir))
        sys.exit(1)

    mod_dirs = get_all_mod_dirs(workshop_dir)
    print("\n  Found " + str(len(mod_dirs)) + " mod(s).\n")
    run_direct_upload(mod_dirs, uploader_exe, args.dry_run)


if __name__ == "__main__":
    main()
