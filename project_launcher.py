#!/usr/bin/env python3
"""
project_launcher.py — iTerm2 Python API script
Opens a new tab with split panes for a project.

Shows a native macOS Spotlight/Raycast-style picker (translucent floating panel) with:
  - Search field at top for filtering
  - New Tab section with 1/2/3/4 pane options
  - Running project indicators
  - Grouped section cards (Pixeldust, Personal) with project rows
  - Pin/favorite for sections and projects
  - Color-coded badges: green [4P], blue [3P], gray [2P]
  - Plus (+) button to create new projects/subdirectories
  - Expand/collapse toggle to show subdirectories with Finder/Cursor actions
  - Tab title set to project name after opening

Layout rules:
  - 4-pane layout: When the project uses Celery (detected automatically).
    ┌──────────┬──────────┐
    │ Frontend │ Backend  │
    │ yarn dev │ make run │
    ├──────────┼──────────┤
    │  Celery  │  Shell   │
    └──────────┴──────────┘

  - 3-pane layout: When the project does NOT use Celery.
    ┌──────────┬──────────┐
    │ Frontend │ Backend  │
    │ yarn dev ├──────────┤
    │          │  Shell   │
    │          │  make sh │
    └──────────┴──────────┘

Accessible from: iTerm2 > Scripts > project_launcher
"""

import json
import os
import subprocess
import time

import objc
from AppKit import (
    NSAlert,
    NSAppearance,
    NSApplication,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBox,
    NSButton,
    NSColor,
    NSFont,
    NSFontAttributeName,
    NSFloatingWindowLevel,
    NSForegroundColorAttributeName,
    NSMutableAttributedString,
    NSPanel,
    NSScrollView,
    NSSearchField,
    NSTextField,
    NSView,
    NSVisualEffectView,
    NSWorkspace,
)
from Foundation import NSMakeRect, NSObject

import iterm2


# ──────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────

PROJECT_ROOT = os.path.expanduser("~/Desktop/Project")

DEFAULT_COMMANDS = {
    "frontend": "yarn dev",
    "backend": "make run",
    "celery": "make celery",
    "shell": "make sh",
}

EXCLUDE_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv",
    "media", "static", "assets",
    "dummy", "test", "testing", "temp", "tmp", "sandbox", "playground", "scratch",
    "template", "boilerplate", "starter", "skeleton", "scaffold",
    "example", "examples", "demo", "sample", "samples",
    "archive", "old", "backup", "bak", "deprecated", "legacy",
    "misc", "untitled", "new-folder", "copy", "draft",
}

USAGE_FILE = os.path.expanduser("~/.config/iterm2/project_launcher_usage.json")
PINS_FILE = os.path.expanduser("~/.config/iterm2/project_launcher_pins.json")

PANEL_WIDTH = 560
PANEL_HEIGHT = 620

NEW_TAB_SENTINEL = "__NEW_TAB__"


# ──────────────────────────────────────────────
# USAGE TRACKING
# ──────────────────────────────────────────────

def load_usage():
    if os.path.exists(USAGE_FILE):
        try:
            with open(USAGE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def save_usage(usage):
    os.makedirs(os.path.dirname(USAGE_FILE), exist_ok=True)
    with open(USAGE_FILE, "w") as f:
        json.dump(usage, f, indent=2)


def record_usage(project_name):
    usage = load_usage()
    if project_name not in usage:
        usage[project_name] = {"count": 0, "last_used": 0}
    usage[project_name]["count"] += 1
    usage[project_name]["last_used"] = time.time()
    save_usage(usage)


# ──────────────────────────────────────────────
# PIN / FAVORITE TRACKING
# ──────────────────────────────────────────────

def load_pins():
    if os.path.exists(PINS_FILE):
        try:
            with open(PINS_FILE, "r") as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_pins(pins):
    os.makedirs(os.path.dirname(PINS_FILE), exist_ok=True)
    with open(PINS_FILE, "w") as f:
        json.dump(sorted(pins), f, indent=2)


def toggle_pin(pin_key):
    pins = load_pins()
    if pin_key in pins:
        pins.discard(pin_key)
    else:
        pins.add(pin_key)
    save_pins(pins)
    return pin_key in pins


# ──────────────────────────────────────────────
# RUNNING PROJECT DETECTION
# ──────────────────────────────────────────────

def detect_running_projects():
    """Connect briefly to iTerm2 to find which projects have open tabs."""
    running = set()

    async def _detect(connection):
        try:
            app = await iterm2.async_get_app(connection)
            for window in app.terminal_windows:
                for tab in window.tabs:
                    # Check tab title set by our launcher
                    try:
                        title = await tab.async_get_variable("titleOverride")
                        if title:
                            running.add(title)
                            continue
                    except Exception:
                        pass
                    # Fallback: check session names
                    for session in tab.sessions:
                        try:
                            name = await session.async_get_variable("name")
                            if name and " \u2014 " in name:
                                project = name.split(" \u2014 ")[0]
                                running.add(project)
                                break
                        except Exception:
                            pass
        except Exception:
            pass

    try:
        iterm2.run_until_complete(_detect)
    except Exception:
        pass

    return running


# ──────────────────────────────────────────────
# PROJECT SCANNING & DETECTION
# ──────────────────────────────────────────────

def get_commands(project_name):
    cmds = dict(DEFAULT_COMMANDS)
    return cmds


def has_celery(project_path, backend_dir=None):
    dirs_to_check = [project_path]
    if backend_dir and backend_dir != project_path:
        dirs_to_check.append(backend_dir)

    for check_dir in dirs_to_check:
        makefile = os.path.join(check_dir, "Makefile")
        if os.path.isfile(makefile):
            try:
                with open(makefile, "r") as f:
                    if "celery" in f.read().lower():
                        return True
            except IOError:
                pass

        for name in ("celery.py", "celeryconfig.py"):
            if os.path.isfile(os.path.join(check_dir, name)):
                return True

        for sub in ("config", "core", "app", "src"):
            if os.path.isfile(os.path.join(check_dir, sub, "celery.py")):
                return True

        for req_file in ("requirements.txt", "requirements/base.txt", "requirements/dev.txt"):
            req_path = os.path.join(check_dir, req_file)
            if os.path.isfile(req_path):
                try:
                    with open(req_path, "r") as f:
                        for line in f:
                            if line.strip().lower().startswith("celery"):
                                return True
                except IOError:
                    pass

        for dc_file in ("docker-compose.yml", "docker-compose.yaml"):
            dc_path = os.path.join(check_dir, dc_file)
            if os.path.isfile(dc_path):
                try:
                    with open(dc_path, "r") as f:
                        if "celery" in f.read().lower():
                            return True
                except IOError:
                    pass

    return False


def detect_structure(project_path):
    frontend_dir = None
    backend_dir = None

    for entry in os.scandir(project_path):
        if not entry.is_dir():
            continue
        name_lower = entry.name.lower()
        if "frontend" in name_lower:
            frontend_dir = entry.path
        elif "backend" in name_lower:
            backend_dir = entry.path

    if frontend_dir and backend_dir:
        fe_dir = frontend_dir
        be_dir = backend_dir
    elif backend_dir and not frontend_dir:
        fe_dir = backend_dir
        be_dir = backend_dir
    else:
        fe_dir = project_path
        be_dir = project_path

    uses_celery = has_celery(project_path, be_dir)

    return {
        "has_celery": uses_celery,
        "frontend_dir": fe_dir,
        "backend_dir": be_dir,
        "project_dir": project_path,
    }


def get_layout_badge(project_path):
    if project_path == NEW_TAB_SENTINEL:
        return "[2P]"
    structure = detect_structure(project_path)
    return "[4P]" if structure["has_celery"] else "[3P]"


# ──────────────────────────────────────────────
# SECTION SCANNING
# ──────────────────────────────────────────────

def scan_sections():
    """
    Scan PROJECT_ROOT for section dirs (Pixeldust, Personal).
    For each section, scan for project dirs.
    For each project, compute badge via get_layout_badge(), scan for subdirs.
    Return list of section dicts:
      {"name", "path", "projects": [{"name", "path", "badge", "subdirs": [{"name", "path"}]}]}
    """
    sections = []
    if not os.path.isdir(PROJECT_ROOT):
        return sections

    try:
        entries = sorted(os.scandir(PROJECT_ROOT), key=lambda e: e.name.lower())
    except OSError:
        return sections

    for section_entry in entries:
        if not section_entry.is_dir() or section_entry.name.startswith(".") or section_entry.name in EXCLUDE_DIRS:
            continue

        section = {
            "name": section_entry.name,
            "path": section_entry.path,
            "projects": [],
        }

        try:
            proj_entries = sorted(os.scandir(section_entry.path), key=lambda e: e.name.lower())
        except OSError:
            continue

        for proj_entry in proj_entries:
            if not proj_entry.is_dir() or proj_entry.name.startswith(".") or proj_entry.name in EXCLUDE_DIRS:
                continue

            badge = get_layout_badge(proj_entry.path)

            # Scan subdirectories
            subdirs = []
            try:
                for sub_entry in sorted(os.scandir(proj_entry.path), key=lambda e: e.name.lower()):
                    if not sub_entry.is_dir() or sub_entry.name.startswith(".") or sub_entry.name in EXCLUDE_DIRS:
                        continue
                    subdirs.append({"name": sub_entry.name, "path": sub_entry.path})
            except OSError:
                pass

            section["projects"].append({
                "name": proj_entry.name,
                "path": proj_entry.path,
                "badge": badge,
                "subdirs": subdirs,
            })

        sections.append(section)

    return sections


# ──────────────────────────────────────────────
# BADGE COLORS
# ──────────────────────────────────────────────

def badge_color_for(badge):
    if badge == "[4P]":
        return NSColor.systemGreenColor()
    elif badge == "[3P]":
        return NSColor.systemBlueColor()
    return NSColor.systemGrayColor()


# ──────────────────────────────────────────────
# SORTING HELPERS
# ──────────────────────────────────────────────

def sort_sections(sections, pins):
    """Sort sections: pinned first, then alphabetical."""
    def key(s):
        pin_key = "section:" + s["name"]
        is_pinned = 0 if pin_key in pins else 1
        return (is_pinned, s["name"].lower())
    return sorted(sections, key=key)


def sort_projects(projects, pins):
    """Sort projects: pinned first, then by usage frequency, then alphabetical."""
    usage = load_usage()

    def key(p):
        name = p["name"]
        is_pinned = 0 if name in pins else 1
        data = usage.get(name)
        if data and data["count"] > 0:
            return (is_pinned, 0, -data["count"], -data["last_used"], name.lower())
        return (is_pinned, 1, 0, 0, name.lower())

    return sorted(projects, key=key)


def sort_subdirs(subdirs, pins):
    """Sort subdirectories: pinned first, then alphabetical."""
    def key(sd):
        pin_key = "sub:" + sd["path"]
        is_pinned = 0 if pin_key in pins else 1
        return (is_pinned, sd["name"].lower())
    return sorted(subdirs, key=key)


# ──────────────────────────────────────────────
# NATIVE COCOA PICKER UI — Spotlight/Raycast Style
# ──────────────────────────────────────────────

# Layout constants
CARD_INSET_X = 16          # Card left/right margin from panel edges
CARD_INNER_PAD_X = 10      # Padding inside card from card edge to content
PROJECT_ROW_H = 32         # Project row height
SUBDIR_ROW_H = 28          # Subdirectory row height
DIVIDER_H = 5              # Dashed divider row height
HEADER_H = 22              # Section header height
HEADER_GAP = 6             # Gap between header and card
SECTION_GAP = 14           # Gap between section cards
CARD_PAD_Y = 8             # Top/bottom padding inside card


class PickerPanel(NSPanel):
    """Custom panel that handles Escape to cancel."""

    def cancelOperation_(self, sender):
        NSApplication.sharedApplication().stopModal()
        self.close()


class PickerDelegate(NSObject):
    """Manages state and actions for the Spotlight/Raycast-style picker."""

    def init(self):
        self = objc.super(PickerDelegate, self).init()
        if self is None:
            return None
        self._sections = []
        self._selected = None
        self._panel = None
        self._pins = set()
        self._running = set()
        self._expanded = set()
        self._searching = False
        self._scroll_view = None
        self._content_view = None
        self._search_field = None
        self._selectable_items = []   # list of dicts with row info for keyboard nav
        self._selected_index = -1     # currently highlighted item index
        return self

    # ── Card creation ──

    def _make_card(self, x, y, w, h):
        """Create a section card as a flipped view with rounded border background."""
        # Use a FlippedView directly instead of NSBox to avoid event interception
        container = FlippedView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
        container.setWantsLayer_(True)
        layer = container.layer()
        layer.setCornerRadius_(8)
        layer.setBorderWidth_(0.5)
        # Use CGColor via layer methods
        border_color = NSColor.colorWithWhite_alpha_(1.0, 0.12)
        fill_color = NSColor.colorWithWhite_alpha_(1.0, 0.03)
        layer.setBorderColor_(border_color.CGColor())
        layer.setBackgroundColor_(fill_color.CGColor())
        layer.setMasksToBounds_(True)
        return container

    def _make_divider(self, x, y, w):
        """Create a thin dashed divider line inside a card."""
        line = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, 1))
        line.setBoxType_(4)      # NSBoxCustom
        line.setBorderType_(0)   # NSNoBorder
        line.setFillColor_(NSColor.colorWithWhite_alpha_(1.0, 0.08))
        line.setContentViewMargins_((0, 0))
        return line

    def _make_label(self, text, font, color, frame):
        """Create a non-editable text field."""
        tf = NSTextField.alloc().initWithFrame_(frame)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        tf.setAttributedStringValue_(
            NSAttributedString.alloc().initWithString_attributes_(
                text, {
                    NSFontAttributeName: font,
                    NSForegroundColorAttributeName: color,
                }
            )
        )
        return tf

    def _make_attr_label(self, attr_str, frame):
        """Create a non-editable text field with attributed string."""
        tf = NSTextField.alloc().initWithFrame_(frame)
        tf.setBezeled_(False)
        tf.setDrawsBackground_(False)
        tf.setEditable_(False)
        tf.setSelectable_(False)
        tf.setAttributedStringValue_(attr_str)
        return tf

    def _make_pin_button(self, frame, pin_key, tag_id):
        """Create a pin toggle button."""
        btn = NSButton.alloc().initWithFrame_(frame)
        btn.setBordered_(False)
        btn.setTarget_(self)
        btn.setAction_("pinBtnClicked:")
        btn.setToolTip_("Pin / Unpin")
        btn.setTag_(tag_id)
        self._style_pin_button(btn, pin_key)
        return btn

    def _style_pin_button(self, btn, pin_key):
        """Style a pin button based on current pin state."""
        is_pinned = pin_key in self._pins
        symbol = "\u2605" if is_pinned else "\u2606"
        color = NSColor.systemYellowColor() if is_pinned else NSColor.systemGrayColor()
        title = NSAttributedString.alloc().initWithString_attributes_(
            symbol, {
                NSFontAttributeName: NSFont.systemFontOfSize_(13),
                NSForegroundColorAttributeName: color,
            }
        )
        btn.setAttributedTitle_(title)

    # ── Highlight for keyboard navigation ──

    def _update_highlight(self):
        """Update visual highlight on the selected item."""
        for i, item in enumerate(self._selectable_items):
            view = item.get("highlight_view")
            if view is not None:
                if i == self._selected_index:
                    view.setFillColor_(NSColor.colorWithWhite_alpha_(1.0, 0.10))
                else:
                    view.setFillColor_(NSColor.clearColor())

    def _make_highlight_box(self, frame):
        """Create an invisible highlight background box."""
        box = NSBox.alloc().initWithFrame_(frame)
        box.setBoxType_(4)       # NSBoxCustom
        box.setBorderType_(0)    # NSNoBorder
        box.setCornerRadius_(4)
        box.setFillColor_(NSColor.clearColor())
        box.setContentViewMargins_((0, 0))
        return box

    # ── Build the full UI content ──

    def rebuild_ui(self):
        """Rebuild the entire scroll content from current state."""
        self._selectable_items = []
        self._selected_index = -1

        content_w = PANEL_WIDTH - 40  # scroll view is inset 20 on each side
        card_w = content_w - 20  # cards with 10px margin on each side

        # Calculate total height first, then build top-down (Cocoa is bottom-up)
        # We'll collect all sections to render, then compute positions
        search_query = ""
        if self._search_field:
            search_query = self._search_field.stringValue().strip()

        render_items = self._compute_render_items(search_query)
        total_h = self._compute_total_height(render_items, card_w)

        # Ensure minimum height for scroll
        visible_h = PANEL_HEIGHT - 80
        if total_h < visible_h:
            total_h = visible_h

        # Create fresh content view
        old_content = self._content_view
        new_content = FlippedView.alloc().initWithFrame_(
            NSMakeRect(0, 0, content_w, total_h)
        )

        # Render from top
        y_cursor = 10  # top padding

        for item in render_items:
            kind = item["kind"]

            if kind == "new_tab_header":
                label = self._make_label(
                    "NEW TAB", NSFont.boldSystemFontOfSize_(11),
                    NSColor.secondaryLabelColor(),
                    NSMakeRect(10, y_cursor, card_w, HEADER_H)
                )
                new_content.addSubview_(label)
                y_cursor += HEADER_H + HEADER_GAP

            elif kind == "new_tab_card":
                btn_h = 32
                card_h = CARD_PAD_Y * 2 + btn_h
                container = FlippedView.alloc().initWithFrame_(
                    NSMakeRect(10, y_cursor, card_w, card_h)
                )

                pane_options = [
                    ("1 Pane", 1),
                    ("2 Pane", 2),
                    ("3 Pane", 3),
                    ("4 Pane", 4),
                ]
                btn_gap = 10
                btn_count = len(pane_options)
                total_btn_w = card_w - (btn_count + 1) * btn_gap
                btn_w = total_btn_w // btn_count
                side_pad = (card_w - (btn_w * btn_count + btn_gap * (btn_count - 1))) // 2
                btn_y = CARD_PAD_Y

                for oi, (label_text, pane_count) in enumerate(pane_options):
                    btn_x = side_pad + oi * (btn_w + btn_gap)

                    # Clickable mini card button
                    mini_btn = NSButton.alloc().initWithFrame_(
                        NSMakeRect(btn_x, btn_y, btn_w, btn_h)
                    )
                    mini_btn.setWantsLayer_(True)
                    mini_btn.layer().setCornerRadius_(6)
                    mini_btn.layer().setBorderWidth_(0.5)
                    mini_btn.layer().setBorderColor_(
                        NSColor.colorWithWhite_alpha_(1.0, 0.12).CGColor()
                    )
                    mini_btn.layer().setBackgroundColor_(
                        NSColor.colorWithWhite_alpha_(1.0, 0.03).CGColor()
                    )
                    mini_btn.setBordered_(False)
                    mini_btn.setAttributedTitle_(
                        NSAttributedString.alloc().initWithString_attributes_(
                            label_text, {
                                NSFontAttributeName: NSFont.boldSystemFontOfSize_(12),
                                NSForegroundColorAttributeName: NSColor.labelColor(),
                            }
                        )
                    )
                    mini_btn.setTarget_(self)
                    mini_btn.setAction_("newTabClicked:")
                    tag = self._next_tag()
                    mini_btn.setTag_(tag)
                    PickerDelegate._path_tags[tag] = f"{NEW_TAB_SENTINEL}:{pane_count}"
                    container.addSubview_(mini_btn)

                    self._selectable_items.append({
                        "type": "new_tab",
                        "name": f"New Tab {pane_count}",
                        "path": f"{NEW_TAB_SENTINEL}:{pane_count}",
                        "highlight_view": None,
                    })

                new_content.addSubview_(container)
                y_cursor += card_h + SECTION_GAP

            elif kind == "running_header":
                count = item["count"]
                # Header row: "RUNNING" left, "N active" right
                header_view = NSView.alloc().initWithFrame_(
                    NSMakeRect(10, y_cursor, card_w, HEADER_H)
                )
                left_label = self._make_label(
                    "RUNNING", NSFont.boldSystemFontOfSize_(11),
                    NSColor.secondaryLabelColor(),
                    NSMakeRect(0, 0, 200, HEADER_H)
                )
                header_view.addSubview_(left_label)
                right_label = self._make_label(
                    str(count) + " active", NSFont.systemFontOfSize_(10),
                    NSColor.tertiaryLabelColor(),
                    NSMakeRect(card_w - 58, 0, 56, HEADER_H)
                )
                right_label.setAlignment_(2)  # Right aligned
                header_view.addSubview_(right_label)
                new_content.addSubview_(header_view)
                y_cursor += HEADER_H + HEADER_GAP

            elif kind == "running_card":
                names = item["names"]
                card_h = 36
                card = self._make_card(10, y_cursor, card_w, card_h)

                # Build running tags inline
                attr_str = NSMutableAttributedString.alloc().init()
                green_attrs = {
                    NSFontAttributeName: NSFont.systemFontOfSize_(13),
                    NSForegroundColorAttributeName: NSColor.systemGreenColor(),
                }
                for i, name in enumerate(names):
                    if i > 0:
                        sep = NSAttributedString.alloc().initWithString_attributes_(
                            "   ", green_attrs
                        )
                        attr_str.appendAttributedString_(sep)
                    part = NSAttributedString.alloc().initWithString_attributes_(
                        "\u25CF  " + name, green_attrs
                    )
                    attr_str.appendAttributedString_(part)

                tag_label = self._make_attr_label(
                    attr_str,
                    NSMakeRect(CARD_INNER_PAD_X, 8, card_w - CARD_INNER_PAD_X * 2, 20)
                )
                card.addSubview_(tag_label)

                new_content.addSubview_(card)
                y_cursor += card_h + SECTION_GAP

            elif kind == "section_header":
                section = item["section"]
                pin_key = "section:" + section["name"]
                proj_count = len(section["projects"])

                header_view = NSView.alloc().initWithFrame_(
                    NSMakeRect(10, y_cursor, card_w, HEADER_H)
                )

                # Pin button — aligned with text baseline (NSView: y=0 is bottom)
                pin_btn = self._make_pin_button(
                    NSMakeRect(0, (HEADER_H - 16) // 2 + 4, 16, 16), pin_key,
                    self._next_tag()
                )
                self._register_pin_tag(pin_btn.tag(), pin_key)
                header_view.addSubview_(pin_btn)

                # Section name — full height for natural vertical centering
                sec_label = self._make_label(
                    section["name"].upper(),
                    NSFont.boldSystemFontOfSize_(11),
                    NSColor.secondaryLabelColor(),
                    NSMakeRect(20, 0, card_w - 120, HEADER_H)
                )
                header_view.addSubview_(sec_label)

                # Plus button — with gap before project count, shifted up
                plus_btn = NSButton.alloc().initWithFrame_(
                    NSMakeRect(card_w - 86, 4, 20, HEADER_H)
                )
                plus_btn.setBordered_(False)
                plus_btn.setAttributedTitle_(
                    NSAttributedString.alloc().initWithString_attributes_(
                        "+", {
                            NSFontAttributeName: NSFont.systemFontOfSize_(14),
                            NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                        }
                    )
                )
                plus_btn.setTarget_(self)
                plus_btn.setAction_("sectionPlusClicked:")
                tag = self._next_tag()
                plus_btn.setTag_(tag)
                self._register_path_tag(tag, section["path"])
                header_view.addSubview_(plus_btn)

                # Project count — flush with card right edge
                count_label = self._make_label(
                    str(proj_count) + " projects",
                    NSFont.systemFontOfSize_(10),
                    NSColor.tertiaryLabelColor(),
                    NSMakeRect(card_w - 66, 0, 64, HEADER_H)
                )
                count_label.setAlignment_(2)  # Right aligned
                header_view.addSubview_(count_label)

                new_content.addSubview_(header_view)
                y_cursor += HEADER_H + HEADER_GAP

            elif kind == "section_card":
                projects = item["projects"]
                section_name = item["section_name"]
                card_h = item["card_height"]

                card = self._make_card(10, y_cursor, card_w, card_h)
                card_content = card

                inner_y = CARD_PAD_Y
                for pi, proj in enumerate(projects):
                    # Divider between projects (not before first)
                    if pi > 0:
                        divider = self._make_divider(
                            CARD_INNER_PAD_X, inner_y + (DIVIDER_H - 1) // 2,
                            card_w - CARD_INNER_PAD_X * 2 - 12
                        )
                        card_content.addSubview_(divider)
                        inner_y += DIVIDER_H

                    # Highlight box behind project row
                    highlight = self._make_highlight_box(
                        NSMakeRect(2, inner_y, card_w - 4, PROJECT_ROW_H)
                    )
                    card_content.addSubview_(highlight)

                    # Project row
                    self._build_project_row(
                        proj, card_w, inner_y, card_content, highlight
                    )

                    inner_y += PROJECT_ROW_H

                    # Subdirectories (if expanded)
                    if proj["name"] in self._expanded and proj.get("subdirs"):
                        sorted_subs = sort_subdirs(proj["subdirs"], self._pins)
                        for sd in sorted_subs:
                            self._build_subdir_row(sd, card_w, inner_y, card_content)
                            inner_y += SUBDIR_ROW_H

                new_content.addSubview_(card)
                y_cursor += card_h + SECTION_GAP

            elif kind == "search_card":
                projects = item["projects"]
                card_h = item["card_height"]

                card = self._make_card(10, y_cursor, card_w, card_h)
                card_content = card

                inner_y = CARD_PAD_Y
                for pi, proj in enumerate(projects):
                    if pi > 0:
                        divider = self._make_divider(
                            CARD_INNER_PAD_X, inner_y + (DIVIDER_H - 1) // 2,
                            card_w - CARD_INNER_PAD_X * 2 - 12
                        )
                        card_content.addSubview_(divider)
                        inner_y += DIVIDER_H

                    highlight = self._make_highlight_box(
                        NSMakeRect(2, inner_y, card_w - 4, PROJECT_ROW_H)
                    )
                    card_content.addSubview_(highlight)

                    self._build_project_row(
                        proj, card_w, inner_y, card_content, highlight
                    )
                    inner_y += PROJECT_ROW_H

                new_content.addSubview_(card)
                y_cursor += card_h + SECTION_GAP

        # Replace content in scroll view
        self._content_view = new_content
        self._scroll_view.setDocumentView_(new_content)

        # Select first selectable item
        if self._selectable_items:
            self._selected_index = 0
            self._update_highlight()

    def _compute_render_items(self, search_query):
        """Compute list of render items based on current state."""
        items = []

        if search_query:
            # Flatten all projects matching query into a single card
            q = search_query.lower()
            matching = []
            for section in self._sections:
                for proj in section["projects"]:
                    if q in proj["name"].lower():
                        matching.append(proj)
            if matching:
                card_h = CARD_PAD_Y * 2
                for i, proj in enumerate(matching):
                    if i > 0:
                        card_h += DIVIDER_H
                    card_h += PROJECT_ROW_H
                items.append({
                    "kind": "search_card",
                    "projects": matching,
                    "card_height": card_h,
                })
            return items

        # New Tab section
        items.append({"kind": "new_tab_header"})
        items.append({"kind": "new_tab_card"})

        # Running section
        if self._running:
            items.append({
                "kind": "running_header",
                "count": len(self._running),
            })
            items.append({
                "kind": "running_card",
                "names": sorted(self._running),
            })

        # Section groups
        sorted_sects = sort_sections(self._sections, self._pins)
        for section in sorted_sects:
            sorted_projs = sort_projects(section["projects"], self._pins)
            if not sorted_projs:
                continue

            items.append({
                "kind": "section_header",
                "section": section,
            })

            # Compute card height
            card_h = CARD_PAD_Y * 2
            for i, proj in enumerate(sorted_projs):
                if i > 0:
                    card_h += DIVIDER_H
                card_h += PROJECT_ROW_H
                if proj["name"] in self._expanded and proj.get("subdirs"):
                    card_h += len(proj["subdirs"]) * SUBDIR_ROW_H

            items.append({
                "kind": "section_card",
                "projects": sorted_projs,
                "section_name": section["name"],
                "card_height": card_h,
            })

        return items

    def _compute_total_height(self, render_items, card_w):
        """Compute total content height."""
        h = 10  # top padding
        for item in render_items:
            kind = item["kind"]
            if kind in ("new_tab_header", "running_header", "section_header"):
                h += HEADER_H + HEADER_GAP
            elif kind == "new_tab_card":
                h += CARD_PAD_Y * 2 + 32 + SECTION_GAP
            elif kind == "running_card":
                h += 36 + SECTION_GAP
            elif kind in ("section_card", "search_card"):
                h += item["card_height"] + SECTION_GAP
        return h + 10  # bottom padding

    # ── Row builders ──

    def _build_project_row(self, proj, card_w, y, parent_view, highlight):
        """Build a project row inside a card and add to parent_view."""
        x_offset = CARD_INNER_PAD_X

        # Pin button — vertically centered with text
        pin_btn = self._make_pin_button(
            NSMakeRect(x_offset, y, 20, 20),
            proj["name"],
            self._next_tag()
        )
        self._register_pin_tag(pin_btn.tag(), proj["name"])
        parent_view.addSubview_(pin_btn)
        x_offset += 24

        # Badge + Name as attributed string label (NOT a button, just visual)
        badge = proj["badge"]
        attr_str = NSMutableAttributedString.alloc().init()
        badge_part = NSAttributedString.alloc().initWithString_attributes_(
            badge + "  ", {
                NSFontAttributeName: NSFont.systemFontOfSize_(11),
                NSForegroundColorAttributeName: badge_color_for(badge),
            }
        )
        attr_str.appendAttributedString_(badge_part)
        name_part = NSAttributedString.alloc().initWithString_attributes_(
            proj["name"], {
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(13),
                NSForegroundColorAttributeName: NSColor.labelColor(),
            }
        )
        attr_str.appendAttributedString_(name_part)
        name_label = self._make_attr_label(attr_str, NSMakeRect(x_offset, y, card_w - x_offset - 80, PROJECT_ROW_H))
        parent_view.addSubview_(name_label)

        # Plus label "+" — right aligned, same y as row
        plus_label = self._make_label("+", NSFont.systemFontOfSize_(14), NSColor.secondaryLabelColor(),
            NSMakeRect(card_w - 64, y, 18, PROJECT_ROW_H))
        parent_view.addSubview_(plus_label)

        # Toggle label "N ↑" or "N ↓" — flush right, gap after plus
        has_subdirs = bool(proj.get("subdirs"))
        if has_subdirs:
            is_expanded = proj["name"] in self._expanded
            count = len(proj["subdirs"])
            indicator = f"{count} \u2191" if is_expanded else f"{count} \u2193"
            toggle_label = self._make_label(indicator, NSFont.systemFontOfSize_(10), NSColor.tertiaryLabelColor(),
                NSMakeRect(card_w - 42, y + 2, 40, PROJECT_ROW_H))
            toggle_label.setAlignment_(2)  # Right
            toggle_label.cell().setLineBreakMode_(5)  # Truncate tail, no wrap
            toggle_label.cell().setWraps_(False)
            parent_view.addSubview_(toggle_label)

        # ONE transparent button covering the whole row (except pin area)
        row_btn = NSButton.alloc().initWithFrame_(NSMakeRect(CARD_INNER_PAD_X + 24, y, card_w - CARD_INNER_PAD_X - 28, PROJECT_ROW_H))
        row_btn.setTransparent_(True)
        row_btn.setBordered_(False)
        row_btn.setTarget_(self)
        row_btn.setAction_("projectRowClicked:")
        tag = self._next_tag()
        row_btn.setTag_(tag)
        self._register_project_tag(tag, proj["name"], proj["path"])
        parent_view.addSubview_(row_btn)

        self._selectable_items.append({
            "type": "project",
            "name": proj["name"],
            "path": proj["path"],
            "highlight_view": highlight,
        })

    def _build_subdir_row(self, sd, card_w, y, parent_view):
        """Build a subdirectory row inside a card and add to parent_view.
        Clicking the name opens the subdir in iTerm2 (3/4 pane layout).
        """
        indent = CARD_INNER_PAD_X + 30
        x = indent

        # Pin button
        pin_key = "sub:" + sd["path"]
        pin_btn = self._make_pin_button(
            NSMakeRect(x, y + (SUBDIR_ROW_H - 16) // 2, 16, 16),
            pin_key, self._next_tag()
        )
        self._register_pin_tag(pin_btn.tag(), pin_key)
        parent_view.addSubview_(pin_btn)
        x += 20

        # Badge + Name combined in one button for horizontal alignment
        sub_badge = get_layout_badge(sd["path"])
        attr_str = NSMutableAttributedString.alloc().init()
        badge_part = NSAttributedString.alloc().initWithString_attributes_(
            sub_badge + "  ", {
                NSFontAttributeName: NSFont.systemFontOfSize_(9),
                NSForegroundColorAttributeName: badge_color_for(sub_badge),
            }
        )
        attr_str.appendAttributedString_(badge_part)
        name_part = NSAttributedString.alloc().initWithString_attributes_(
            sd["name"], {
                NSFontAttributeName: NSFont.systemFontOfSize_(12),
                NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
            }
        )
        attr_str.appendAttributedString_(name_part)

        name_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(x, y, card_w - x - 90, SUBDIR_ROW_H)
        )
        name_btn.setBordered_(False)
        name_btn.setAttributedTitle_(attr_str)
        name_btn.setAlignment_(0)  # Left
        name_btn.setTarget_(self)
        name_btn.setAction_("subdirLaunchClicked:")
        tag = self._next_tag()
        name_btn.setTag_(tag)
        self._register_project_tag(tag, sd["name"], sd["path"])
        parent_view.addSubview_(name_btn)

        # Finder 📂 button
        finder_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(card_w - 80, y + (SUBDIR_ROW_H - 18) // 2, 22, 18)
        )
        finder_btn.setBordered_(False)
        finder_btn.setTitle_("\U0001F4C2")
        finder_btn.setFont_(NSFont.systemFontOfSize_(14))
        finder_btn.setTarget_(self)
        finder_btn.setAction_("finderBtnClicked:")
        tag = self._next_tag()
        finder_btn.setTag_(tag)
        self._register_path_tag(tag, sd["path"])
        parent_view.addSubview_(finder_btn)

        # Cursor text button
        cursor_btn = NSButton.alloc().initWithFrame_(
            NSMakeRect(card_w - 54, y + (SUBDIR_ROW_H - 18) // 2, 48, 18)
        )
        cursor_btn.setBordered_(False)
        cursor_btn.setAttributedTitle_(
            NSAttributedString.alloc().initWithString_attributes_(
                "Cursor", {
                    NSFontAttributeName: NSFont.systemFontOfSize_(11),
                    NSForegroundColorAttributeName: NSColor.secondaryLabelColor(),
                }
            )
        )
        cursor_btn.setTarget_(self)
        cursor_btn.setAction_("cursorBtnClicked:")
        tag = self._next_tag()
        cursor_btn.setTag_(tag)
        self._register_path_tag(tag, sd["path"])
        parent_view.addSubview_(cursor_btn)

    # ── Tag registry for button actions ──

    _tag_counter = 1000
    _pin_tags = {}       # tag -> pin_key
    _project_tags = {}   # tag -> (name, path)
    _path_tags = {}      # tag -> path

    def _next_tag(self):
        PickerDelegate._tag_counter += 1
        return PickerDelegate._tag_counter

    def _register_pin_tag(self, tag, pin_key):
        PickerDelegate._pin_tags[tag] = pin_key

    def _register_project_tag(self, tag, name, path):
        PickerDelegate._project_tags[tag] = (name, path)

    def _register_path_tag(self, tag, path):
        PickerDelegate._path_tags[tag] = path

    def _clear_tag_registries(self):
        PickerDelegate._tag_counter = 1000
        PickerDelegate._pin_tags = {}
        PickerDelegate._project_tags = {}
        PickerDelegate._path_tags = {}

    # ── Button actions ──

    def newTabClicked_(self, sender):
        tag = sender.tag()
        sentinel = PickerDelegate._path_tags.get(tag, NEW_TAB_SENTINEL + ":2")
        # Extract pane count from sentinel like "__NEW_TAB__:2"
        if ":" in sentinel:
            pane_count = sentinel.split(":")[-1]
        else:
            pane_count = "2"
        self._selected = (f"New Tab {pane_count}", f"{NEW_TAB_SENTINEL}:{pane_count}")
        NSApplication.sharedApplication().stopModal()
        self._panel.close()

    def projectRowClicked_(self, sender):
        tag = sender.tag()
        info = PickerDelegate._project_tags.get(tag)
        if not info:
            return
        name, path = info

        # Get click position within the button
        event = NSApplication.sharedApplication().currentEvent()
        click_pt = sender.convertPoint_fromView_(event.locationInWindow(), None)
        btn_w = sender.frame().size.width

        # Right 38px: toggle expand (toggle label at card_w - 42)
        if click_pt.x > btn_w - 38:
            for section in self._sections:
                for proj in section["projects"]:
                    if proj["name"] == name and proj.get("subdirs"):
                        if name in self._expanded:
                            self._expanded.discard(name)
                        else:
                            self._expanded.add(name)
                        self._clear_tag_registries()
                        self.rebuild_ui()
                        return
            return

        # Next area: plus (create subdir) (plus label at card_w - 64)
        if click_pt.x > btn_w - 60:
            for section in self._sections:
                for proj in section["projects"]:
                    if proj["name"] == name:
                        self._show_create_dialog(proj["path"], "subdirectory")
                        return
            return

        # Rest: launch project
        self._selected = (name, path)
        NSApplication.sharedApplication().stopModal()
        self._panel.close()

    def sectionPlusClicked_(self, sender):
        tag = sender.tag()
        section_path = PickerDelegate._path_tags.get(tag)
        if section_path:
            self._show_create_dialog(section_path, "project")

    def _show_create_dialog(self, parent_path, kind):
        """Show NSAlert with text input to create a new directory."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_(f"Create new {kind}")
        alert.setInformativeText_(f"in {os.path.basename(parent_path)}")
        alert.addButtonWithTitle_("Create")
        alert.addButtonWithTitle_("Cancel")

        input_field = NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 260, 24))
        input_field.setPlaceholderString_(f"Enter {kind} name...")
        alert.setAccessoryView_(input_field)
        alert.window().setInitialFirstResponder_(input_field)

        response = alert.runModal()
        if response == 1000:  # NSAlertFirstButtonReturn
            dir_name = input_field.stringValue().strip()
            if dir_name:
                new_path = os.path.join(parent_path, dir_name)
                try:
                    os.makedirs(new_path, exist_ok=True)
                    # Rescan and rebuild
                    self._sections = scan_sections()
                    pins = load_pins()
                    self._sections = sort_sections(self._sections, pins)
                    for section in self._sections:
                        section["projects"] = sort_projects(section["projects"], pins)
                    # Add to expanded if it has subdirs now
                    for section in self._sections:
                        for proj in section["projects"]:
                            if proj.get("subdirs"):
                                self._expanded.add(proj["name"])
                    self._clear_tag_registries()
                    self.rebuild_ui()
                except OSError:
                    pass

    def subdirLaunchClicked_(self, sender):
        """Launch a subdirectory in iTerm2 with 3/4 pane layout."""
        tag = sender.tag()
        info = PickerDelegate._project_tags.get(tag)
        if info:
            name, path = info
            self._selected = (name, path)
            NSApplication.sharedApplication().stopModal()
            self._panel.close()

    def finderBtnClicked_(self, sender):
        tag = sender.tag()
        path = PickerDelegate._path_tags.get(tag, "")
        if path and path != NEW_TAB_SENTINEL:
            NSWorkspace.sharedWorkspace().openFile_(path)

    def cursorBtnClicked_(self, sender):
        tag = sender.tag()
        path = PickerDelegate._path_tags.get(tag, "")
        if path and path != NEW_TAB_SENTINEL:
            subprocess.Popen(["/usr/local/bin/cursor", path])

    def pinBtnClicked_(self, sender):
        tag = sender.tag()
        pin_key = PickerDelegate._pin_tags.get(tag)
        if pin_key:
            toggle_pin(pin_key)
            self._pins = load_pins()
            self._clear_tag_registries()
            self.rebuild_ui()

    # ── Live search filtering ──

    def controlTextDidChange_(self, notification):
        field = notification.object()
        query = field.stringValue().strip()
        self._searching = bool(query)
        self._clear_tag_registries()
        self.rebuild_ui()

    # ── Keyboard handling in search field ──

    def control_textView_doCommandBySelector_(self, control, tv, selector):
        sel_name = selector
        if hasattr(selector, "decode"):
            sel_name = selector.decode("ascii")
        else:
            sel_name = str(selector)

        if sel_name == "insertNewline:":
            # Launch currently highlighted item
            if 0 <= self._selected_index < len(self._selectable_items):
                item = self._selectable_items[self._selected_index]
                self._selected = (item["name"], item["path"])
                NSApplication.sharedApplication().stopModal()
                self._panel.close()
                return True
            elif self._selectable_items:
                item = self._selectable_items[0]
                self._selected = (item["name"], item["path"])
                NSApplication.sharedApplication().stopModal()
                self._panel.close()
                return True
            return True

        if sel_name == "moveDown:":
            if self._selectable_items:
                if self._selected_index < len(self._selectable_items) - 1:
                    self._selected_index += 1
                else:
                    self._selected_index = 0
                self._update_highlight()
                self._scroll_to_selected()
            return True

        if sel_name == "moveUp:":
            if self._selectable_items:
                if self._selected_index > 0:
                    self._selected_index -= 1
                else:
                    self._selected_index = len(self._selectable_items) - 1
                self._update_highlight()
                self._scroll_to_selected()
            return True

        if sel_name == "cancelOperation:":
            NSApplication.sharedApplication().stopModal()
            self._panel.close()
            return True

        return False

    def _scroll_to_selected(self):
        """Scroll to make the currently selected item visible."""
        if 0 <= self._selected_index < len(self._selectable_items):
            item = self._selectable_items[self._selected_index]
            view = item.get("highlight_view")
            if view is not None:
                # Convert the highlight view's frame to content view coordinates
                frame = view.frame()
                superview = view.superview()
                if superview and superview != self._content_view:
                    # The highlight is inside a card's contentView - convert coords
                    card_frame = superview.superview().frame() if superview.superview() else superview.frame()
                    scroll_rect = NSMakeRect(
                        0, card_frame.origin.y + frame.origin.y - 10,
                        frame.size.width, frame.size.height + 20
                    )
                    self._content_view.scrollRectToVisible_(scroll_rect)

    # ── Window close ──

    def windowWillClose_(self, notification):
        NSApplication.sharedApplication().stopModal()


class FlippedView(NSView):
    """An NSView subclass that flips the coordinate system (origin at top-left)."""

    def isFlipped(self):
        return True

    def acceptsFirstMouse_(self, event):
        return True


def show_picker(sections, running_projects):
    """Show native macOS Spotlight/Raycast-style picker. Returns (name, path) or None."""
    pins = load_pins()

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(0)  # Regular — allows windows

    W, H = PANEL_WIDTH, PANEL_HEIGHT

    # ── Panel ──
    style = 1 | 2  # Titled | Closable
    panel = PickerPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(0, 0, W, H), style, NSBackingStoreBuffered, False,
    )
    panel.setTitle_("Project Launcher")
    panel.center()
    panel.setLevel_(NSFloatingWindowLevel)
    panel.setMovableByWindowBackground_(True)
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setHasShadow_(True)
    panel.setReleasedWhenClosed_(False)

    # ── Dark vibrant appearance ──
    dark = NSAppearance.appearanceNamed_("NSAppearanceNameVibrantDark")
    panel.setAppearance_(dark)

    # ── Translucent background ──
    content = panel.contentView()
    vfx = NSVisualEffectView.alloc().initWithFrame_(content.bounds())
    vfx.setAutoresizingMask_(18)
    vfx.setBlendingMode_(0)       # Behind window
    vfx.setMaterial_(6)           # Popover — dark translucent
    vfx.setState_(1)              # Always active
    content.addSubview_(vfx)

    # ── Delegate ──
    delegate = PickerDelegate.alloc().init()
    delegate._sections = sections
    delegate._pins = pins
    delegate._running = running_projects
    delegate._panel = panel
    delegate._expanded = set()
    delegate._searching = False
    panel.setDelegate_(delegate)

    # ── Search field ──
    search = NSSearchField.alloc().initWithFrame_(
        NSMakeRect(20, H - 50, W - 40, 28)
    )
    search.setPlaceholderString_("Search projects...")
    search.setFont_(NSFont.systemFontOfSize_(14))
    search.setDelegate_(delegate)
    delegate._search_field = search
    vfx.addSubview_(search)

    # ── Scroll view ──
    scroll_h = H - 80
    scroll = NSScrollView.alloc().initWithFrame_(
        NSMakeRect(20, 15, W - 40, scroll_h)
    )
    scroll.setHasVerticalScroller_(True)
    scroll.setDrawsBackground_(False)
    scroll.setBorderType_(0)
    scroll.setAutohidesScrollers_(True)
    delegate._scroll_view = scroll

    # Initial content view
    content_view = FlippedView.alloc().initWithFrame_(
        NSMakeRect(0, 0, W - 40, scroll_h)
    )
    delegate._content_view = content_view
    scroll.setDocumentView_(content_view)
    vfx.addSubview_(scroll)

    # Build UI
    delegate._clear_tag_registries()
    delegate.rebuild_ui()

    # ── Key view loop ──
    search.setNextKeyView_(search)
    panel.setInitialFirstResponder_(search)

    # ── Show and run ──
    panel.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)
    NSApplication.sharedApplication().runModalForWindow_(panel)

    return delegate._selected


# ──────────────────────────────────────────────
# PANE LAYOUTS
# ──────────────────────────────────────────────

async def create_two_pane_layout(tab):
    """
    2-pane layout — plain new tab at home directory.
    ┌──────────┬──────────┐
    │  Pane 1  │  Pane 2  │
    │   ~/     │   ~/     │
    └──────────┴──────────┘
    """
    home = os.path.expanduser("~")
    session_left = tab.current_session
    await session_left.async_send_text(f"cd '{home}'\n")
    await session_left.async_split_pane(vertical=True)


async def create_one_pane_layout(tab):
    """1-pane layout — single pane at home directory."""
    home = os.path.expanduser("~")
    await tab.current_session.async_send_text(f"cd '{home}'\n")


async def create_three_pane_new_tab(tab):
    """
    3-pane layout — new tab at home directory.
    ┌──────────┬──────────┐
    │          │  Right   │
    │  Left    ├──────────┤
    │          │  R-Bot   │
    └──────────┴──────────┘
    """
    home = os.path.expanduser("~")
    left = tab.current_session
    await left.async_send_text(f"cd '{home}'\n")
    right = await left.async_split_pane(vertical=True)
    await right.async_send_text(f"cd '{home}'\n")
    await right.async_split_pane(vertical=False)


async def create_four_pane_new_tab(tab):
    """
    4-pane layout — new tab at home directory (2x2 grid).
    ┌──────────┬──────────┐
    │  Top-L   │  Top-R   │
    ├──────────┼──────────┤
    │  Bot-L   │  Bot-R   │
    └──────────┴──────────┘
    """
    home = os.path.expanduser("~")
    left = tab.current_session
    await left.async_send_text(f"cd '{home}'\n")
    right = await left.async_split_pane(vertical=True)
    await right.async_send_text(f"cd '{home}'\n")
    await left.async_split_pane(vertical=False)
    await right.async_split_pane(vertical=False)


async def create_four_pane_layout(tab, structure, commands, project_name):
    """
    4-pane layout — project uses Celery.
    ┌──────────┬──────────┐
    │ Frontend │ Backend  │
    ├──────────┼──────────┤
    │  Celery  │  Shell   │
    └──────────┴──────────┘
    """
    fe_dir = structure["frontend_dir"]
    be_dir = structure["backend_dir"]

    session_frontend = tab.current_session
    await session_frontend.async_set_name(f"{project_name} \u2014 Frontend")
    await session_frontend.async_send_text(f"cd '{fe_dir}' && {commands['frontend']}\n")

    session_backend = await session_frontend.async_split_pane(vertical=True)
    await session_backend.async_set_name(f"{project_name} \u2014 Backend")
    await session_backend.async_send_text(f"cd '{be_dir}' && {commands['backend']}\n")

    session_celery = await session_frontend.async_split_pane(vertical=False)
    await session_celery.async_set_name(f"{project_name} \u2014 Celery")
    await session_celery.async_send_text(f"cd '{be_dir}' && {commands['celery']}\n")

    session_shell = await session_backend.async_split_pane(vertical=False)
    await session_shell.async_set_name(f"{project_name} \u2014 Shell")
    await session_shell.async_send_text(f"cd '{be_dir}' && {commands['shell']}\n")

    await tab.async_set_title(project_name)


async def create_three_pane_layout(tab, structure, commands, project_name):
    """
    3-pane layout — project does NOT use Celery.
    ┌──────────┬──────────┐
    │ Frontend │ Backend  │
    │          ├──────────┤
    │          │  Shell   │
    └──────────┴──────────┘
    """
    fe_dir = structure["frontend_dir"]
    be_dir = structure["backend_dir"]

    session_frontend = tab.current_session
    await session_frontend.async_set_name(f"{project_name} \u2014 Frontend")
    await session_frontend.async_send_text(f"cd '{fe_dir}' && {commands['frontend']}\n")

    session_backend = await session_frontend.async_split_pane(vertical=True)
    await session_backend.async_set_name(f"{project_name} \u2014 Backend")
    await session_backend.async_send_text(f"cd '{be_dir}' && {commands['backend']}\n")

    session_shell = await session_backend.async_split_pane(vertical=False)
    await session_shell.async_set_name(f"{project_name} \u2014 Shell")
    await session_shell.async_send_text(f"cd '{be_dir}' && {commands['shell']}\n")

    await tab.async_set_title(project_name)


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────

def run():
    # 1. Scan sections/projects/subdirs
    sections = scan_sections()

    if not sections:
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(0)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("No Projects Found")
        alert.setInformativeText_(
            "No projects found in " + PROJECT_ROOT + ".\n"
            "Ensure the directory contains section folders (e.g. Pixeldust, Personal) "
            "with project subdirectories inside."
        )
        alert.runModal()
        return

    # 2. Sort sections/projects by pins + frequency
    pins = load_pins()
    sections = sort_sections(sections, pins)
    for section in sections:
        section["projects"] = sort_projects(section["projects"], pins)
        for proj in section["projects"]:
            proj["subdirs"] = sort_subdirs(proj["subdirs"], pins)

    # 3. Detect running projects
    running = detect_running_projects()

    # 4. Show picker
    selected = show_picker(sections, running)

    if not selected:
        return

    display_name, project_path = selected

    # 5. Handle "New Tab"
    if project_path.startswith(NEW_TAB_SENTINEL):
        pane_count = 2  # default
        if ":" in project_path:
            try:
                pane_count = int(project_path.split(":")[-1])
            except ValueError:
                pane_count = 2

        async def setup_new_tab(connection):
            app = await iterm2.async_get_app(connection)
            window = app.current_window
            if window is None:
                window = await iterm2.Window.async_create(connection)
            else:
                await window.async_create_tab()
            tab = window.current_tab
            if pane_count == 1:
                await create_one_pane_layout(tab)
            elif pane_count == 3:
                await create_three_pane_new_tab(tab)
            elif pane_count == 4:
                await create_four_pane_new_tab(tab)
            else:
                await create_two_pane_layout(tab)

        iterm2.run_until_complete(setup_new_tab)
        return

    # 6. Handle project selection
    project_name = display_name.split("/")[-1] if "/" in display_name else display_name
    record_usage(display_name)

    structure = detect_structure(project_path)
    commands = get_commands(project_name)

    async def setup(connection):
        app = await iterm2.async_get_app(connection)
        window = app.current_window
        if window is None:
            window = await iterm2.Window.async_create(connection)
        else:
            await window.async_create_tab()

        tab = window.current_tab

        if structure["has_celery"]:
            await create_four_pane_layout(tab, structure, commands, project_name)
        else:
            await create_three_pane_layout(tab, structure, commands, project_name)

    iterm2.run_until_complete(setup)


run()
