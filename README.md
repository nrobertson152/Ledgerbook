<p align="center">
  <img src="assets/ledgerbook.png" width="112" alt="Ledgerbook icon">
</p>

<h1 align="center">Ledgerbook</h1>

<p align="center">
  <strong>An offline, customizable logbook manager for Linux.</strong><br>
  Track vehicle maintenance, equipment, projects, expenses or anything else, with fields you design yourself.
</p>

<p align="center">
  <a href="https://github.com/nrobertson152/ledgerbook/releases/latest"><img alt="Download the latest AppImage" src="https://img.shields.io/badge/Download-AppImage-2ea44f?style=for-the-badge"></a>
</p>

<p align="center">
  <img alt="Version 1.0.0" src="https://img.shields.io/badge/version-1.0.0-4c6ef5">
  <img alt="License: GPL-3.0-only" src="https://img.shields.io/badge/license-GPL--3.0--only-blue">
  <img alt="Python 3" src="https://img.shields.io/badge/python-3.9%2B-3776ab">
  <img alt="Qt 6" src="https://img.shields.io/badge/Qt-6%20(PySide6)-41cd52">
  <img alt="Linux" src="https://img.shields.io/badge/platform-Linux-lightgrey">
</p>

<!-- Screenshots: run `python3 tests_gui.py`, copy a few images from ./screenshots into docs/, then uncomment:
<p align="center">
  <img src="docs/Midnight-home.png" width="48%" alt="Home dashboard, Midnight theme">
  <img src="docs/Light-logbook.png" width="48%" alt="Logbook view, Light theme">
</p>
-->

---

Ledgerbook 1.0.0 is the first stable release. It keeps every feature from the beta series. The SQLite schema, `.ledgerbook` files and `settings.json` keys are unchanged, so data from earlier versions opens as-is.

**No accounts. No cloud. No telemetry.** Your logbooks are stored in one SQLite file on your own machine, and Ledgerbook never connects to the internet while it runs.

## Features

- **Logbooks with your own fields**: text, number, date, checkbox, dropdown, long text and attachment columns. Rename, retype and reorder them from a live preview.
- **Organized sidebar** with coloured logbook tiles, count badges, folders, pinning and recently opened logbooks.
- **Home dashboard** showing totals, recent logbooks and quick actions.
- **Command palette** (<kbd>Ctrl</kbd>+<kbd>K</kbd>): type to jump to any logbook or run any action.
- **Fast entry handling**: search, sorting, adjustable column widths, multi-select and duplication.
- **Undo for deletes** instead of confirmation prompts. Deleted items also go to a Recycle Bin you can restore from.
- **Archiving** for logbooks you're finished with but want to keep.
- **PDF reports** with your choice of columns and date range, shaded headers, banded rows, page numbers and an optional landscape layout.
- **Import and export** as CSV or `.ledgerbook` files. CSV headings match your columns whatever their case or spacing; a bad value stops the import with its row number and nothing is added.
- **Backups**: manual and automatic backups, restore, and database integrity checks.
- **Templates** for new logbooks: vehicle maintenance, equipment & calibration, expenses, inspections and a project log, each a normal logbook you can change afterwards.
- **Due dates** (*Due date* columns): overdue and upcoming items are coloured in the table and listed under *Coming up* on Home. Only the newest entry for each item counts, so a done task stops nagging. Quick buttons set the next due date 1, 3, 6 or 12 months after the entry.
- **Totals** of number columns under the table, following your search, and at the end of PDF reports. Numbers may be typed as you write them: `$1,234.50`, `€ 45`, `(12.50)`.
- **Attachments** can be picked with *Browse…* and opened from the entry's right-click menu.
- **RevisionWorx document columns**: a column type that holds a document number such as `DWG-100`. When [RevisionWorx](https://github.com/nrobertson152/RevisionWorx) is installed, the table shows each document's live revision and state, the entry editor can pick documents, and the entry menu opens the document in RevisionWorx (F5 refreshes). Without RevisionWorx the number is plain text.
- **Four themes**: Midnight, Graphite, Terracotta and Light, checked for readable contrast and using the bundled Inter typeface.

## Getting started

### Option 1: AppImage (recommended)

1. Go to the [latest release](https://github.com/nrobertson152/ledgerbook/releases/latest) and download `Ledgerbook-<version>-x86_64.AppImage` from the **Assets** list.
2. Make the file executable and run it:

   ```bash
   chmod +x ~/Downloads/Ledgerbook-*-x86_64.AppImage
   ~/Downloads/Ledgerbook-*-x86_64.AppImage
   ```

   Instead of using the terminal, you can right-click the file, choose **Properties → Permissions**, tick **Allow executing file as program**, and then double-click it.

The AppImage includes its own Python and Qt, so it runs on Linux Mint 21 or newer, Ubuntu 22.04 or newer, and similar 64-bit distributions. It's portable: keep it anywhere, such as `~/Applications`. To update, download the newer file from the [Releases](https://github.com/nrobertson152/ledgerbook/releases) page and replace the old one.

### Option 2: Installer (adds a menu entry and a `ledgerbook` command)

```bash
git clone https://github.com/nrobertson152/ledgerbook.git
cd ledgerbook
bash install.sh
```

The installer:

- installs Qt's `libxcb-cursor0` with apt if it's missing (it asks for your password)
- creates an isolated Python environment and downloads PySide6
- opens a setup wizard that installs Ledgerbook, adds a `ledgerbook` command and creates a menu entry (and, if you choose, a desktop shortcut)

The first installation needs an internet connection; normal use doesn't. If `venv` is missing, run `sudo apt install python3-venv`.

### Option 3: Run from source

```bash
git clone https://github.com/nrobertson152/ledgerbook.git
cd ledgerbook
python3 -m venv .venv
.venv/bin/pip install 'PySide6-Essentials>=6.7,<7'
.venv/bin/python -m ledgerbook
```

## Your data

| What | Where |
|---|---|
| Database | `~/.local/share/ledgerbook/ledgerbook.sqlite3` (or `$XDG_DATA_HOME/ledgerbook/`) |
| Settings | `~/.config/ledgerbook/settings.json` (or `$XDG_CONFIG_HOME/ledgerbook/`) |

The AppImage, the installer and a source checkout all use these same locations, so they share your logbooks. Deleting the AppImage doesn't delete your data. **Still, back up your database before upgrading.**

## Keyboard shortcuts

| Key | Action |
|---|---|
| <kbd>Ctrl</kbd>+<kbd>K</kbd> | Command palette |
| <kbd>Ctrl</kbd>+<kbd>N</kbd> | New entry |
| <kbd>Ctrl</kbd>+<kbd>Shift</kbd>+<kbd>N</kbd> | New logbook |
| <kbd>Ctrl</kbd>+<kbd>F</kbd> | Search entries |
| <kbd>Ctrl</kbd>+<kbd>D</kbd> | Duplicate selected entries |
| <kbd>Ctrl</kbd>+<kbd>Z</kbd> | Undo last delete |
| <kbd>Ctrl</kbd>+<kbd>B</kbd> | Show or hide the sidebar |
| <kbd>Ctrl</kbd>+<kbd>Return</kbd> | Save (in the entry dialog) |
| <kbd>Delete</kbd> / <kbd>Return</kbd> | Delete / edit selected entries |

## Troubleshooting

- **The AppImage won't start, or there's an error about FUSE:** run `sudo apt install libfuse2`. Alternatively, start it with `./Ledgerbook-*-x86_64.AppImage --appimage-extract-and-run`.
- **Error about the Qt "xcb" platform plugin when running from source:** run `sudo apt install libxcb-cursor0`.

## Development

### Project layout

```
ledgerbook/            application package (run with: python -m ledgerbook)
  app.py               main window, actions and shortcuts
  views.py             home dashboard and logbook table
  sidebar.py           logbook and folder navigation
  dialogs.py           entry, column, logbook, export and recovery dialogs
  settings.py          settings and About dialogs
  palette.py           Ctrl+K command palette
  widgets.py           shared UI building blocks
  theme.py             design tokens, themes and stylesheet
  icons.py             line icons drawn in code
  store.py             SQLite storage (Qt-free)
  prefs.py             settings.json handling (Qt-free)
  pdf.py               PDF report export
  resources/           app icon and Inter font
assets/                icon used by the installer and AppImage
tests/                 unit tests
tests_gui.py           renders screenshots of every screen in every theme
install.sh             installer entry point
installer.py           setup wizard used by install.sh
packaging/appimage/    AppImage build script, AppRun and desktop entry
```

### Tests

```bash
# Storage, preferences, helpers and theme contrast (no Qt needed)
PYTHONPATH=. python3 -m unittest discover -s tests

# Real-Qt smoke test and screenshots of every screen (needs PySide6; runs offscreen)
python3 tests/test_qt_smoke.py
python3 tests_gui.py        # writes images to ./screenshots
```

### Building the AppImage

```bash
bash packaging/appimage/build-appimage.sh
```

This produces `dist/Ledgerbook-<version>-x86_64.AppImage`. Build on the oldest distribution you want to support (Linux Mint 21 / Ubuntu 22.04 is a good baseline). See [`packaging/appimage/README.md`](packaging/appimage/README.md) for requirements and options.

### Publishing a release

1. Update `__version__` and `VERSION` in `ledgerbook/__init__.py`, `VERSION` in `installer.py`, and the version in this README.
2. Run the tests, then build the AppImage.
3. On GitHub, open **Releases → Draft a new release**, create a tag such as `v1.0.0`, and attach `dist/Ledgerbook-<version>-x86_64.AppImage`.

AppImages go on the Releases page rather than into the repository. Releases accept files up to 2 GB, while files committed to the repository are limited to 100 MB.

## Contributing

Bug reports and pull requests are welcome. When reporting a bug in the [issue tracker](https://github.com/nrobertson152/ledgerbook/issues), please include:

- your distribution and desktop environment
- how you run Ledgerbook (AppImage, installer or source)
- the steps that reproduce the problem

Before opening a pull request, run the test suite. If you changed the interface, also run `python3 tests_gui.py` and check the screenshots in all four themes.

## License

Copyright © 2026 Nate Robertson.

Ledgerbook is free software: you can redistribute and/or modify it under the terms of the [GNU General Public License, version 3](LICENSE) (GPL-3.0-only).

The bundled [Inter](https://rsms.me/inter/) typeface is distributed under the SIL Open Font License; see [`Inter-LICENSE.txt`](ledgerbook/resources/fonts/Inter-LICENSE.txt).
