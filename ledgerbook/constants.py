"""Static data shared by the interface (Qt-free)."""

# Curated, single-character logbook symbols. The saved icon stays plain text so existing databases and
# exported .ledgerbook files keep working.
LOGBOOK_ICONS = [
    ('📒', 'Notebook'), ('📘', 'Blue book'), ('📗', 'Green book'), ('📕', 'Red book'), ('📓', 'Journal'),
    ('📔', 'Decorated notebook'), ('📋', 'Clipboard'), ('🗂️', 'File dividers'), ('📁', 'Folder'), ('📝', 'Notes'),
    ('📅', 'Calendar'), ('📊', 'Chart'), ('📈', 'Growth'), ('🧮', 'Calculator'), ('🔧', 'Tools'),
    ('⚙️', 'Engineering'), ('🔬', 'Science'), ('💻', 'Computer'), ('✈️', 'Aviation'), ('🚗', 'Vehicle'),
    ('🏠', 'Home'), ('💼', 'Work'), ('💰', 'Finance'), ('💳', 'Expenses'), ('🏥', 'Health'),
    ('🎓', 'Education'), ('🌍', 'Travel'), ('📦', 'Inventory'), ('⭐', 'Favorites'), ('🔖', 'Bookmark'),
    ('🎯', 'Goals'), ('🔒', 'Private'), ('☑️', 'Checklist'), ('▤', 'Classic logbook'),
]
DEFAULT_ICON = '▤'

TYPE_NAMES = {'text': 'Text', 'number': 'Number', 'date': 'Date', 'checkbox': 'Checkbox', 'select': 'Dropdown',
              'multiline': 'Long text', 'attachment': 'Attachment',
              'revision': 'RevisionWorx document'}

TRUE_VALUES = ('1', 'true', 'yes', 'on')

LICENSE_URL = 'https://www.gnu.org/licenses/gpl-3.0.html'
LICENSE_NOTICE = """Copyright (C) 2026 Nate Robertson

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, version 3 of the License.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program. If not, see https://gnu.org/licenses/."""
