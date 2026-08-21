# PZ SteamUploader Helper

Batch regex and Steam Workshop uploading for Project Zomboid mods utilizing SteamUploader as a base.

---

## Setup

1. Grab a copy of [SteamUploader (C++)](https://github.com/SimKDT/Steam-Uploader).
2. Place it alongside either the built `.exe`, or the `py/` folder if running from source.
3. Run it.

```text
PZ SteamUploader Helper.exe
SteamUploader/
```
or, running from source:
```text
py/
SteamUploader/
```

Open **Settings** (the gear icon) and set the `workshop folder` and `steamUploader.exe` paths.

---

## Key Features

| Feature                             | Description                                                                                                                                                                   |
|-------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Batch Regex**                     | Find/replace across file contents, and batch file renaming, across any folder(s). Recursive, with exclude patterns, dry-run preview.             |
| **Batch upload (full)**             | Uploads content, preview image, description, and tags for selected mods.                                                                                                      |
| **Batch upload (desc + tags only)** | Pushes metadata updates without re-uploading content.                                                                                                                         |
| **Auto Info Pull/Write**            | Title, description, and tags are read straight from each mod's `workshop.txt` / `mod.info`. New uploads writes back the new WorkshopID.                                       |
| **Regex to Upload Workflow**        | Files changed by a regex operation auto-flag/select their mod in the Upload tab.                                                                                              |
| **Live theme editor**               | Not related to the uploader process. Click any color swatch in the topbar to recolor that UI element via a color picker, also saved to `config.json`, with a one-click reset. |

---

### Building the exe

Run `build_exe.bat` from the project root, on Windows.

> [!NOTE]
> PyInstaller can't cross-compile, this must be run on Windows, not Linux/macOS.

The built exe lands in the project root, so it shares the same `config.json` and `steamUploader/` folder as running `python py/app.py` directly.

---

### Troubleshooting

**A mod isn't showing up in the list:** It needs either a `Contents/` folder or a `workshop.txt` file to be recognized as a mod at all.

**Mod ID shows blank:** It's only read from the *first* subfolder (alphabetically) under `Contents/mods/`. If multiple mods are packed together and that one's `mod.info` lacks an ID, the others aren't checked.

---

### Config

`config.json` is created automatically on first run and stores your Workshop folder path, `SteamUploader.exe` path, and any custom theme colors.