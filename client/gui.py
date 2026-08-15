"""
AFV Tracker - Main GUI
PyQt6 desktop application for Africana Virtual Airways pilots.
Dark aviation theme: black + AFV red (#C41E3A) + white.
"""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional

from PyQt6.QtCore import Qt, QTimer, pyqtSlot, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QPixmap, QPainter, QPen, QBrush
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit, QFrame, QSplitter, QStatusBar,
    QDialog, QDialogButtonBox, QFormLayout, QMessageBox, QScrollArea,
    QGridLayout, QSizePolicy, QMenu, QSystemTrayIcon,
)

import config
from simbrief import fetch_ofp, SimBriefError, OFP
from simconnect_client import SimConnectWorker, Telemetry
from flight_tracker import FlightTracker, FlightPhase, haversine_nm
from gate_manager import GateManager, GateAssignment
from network_client import NetworkClient
from discord_presence import DiscordPresenceWorker
from phpvms_sync_worker import PhpVmsSyncWorker
import sounds

from phpvms_integration import PhpVmsClient

log = logging.getLogger(__name__)

# ── Palette constants ──────────────────────────────────────────────────────────
# Two full palettes; the active one is selected once at import time from the
# saved config. Every other line in this file references the plain constant
# names below (BG_PRIMARY, etc.), so switching themes needs no other changes —
# it just takes a restart to re-import this module with the new selection.
_PALETTE_DARK = {
    "BG_PRIMARY":      "#0D0D0D",
    "BG_SECONDARY":    "#1A1A1A",
    "BG_PANEL":        "#242424",
    "BG_INPUT":        "#2A2A2A",
    "ACCENT_RED":      "#C41E3A",
    "ACCENT_RED_DARK": "#9E1830",
    "TEXT_PRIMARY":    "#FFFFFF",
    "TEXT_SECONDARY":  "#A0A0A0",
    "BORDER":          "#2A2A2A",
    "SUCCESS":         "#22C55E",
    "WARNING":         "#F59E0B",
}

_PALETTE_LIGHT = {
    "BG_PRIMARY":      "#F5F5F7",
    "BG_SECONDARY":    "#FFFFFF",
    "BG_PANEL":        "#FFFFFF",
    "BG_INPUT":        "#EDEDF0",
    "ACCENT_RED":      "#C41E3A",
    "ACCENT_RED_DARK": "#9E1830",
    "TEXT_PRIMARY":    "#1A1A1A",
    "TEXT_SECONDARY":  "#5A5A5A",
    "BORDER":          "#DADADD",
    "SUCCESS":         "#16A34A",
    "WARNING":         "#D97706",
}

_active_palette = _PALETTE_LIGHT if config.get("theme", "dark") == "light" else _PALETTE_DARK

BG_PRIMARY      = _active_palette["BG_PRIMARY"]
BG_SECONDARY    = _active_palette["BG_SECONDARY"]
BG_PANEL        = _active_palette["BG_PANEL"]
BG_INPUT        = _active_palette["BG_INPUT"]
ACCENT_RED      = _active_palette["ACCENT_RED"]
ACCENT_RED_DARK = _active_palette["ACCENT_RED_DARK"]
TEXT_PRIMARY    = _active_palette["TEXT_PRIMARY"]
TEXT_SECONDARY  = _active_palette["TEXT_SECONDARY"]
BORDER          = _active_palette["BORDER"]
SUCCESS         = _active_palette["SUCCESS"]
WARNING         = _active_palette["WARNING"]

FONT_MONO  = "JetBrains Mono, Consolas, Courier New, monospace"
FONT_LABEL = "Segoe UI, Arial, sans-serif"

LBS_TO_KG = 0.453592


def _fmt_weight(lbs: float) -> str:
    """Format a weight value using the user's configured unit."""
    unit = config.get("weight_unit", "LBS")
    if unit == "KG":
        return f"{lbs * LBS_TO_KG:,.0f} kg"
    return f"{lbs:,.0f} lbs"


def _weight_unit_label() -> str:
    return config.get("weight_unit", "LBS")


def _label(text: str, color: str = TEXT_SECONDARY, size: int = 11,
           bold: bool = False, font: str = FONT_LABEL) -> QLabel:
    lbl = QLabel(text)
    weight = "bold" if bold else "normal"
    lbl.setStyleSheet(
        f"color: {color}; font-size: {size}px; font-weight: {weight};"
        f"font-family: {font}; background: transparent;"
    )
    return lbl


def _sep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    line.setStyleSheet(f"color: {BORDER}; background: {BORDER};")
    line.setFixedHeight(1)
    return line


def _panel(parent=None) -> QFrame:
    f = QFrame(parent)
    f.setStyleSheet(
        f"QFrame {{ background: {BG_SECONDARY}; border: 1px solid {BORDER};"
        f"border-radius: 6px; }}"
    )
    return f


# ── Pilot ID dialog ────────────────────────────────────────────────────────────

class PilotSetupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AFV — Pilot Setup")
        self.setModal(True)
        self.setMinimumSize(420, 660)
        self.resize(420, 660)
        self.setStyleSheet(f"""
            QDialog {{
                background: {BG_PRIMARY};
                border: 1px solid #1F1F1F;
            }}
            QLabel {{
                color: {TEXT_SECONDARY};
                font-family: {FONT_LABEL};
                font-size: 11px;
                background: transparent;
            }}
        """)

        root = QVBoxLayout(self)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header bar ────────────────────────────────
        header = QFrame()
        header.setFixedHeight(78)
        header.setStyleSheet(
            f"background: {ACCENT_RED}; border-bottom: 1px solid {ACCENT_RED_DARK};"
        )
        h_row = QVBoxLayout(header)
        h_row.setContentsMargins(20, 14, 20, 14)
        h_row.setSpacing(3)

        lbl_title = QLabel("PILOT SETUP")
        lbl_title.setStyleSheet(
            f"color: white; font-size: 16px; font-weight: 700; "
            f"font-family: {FONT_LABEL}; letter-spacing: 2px;"
        )
        lbl_subtitle = QLabel("VATSIM, SimBrief and display preferences")
        lbl_subtitle.setStyleSheet(
            "color: #F2D7DD;"
            f"font-size: 11px; font-family: {FONT_LABEL};"
        )

        h_row.addWidget(lbl_title)
        h_row.addWidget(lbl_subtitle)
        h_row.addStretch()
        root.addWidget(header)

        # ── Form body ─────────────────────────────────
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 16)

        form_panel = QFrame()
        form_panel.setStyleSheet(
            f"QFrame {{"
            f"background: {BG_SECONDARY};"
                f"border: 1px solid #2A2A2A;"
                f"border-radius: 10px;"
            f"}}"
        )
        form_layout = QVBoxLayout(form_panel)
        form_layout.setSpacing(10)
        form_layout.setContentsMargins(18, 16, 18, 16)

        def _styled_input(widget):
            """Apply dark-theme styling directly — no selector, so Qt can't override it."""
            widget.setStyleSheet(
                "QLineEdit {"
                f"background-color: {BG_INPUT};"
                f"color: {TEXT_PRIMARY};"
                "border: 1px solid #4A4A4A;"
                "border-radius: 6px;"
                "padding: 8px 12px;"
                "font-size: 13px;"
                f"font-family: {FONT_MONO};"
                f"selection-background-color: {ACCENT_RED};"
                "selection-color: white;"
                "}"
                "QLineEdit:hover {"
                "border-color: #6A6A6A;"
                "}"
                "QLineEdit:focus {"
                f"border: 1px solid {ACCENT_RED};"
                f"background-color: {BG_INPUT};"
                "}"
            )
            # Also set the palette so native platform styling does not wash out the field.
            from PyQt6.QtGui import QPalette, QColor
            pal = widget.palette()
            pal.setColor(QPalette.ColorRole.Text, QColor(TEXT_PRIMARY))
            pal.setColor(QPalette.ColorRole.Base, QColor(BG_INPUT))
            pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#6B7280"))
            widget.setPalette(pal)
            widget.setFixedHeight(36)

        def _field(label_text, widget):
            label = _label(label_text.upper(), "#8F96A3", 10, bold=True)
            label.setStyleSheet(label.styleSheet() + "letter-spacing: 1.6px;")
            form_layout.addWidget(label)
            _styled_input(widget)
            form_layout.addWidget(widget)

        self.vatsim_edit = QLineEdit()
        self.vatsim_edit.setPlaceholderText("e.g. 1234567")
        saved_cid = config.get("vatsim_cid", "")
        if saved_cid:
            self.vatsim_edit.setText(saved_cid)
        _field("VATSIM CID", self.vatsim_edit)

        self.simbrief_edit = QLineEdit()
        self.simbrief_edit.setPlaceholderText("username or numeric ID")
        saved_sb = config.get("simbrief_id", "")
        if saved_sb:
            self.simbrief_edit.setText(saved_sb)
        _field("SimBrief ID", self.simbrief_edit)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. John Doe")
        saved_name = config.get("pilot_name", "")
        if saved_name:
            self.name_edit.setText(saved_name)
        _field("Pilot Name", self.name_edit)

        self.discord_edit = QLineEdit()
        self.discord_edit.setPlaceholderText("e.g. johndoe")
        saved_discord = config.get("discord", "")
        if saved_discord:
            self.discord_edit.setText(saved_discord)
        _field("Discord", self.discord_edit)

        self.va_url_edit = QLineEdit()
        self.va_url_edit.setPlaceholderText("https://africanava.ddns.net")
        self.va_url_edit.setText(config.get("VA_URL", "https://africanava.ddns.net"))
        _field("phpVMS Airline URL", self.va_url_edit)

        self.pilot_key_edit = QLineEdit()
        self.pilot_key_edit.setPlaceholderText("v7 API Key")
        self.pilot_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.pilot_key_edit.setText(config.get("Pilot_Key", ""))
        _field("Pilot API Key", self.pilot_key_edit)

        unit_panel = QFrame()
        unit_panel.setStyleSheet(
            "QFrame {"
            "background: #181818;"
            "border: 1px solid #2C2C2C;"
            "border-radius: 8px;"
            "}"
        )
        unit_panel_layout = QHBoxLayout(unit_panel)
        unit_panel_layout.setContentsMargins(12, 10, 12, 10)
        unit_panel_layout.setSpacing(10)

        unit_text = QVBoxLayout()
        unit_text.setContentsMargins(0, 0, 0, 0)
        unit_text.setSpacing(2)
        unit_title = _label("WEIGHT UNIT", "#8F96A3", 10, bold=True)
        unit_title.setStyleSheet(unit_title.styleSheet() + "letter-spacing: 1.6px;")
        unit_hint = QLabel("Choose how weights are shown in the app")
        unit_hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-family: {FONT_LABEL};"
        )
        unit_text.addWidget(unit_title)
        unit_text.addWidget(unit_hint)

        toggle_row = QHBoxLayout()
        toggle_row.setContentsMargins(0, 0, 0, 0)
        toggle_row.setSpacing(0)

        saved_unit = config.get("weight_unit", "LBS")
        self._btn_lbs = QPushButton("  LBS  ")
        self._btn_kg = QPushButton("  KG  ")
        self._btn_lbs.setCheckable(True)
        self._btn_kg.setCheckable(True)
        self._btn_lbs.setFixedHeight(34)
        self._btn_kg.setFixedHeight(34)
        self._btn_lbs.setMinimumWidth(68)
        self._btn_kg.setMinimumWidth(68)
        self._btn_lbs.setChecked(saved_unit == "LBS")
        self._btn_kg.setChecked(saved_unit == "KG")

        def _toggle_style(active: bool) -> str:
            bg = ACCENT_RED if active else BG_INPUT
            border = ACCENT_RED if active else "#333333"
            text = TEXT_PRIMARY if active else TEXT_SECONDARY
            weight = "700" if active else "500"
            return (
                "QPushButton {"
                f"background: {bg};"
                f"color: {text};"
                f"border: 1px solid {border};"
                "border-radius: 6px;"
                "padding: 0 16px;"
                f"font-size: 12px; font-weight: {weight}; font-family: {FONT_LABEL};"
                "}"
                "QPushButton:hover {"
                f"border-color: {ACCENT_RED};"
                "}"
            )

        def _apply_unit_styles():
            self._btn_lbs.setStyleSheet(_toggle_style(self._btn_lbs.isChecked()))
            self._btn_kg.setStyleSheet(_toggle_style(self._btn_kg.isChecked()))

        def _select_lbs():
            self._btn_lbs.setChecked(True)
            self._btn_kg.setChecked(False)
            _apply_unit_styles()

        def _select_kg():
            self._btn_kg.setChecked(True)
            self._btn_lbs.setChecked(False)
            _apply_unit_styles()

        self._btn_lbs.clicked.connect(_select_lbs)
        self._btn_kg.clicked.connect(_select_kg)
        toggle_row.addWidget(self._btn_lbs)
        toggle_row.addWidget(self._btn_kg)
        unit_panel_layout.addLayout(unit_text, 1)
        unit_panel_layout.addLayout(toggle_row, 0)
        _apply_unit_styles()
        form_layout.addWidget(unit_panel)

        # ── Theme ───────────────────────────────────────
        theme_panel = QFrame()
        theme_panel.setStyleSheet(
            "QFrame {"
            "background: #181818;"
            "border: 1px solid #2C2C2C;"
            "border-radius: 8px;"
            "}"
        )
        theme_panel_layout = QHBoxLayout(theme_panel)
        theme_panel_layout.setContentsMargins(12, 10, 12, 10)
        theme_panel_layout.setSpacing(10)

        theme_text = QVBoxLayout()
        theme_text.setContentsMargins(0, 0, 0, 0)
        theme_text.setSpacing(2)
        theme_title = _label("THEME", "#8F96A3", 10, bold=True)
        theme_title.setStyleSheet(theme_title.styleSheet() + "letter-spacing: 1.6px;")
        theme_hint = QLabel("Takes effect after restarting AFV Tracker")
        theme_hint.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 11px; font-family: {FONT_LABEL};"
        )
        theme_text.addWidget(theme_title)
        theme_text.addWidget(theme_hint)

        theme_toggle_row = QHBoxLayout()
        theme_toggle_row.setContentsMargins(0, 0, 0, 0)
        theme_toggle_row.setSpacing(0)

        saved_theme = config.get("theme", "dark")
        self._btn_dark = QPushButton("  DARK  ")
        self._btn_light = QPushButton("  LIGHT  ")
        self._btn_dark.setCheckable(True)
        self._btn_light.setCheckable(True)
        self._btn_dark.setFixedHeight(34)
        self._btn_light.setFixedHeight(34)
        self._btn_dark.setMinimumWidth(68)
        self._btn_light.setMinimumWidth(68)
        self._btn_dark.setChecked(saved_theme != "light")
        self._btn_light.setChecked(saved_theme == "light")

        def _apply_theme_styles():
            self._btn_dark.setStyleSheet(_toggle_style(self._btn_dark.isChecked()))
            self._btn_light.setStyleSheet(_toggle_style(self._btn_light.isChecked()))

        def _select_dark():
            self._btn_dark.setChecked(True)
            self._btn_light.setChecked(False)
            _apply_theme_styles()

        def _select_light():
            self._btn_light.setChecked(True)
            self._btn_dark.setChecked(False)
            _apply_theme_styles()

        self._btn_dark.clicked.connect(_select_dark)
        self._btn_light.clicked.connect(_select_light)
        theme_toggle_row.addWidget(self._btn_dark)
        theme_toggle_row.addWidget(self._btn_light)
        theme_panel_layout.addLayout(theme_text, 1)
        theme_panel_layout.addLayout(theme_toggle_row, 0)
        _apply_theme_styles()
        form_layout.addWidget(theme_panel)

        # ── Discord Rich Presence / Sound cue toggles ────
        prefs_panel = QFrame()
        prefs_panel.setStyleSheet(
            "QFrame {"
            "background: #181818;"
            "border: 1px solid #2C2C2C;"
            "border-radius: 8px;"
            "}"
        )
        prefs_layout = QVBoxLayout(prefs_panel)
        prefs_layout.setContentsMargins(12, 10, 12, 10)
        prefs_layout.setSpacing(10)

        def _bool_toggle_style(on: bool) -> str:
            bg = ACCENT_RED if on else BG_INPUT
            color = TEXT_PRIMARY if on else TEXT_SECONDARY
            return (
                "QPushButton {"
                f"background: {bg}; color: {color};"
                "border: 1px solid #333333; border-radius: 6px;"
                f"font-size: 10px; font-weight: 700; font-family: {FONT_LABEL};"
                "}"
            )

        def _pref_row(title_text: str, hint_text: str, initial: bool) -> QPushButton:
            row = QHBoxLayout()
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(10)

            text_col = QVBoxLayout()
            text_col.setContentsMargins(0, 0, 0, 0)
            text_col.setSpacing(2)
            title = _label(title_text, "#8F96A3", 10, bold=True)
            title.setStyleSheet(title.styleSheet() + "letter-spacing: 1.6px;")
            hint = QLabel(hint_text)
            hint.setStyleSheet(
                f"color: {TEXT_SECONDARY}; font-size: 11px; font-family: {FONT_LABEL};"
            )
            text_col.addWidget(title)
            text_col.addWidget(hint)

            btn = QPushButton("ON" if initial else "OFF")
            btn.setCheckable(True)
            btn.setChecked(initial)
            btn.setFixedSize(56, 28)
            btn.setStyleSheet(_bool_toggle_style(initial))

            def _on_toggled(checked: bool):
                btn.setText("ON" if checked else "OFF")
                btn.setStyleSheet(_bool_toggle_style(checked))

            btn.toggled.connect(_on_toggled)

            row.addLayout(text_col, 1)
            row.addWidget(btn, 0)
            prefs_layout.addLayout(row)
            return btn

        self._discord_btn = _pref_row(
            "DISCORD RICH PRESENCE",
            "Show your current flight on Discord — restart to apply",
            config.get("discord_rpc_enabled", True),
        )
        self._sound_btn = _pref_row(
            "SOUND CUES",
            "Play a tone on takeoff, landing, and gate assignment",
            config.get("sound_enabled", True),
        )
        form_layout.addWidget(prefs_panel)

        layout.addWidget(form_panel)
        root.addWidget(body, 1)

        # ── Footer buttons ────────────────────────────
        footer = QFrame()
        footer.setStyleSheet(
            "QFrame {"
            f"background: {BG_PRIMARY};"
            "border-top: 1px solid #222222;"
            "}"
        )
        f_row = QHBoxLayout(footer)
        f_row.setContentsMargins(20, 12, 20, 14)
        f_row.setSpacing(10)
        f_row.addStretch()

        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedSize(90, 34)
        btn_cancel.setStyleSheet(
            "QPushButton {"
            f"background: {BG_INPUT}; color: {TEXT_SECONDARY}; "
            "border: 1px solid #333333; border-radius: 6px; "
            f"font-size: 12px; font-family: {FONT_LABEL};"
            "}"
            "QPushButton:hover {"
            "border-color: #555555; color: white;"
            "}"
        )
        btn_cancel.clicked.connect(self.reject)

        btn_ok = QPushButton("Save")
        btn_ok.setFixedSize(90, 34)
        btn_ok.setStyleSheet(
            "QPushButton {"
            f"background: {ACCENT_RED}; color: white; "
            "border: none; border-radius: 6px; "
            f"font-size: 12px; font-weight: 700; font-family: {FONT_LABEL};"
            "}"
            "QPushButton:hover {"
            f"background: {ACCENT_RED_DARK};"
            "}"
        )
        btn_ok.clicked.connect(self.accept)

        f_row.addWidget(btn_cancel)
        f_row.addWidget(btn_ok)
        root.addWidget(footer)

    def get_values(self) -> tuple:
        """
        Returns (vatsim_cid, simbrief_id, pilot_name, discord, weight_unit,
                 va_url, pilot_key, theme, discord_rpc_enabled, sound_enabled).
        """
        unit  = "KG" if self._btn_kg.isChecked() else "LBS"
        theme = "light" if self._btn_light.isChecked() else "dark"
        return (
            self.vatsim_edit.text().strip(),
            self.simbrief_edit.text().strip(),
            self.name_edit.text().strip(),
            self.discord_edit.text().strip(),
            unit,
            self.va_url_edit.text().strip(),
            self.pilot_key_edit.text().strip(),
            theme,
            self._discord_btn.isChecked(),
            self._sound_btn.isChecked(),
        )


# ── Stat widget (label + value pair) ──────────────────────────────────────────

class StatWidget(QWidget):
    def __init__(self, label: str, value: str = "---", unit: str = "",
                 value_size: int = 22, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self._lbl = _label(label, TEXT_SECONDARY, 10)
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._val = _label(value, TEXT_PRIMARY, value_size, bold=True, font=FONT_MONO)
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._unit = _label(unit, TEXT_SECONDARY, 10)
        self._unit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self._lbl)
        layout.addWidget(self._val)
        if unit:
            layout.addWidget(self._unit)

    def set_value(self, v: str):
        self._val.setText(v)

    def set_unit(self, u: str):
        self._unit.setText(u)

    def set_color(self, color: str):
        self._val.setStyleSheet(
            f"color: {color}; font-size: {self._val.font().pointSize()}px;"
            f"font-weight: bold; font-family: {FONT_MONO}; background: transparent;"
        )


# ── Connection indicator dot ───────────────────────────────────────────────────

class ConnDot(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self._base_label = label
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setStyleSheet(f"color: {ACCENT_RED}; font-size: 10px; background: transparent;")
        self._txt = _label(label, TEXT_SECONDARY, 11)
        row.addWidget(self._dot)
        row.addWidget(self._txt)

    def set_connected(self, ok: bool, label: str = ""):
        color = SUCCESS if ok else ACCENT_RED
        display = label if label else self._base_label
        self._txt.setText(display)
        self._dot.setStyleSheet(f"color: {color}; font-size: 10px; background: transparent;")


# ── Gate assignment banner ─────────────────────────────────────────────────────

class GateBanner(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {ACCENT_RED}; border-radius: 8px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        self._icon = _label("✈", TEXT_PRIMARY, 20, bold=True)
        self._header = _label("GATE ASSIGNMENT", TEXT_PRIMARY, 11, bold=True)
        self._header.setAlignment(Qt.AlignmentFlag.AlignLeft)
        top_row.addWidget(self._icon)
        top_row.addSpacing(8)
        top_row.addWidget(self._header)
        top_row.addStretch()
        layout.addLayout(top_row)

        self._gate_label = QLabel("---")
        self._gate_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gate_label.setStyleSheet(
            f"color: {TEXT_PRIMARY}; font-size: 36px; font-weight: bold;"
            f"font-family: {FONT_MONO}; background: transparent; letter-spacing: 2px;"
        )
        layout.addWidget(self._gate_label)

        self._sub = _label("", TEXT_PRIMARY, 12)
        self._sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._sub)

        self.setVisible(False)

    def show_assignment(self, assignment: GateAssignment):
        if assignment.fallback and assignment.gate_number == "CONTACT GROUND":
            gate_text = "CONTACT GROUND FOR GATE"
            sub_text  = "No matching gate available"
        else:
            terminal_str = f"TERMINAL {assignment.terminal}" if assignment.terminal else ""
            gate_text = f"GATE {assignment.gate_number}"
            sub_text  = terminal_str

        self._gate_label.setText(gate_text)
        self._sub.setText(sub_text)
        self.setVisible(True)

    def hide_banner(self):
        self.setVisible(False)


# ── Flight briefing panel ──────────────────────────────────────────────────────

class BriefingPanel(QFrame):
    fetch_requested = pyqtSignal(str)   # pilot_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_SECONDARY}; border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        hdr.addWidget(_label("FLIGHT BRIEFING", TEXT_PRIMARY, 12, bold=True))
        hdr.addStretch()
        self._fetch_btn = QPushButton("FETCH OFP")
        self._fetch_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_RED}; color: {TEXT_PRIMARY}; "
            f"border: none; border-radius: 4px; padding: 4px 12px; "
            f"font-size: 11px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {ACCENT_RED_DARK}; }}"
            f"QPushButton:disabled {{ background: #555; }}"
        )
        self._fetch_btn.clicked.connect(self._on_fetch)
        hdr.addWidget(self._fetch_btn)
        outer.addLayout(hdr)
        outer.addWidget(_sep())

        self._status = _label("No flight plan loaded.", TEXT_SECONDARY, 11)
        outer.addWidget(self._status)

        # Grid of briefing rows
        self._grid = QGridLayout()
        self._grid.setSpacing(6)
        self._grid.setColumnStretch(1, 1)
        outer.addLayout(self._grid)

        self._rows: dict[str, QLabel] = {}
        fields = [
            ("AIRLINE",     "airline"),
            ("FLIGHT",      "flight"),
            ("CALLSIGN",    "callsign"),
            ("ORIGIN",      "origin"),
            ("DESTINATION", "destination"),
            ("ALTERNATE",   "alternate"),
            ("AIRCRAFT",    "aircraft"),
            ("ROUTE",       "route"),
            ("CRUISE ALT",  "cruise_alt"),
            ("EST TIME",    "est_time"),
            ("DISTANCE",    "distance"),
            ("FUEL",        "fuel"),
            ("ZFW",         "zfw"),
            ("TOW",         "tow"),
            ("ETD",         "etd"),
            ("ETA",         "eta"),
        ]
        for row_idx, (lbl_text, key) in enumerate(fields):
            lbl = _label(lbl_text, TEXT_SECONDARY, 10)
            val = _label("---", TEXT_PRIMARY, 11, font=FONT_MONO)
            val.setWordWrap(True)
            self._grid.addWidget(lbl, row_idx, 0)
            self._grid.addWidget(val, row_idx, 1)
            self._rows[key] = val

        outer.addStretch()

    def set_fetch_button_enabled(self, enabled: bool):
        self._fetch_btn.setEnabled(enabled)

    def _on_fetch(self):
        sb = config.get("simbrief_id", "")
        if sb:
            self.fetch_requested.emit(sb)
        else:
            self._status.setText("⚠  No SimBrief ID configured.")
            self._status.setStyleSheet(f"color: {WARNING}; font-size: 11px;")

    def load_ofp(self, ofp: OFP):
        self._status.setText(f"OFP loaded — {ofp.origin_icao} → {ofp.destination_icao}")
        self._status.setStyleSheet(f"color: {SUCCESS}; font-size: 11px;")

        def mins_to_hhmm(m: int) -> str:
            return f"{m // 60:02d}h {m % 60:02d}m"

        self._rows["airline"].setText(ofp.airline)
        self._rows["flight"].setText(ofp.flight_number)
        self._rows["callsign"].setText(ofp.callsign)
        self._rows["origin"].setText(f"{ofp.origin_icao}  {ofp.origin_name}")
        self._rows["destination"].setText(f"{ofp.destination_icao}  {ofp.destination_name}")
        self._rows["alternate"].setText(ofp.alternate_icao or "None")
        self._rows["aircraft"].setText(f"{ofp.aircraft_icao}  {ofp.aircraft_name}")
        self._rows["route"].setText(ofp.route or "DCT")
        self._rows["cruise_alt"].setText(f"FL{ofp.cruise_altitude // 100:03d}" if ofp.cruise_altitude else "---")
        self._rows["est_time"].setText(mins_to_hhmm(ofp.est_flight_time_min))
        self._rows["distance"].setText(f"{ofp.distance_nm} NM")
        self._rows["fuel"].setText(_fmt_weight(ofp.fuel.total_lbs))
        self._rows["zfw"].setText(_fmt_weight(ofp.zfw_lbs))
        self._rows["tow"].setText(_fmt_weight(ofp.tow_lbs))
        self._rows["etd"].setText(ofp.atd_utc)
        self._rows["eta"].setText(ofp.eta_utc)

    def set_error(self, msg: str):
        self._status.setText(f"✗ {msg}")
        self._status.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")


# ── Real-time status panel ─────────────────────────────────────────────────────

class StatusPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_SECONDARY}; border: 1px solid {BORDER}; border-radius: 6px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 14, 14, 14)
        outer.setSpacing(12)

        outer.addWidget(_label("REAL-TIME STATUS", TEXT_PRIMARY, 12, bold=True))
        outer.addWidget(_sep())

        # Phase display
        self._phase = QLabel("PRE-FLIGHT")
        self._phase.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._phase.setStyleSheet(
            f"color: {TEXT_SECONDARY}; font-size: 22px; font-weight: bold;"
            f"font-family: {FONT_MONO}; background: transparent;"
            f"border: 1px solid {BORDER}; border-radius: 4px; padding: 8px;"
        )
        outer.addWidget(self._phase)

        # Stats grid
        stats_widget = QWidget()
        stats_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        grid = QGridLayout(stats_widget)
        grid.setSpacing(10)

        self._alt     = StatWidget("ALTITUDE", "---", "FT", 20)
        self._gs      = StatWidget("GROUNDSPEED", "---", "KTS", 20)
        self._fuel    = StatWidget("FUEL REMAINING", "---", _weight_unit_label(), 20)
        self._dist    = StatWidget("DIST TO DEST", "---", "NM", 20)
        self._elapsed = StatWidget("ELAPSED", "00:00:00", "UTC", 20)
        self._vs      = StatWidget("VERT SPEED", "---", "FPM", 20)

        grid.addWidget(self._alt,     0, 0)
        grid.addWidget(self._gs,      0, 1)
        grid.addWidget(self._fuel,    0, 2)
        grid.addWidget(self._dist,    1, 0)
        grid.addWidget(self._elapsed, 1, 1)
        grid.addWidget(self._vs,      1, 2)

        outer.addWidget(stats_widget)
        outer.addStretch()

    def update_phase(self, phase: FlightPhase):
        color_map = {
            FlightPhase.PRE_FLIGHT: TEXT_SECONDARY,
            FlightPhase.TAXI_OUT:   WARNING,
            FlightPhase.TAKEOFF:    WARNING,
            FlightPhase.CLIMB:      SUCCESS,
            FlightPhase.CRUISE:     "#60A5FA",   # blue
            FlightPhase.DESCENT:    "#A78BFA",   # purple
            FlightPhase.APPROACH:   ACCENT_RED,
            FlightPhase.LANDING:    WARNING,
            FlightPhase.TAXI_IN:    WARNING,
            FlightPhase.PARKED:     SUCCESS,
        }
        color = color_map.get(phase, TEXT_PRIMARY)
        self._phase.setText(phase.value)
        self._phase.setStyleSheet(
            f"color: {color}; font-size: 22px; font-weight: bold;"
            f"font-family: {FONT_MONO}; background: transparent;"
            f"border: 1px solid {color}; border-radius: 4px; padding: 8px;"
        )

    def update_telemetry(self, tel: Telemetry, elapsed: float, dist_nm: float):
        self._alt.set_value(f"{tel.altitude_ft:,.0f}")
        self._gs.set_value(f"{tel.groundspeed_kts:.0f}")
        unit = _weight_unit_label()
        fuel_val = tel.fuel_lbs * LBS_TO_KG if unit == "KG" else tel.fuel_lbs
        self._fuel.set_value(f"{fuel_val:,.0f}")
        self._fuel.set_unit(unit)
        self._dist.set_value(f"{dist_nm:.1f}" if dist_nm > 0 else "---")

        h = int(elapsed) // 3600
        m = (int(elapsed) % 3600) // 60
        s = int(elapsed) % 60
        self._elapsed.set_value(f"{h:02d}:{m:02d}:{s:02d}")

        vs = tel.vertical_speed_fpm
        vs_color = SUCCESS if vs > 50 else (ACCENT_RED if vs < -50 else TEXT_PRIMARY)
        self._vs.set_value(f"{vs:+.0f}")
        self._vs.set_color(vs_color)


# ── SimBrief fetch worker (non-blocking) ───────────────────────────────────────

class SimBriefFetchWorker(QThread):
    success = pyqtSignal(object)   # OFP
    failure = pyqtSignal(str)      # error message

    def __init__(self, pilot_id: str, parent=None):
        super().__init__(parent)
        self.pilot_id = pilot_id

    def run(self):
        try:
            ofp = fetch_ofp(self.pilot_id)
            self.success.emit(ofp)
        except SimBriefError as e:
            self.failure.emit(str(e))
        except Exception as e:
            self.failure.emit(f"Unexpected error: {e}")


# ── Gate request worker ────────────────────────────────────────────────────────

class GateFetchWorker(QThread):
    success = pyqtSignal(object)   # GateAssignment
    failure = pyqtSignal(str)

    def __init__(self, gate_manager: GateManager,
                 airport_icao: str, aircraft_icao: str,
                 aircraft_reg: str = "", parent=None):
        super().__init__(parent)
        self.gm = gate_manager
        self.airport_icao = airport_icao
        self.aircraft_icao = aircraft_icao
        self.aircraft_reg = aircraft_reg

    def run(self):
        try:
            assignment = self.gm.request_gate(
                self.airport_icao, self.aircraft_icao, self.aircraft_reg
            )
            self.success.emit(assignment)
        except Exception as e:
            self.failure.emit(str(e))


# ── Network panel (right sidebar) ─────────────────────────────────────────────

PHASE_COLORS = {
    "PRE-FLIGHT": TEXT_SECONDARY,
    "TAXI OUT":   WARNING,
    "TAKEOFF":    WARNING,
    "CLIMB":      SUCCESS,
    "CRUISE":     "#60A5FA",
    "DESCENT":    "#A78BFA",
    "APPROACH":   ACCENT_RED,
    "LANDING":    WARNING,
    "TAXI IN":    WARNING,
    "PARKED":     SUCCESS,
}


class PilotRow(QFrame):
    """Single pilot entry in the network roster."""

    def __init__(self, data: dict, parent=None):
        super().__init__(parent)
        self.pilot_id = data.get("pilot_id", "")
        self.setStyleSheet(
            f"QFrame {{ background: {BG_PANEL}; border: 1px solid {BORDER};"
            f"border-radius: 4px; }}"
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        top = QHBoxLayout()
        self._name_lbl = _label("", TEXT_PRIMARY, 11, bold=True)
        self._phase_lbl = _label("", TEXT_SECONDARY, 10)
        self._phase_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        top.addWidget(self._name_lbl)
        top.addStretch()
        top.addWidget(self._phase_lbl)
        layout.addLayout(top)

        self._route_lbl = _label("", TEXT_SECONDARY, 10, font=FONT_MONO)
        layout.addWidget(self._route_lbl)

        self.update_data(data)

    def update_data(self, data: dict):
        name = data.get("name") or data.get("pilot_id", "Unknown")
        phase = data.get("phase", "")
        origin = data.get("origin", "----")
        dest   = data.get("destination", "----")
        fnum   = data.get("flight_number", "")
        alt    = data.get("alt", 0)

        self._name_lbl.setText(name)
        color = PHASE_COLORS.get(phase, TEXT_SECONDARY)
        self._phase_lbl.setText(phase)
        self._phase_lbl.setStyleSheet(
            f"color: {color}; font-size: 10px; background: transparent;"
        )
        route_txt = f"{origin} → {dest}"
        if fnum:
            route_txt = f"{fnum}  {route_txt}"
        if alt and not data.get("on_ground", True):
            route_txt += f"  FL{int(alt) // 100:03d}"
        self._route_lbl.setText(route_txt)


class NetworkPanel(QFrame):
    """
    Collapsible right sidebar showing:
    - Online pilot roster with live phase/route
    - Gate board for the destination airport
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._pilot_rows: dict[str, PilotRow] = {}
        self._gate_cells: dict[str, QLabel] = {}   # gate_number → status label
        self._current_airport = ""

        self.setStyleSheet(
            f"QFrame {{ background: {BG_SECONDARY}; border: 1px solid {BORDER};"
            f"border-radius: 6px; }}"
        )
        self.setMinimumWidth(40)
        self.setMaximumWidth(260)

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(10, 10, 10, 10)
        self._outer.setSpacing(8)

        # ── Header row ──
        hdr = QHBoxLayout()
        self._title = _label("NETWORK", ACCENT_RED, 11, bold=True)
        self._count_lbl = _label("0 online", TEXT_SECONDARY, 10)
        self._toggle_btn = QPushButton("◀")
        self._toggle_btn.setFixedSize(22, 22)
        self._toggle_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SECONDARY};"
            f"border: 1px solid {BORDER}; border-radius: 3px; font-size: 10px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; }}"
        )
        self._toggle_btn.clicked.connect(self._toggle)
        hdr.addWidget(self._title)
        hdr.addWidget(self._count_lbl)
        hdr.addStretch()
        hdr.addWidget(self._toggle_btn)
        self._outer.addLayout(hdr)

        # ── Scrollable content ──
        self._content = QWidget()
        self._content.setStyleSheet("background: transparent;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(6)

        # Pilots section
        self._content_layout.addWidget(_label("PILOTS", TEXT_SECONDARY, 10, bold=True))
        self._no_pilots = _label("No pilots online.", TEXT_SECONDARY, 10)
        self._content_layout.addWidget(self._no_pilots)
        self._pilots_area = QVBoxLayout()
        self._pilots_area.setSpacing(4)
        self._content_layout.addLayout(self._pilots_area)

        self._content_layout.addWidget(_sep())

        # Gate board section
        self._gate_header = _label("GATE BOARD", TEXT_SECONDARY, 10, bold=True)
        self._content_layout.addWidget(self._gate_header)
        self._gate_airport_lbl = _label("", TEXT_SECONDARY, 10)
        self._content_layout.addWidget(self._gate_airport_lbl)
        self._gate_area = QGridLayout()
        self._gate_area.setSpacing(3)
        self._gate_area.setColumnStretch(1, 1)
        self._content_layout.addLayout(self._gate_area)

        self._content_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(self._content)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
        )
        self._outer.addWidget(scroll)

    # ------------------------------------------------------------------
    # Roster management
    # ------------------------------------------------------------------

    def update_pilot(self, data: dict):
        pid = data.get("pilot_id", "")
        if not pid:
            return

        if pid in self._pilot_rows:
            self._pilot_rows[pid].update_data(data)
        else:
            row = PilotRow(data)
            self._pilot_rows[pid] = row
            self._pilots_area.addWidget(row)

        self._no_pilots.setVisible(len(self._pilot_rows) == 0)
        self._count_lbl.setText(f"{len(self._pilot_rows)} online")

    def remove_pilot(self, pilot_id: str):
        row = self._pilot_rows.pop(pilot_id, None)
        if row:
            self._pilots_area.removeWidget(row)
            row.deleteLater()
        self._no_pilots.setVisible(len(self._pilot_rows) == 0)
        self._count_lbl.setText(f"{len(self._pilot_rows)} online")

    # ------------------------------------------------------------------
    # Gate board
    # ------------------------------------------------------------------

    def load_gate_board(self, airport_icao: str, gates: list[dict]):
        """Populate the gate board from an HTTP gate list response."""
        self._current_airport = airport_icao
        self._gate_airport_lbl.setText(airport_icao)
        self._gate_cells.clear()

        # Clear old grid
        while self._gate_area.count():
            item = self._gate_area.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row_idx, g in enumerate(gates):
            gnum  = g.get("gate_number", "?")
            avail = g.get("is_available", True)
            size  = g.get("gate_size", "Medium")

            num_lbl = _label(f"{gnum}", TEXT_PRIMARY, 10, font=FONT_MONO)
            size_lbl = _label(size, TEXT_SECONDARY, 9)

            status_lbl = QLabel("OPEN" if avail else "OCCUPIED")
            color = SUCCESS if avail else ACCENT_RED
            status_lbl.setStyleSheet(
                f"color: {color}; font-size: 9px;"
                f"font-family: {FONT_MONO}; background: transparent;"
            )
            status_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)

            self._gate_area.addWidget(num_lbl,    row_idx, 0)
            self._gate_area.addWidget(size_lbl,   row_idx, 1)
            self._gate_area.addWidget(status_lbl, row_idx, 2)
            self._gate_cells[gnum] = status_lbl

    def mark_gate_assigned(self, airport: str, gate_number: str, pilot_name: str):
        if airport != self._current_airport:
            return
        lbl = self._gate_cells.get(gate_number)
        if lbl:
            display = pilot_name if pilot_name else "OCCUPIED"
            lbl.setText(display[:12])
            lbl.setStyleSheet(
                f"color: {ACCENT_RED}; font-size: 9px;"
                f"font-family: {FONT_MONO}; background: transparent;"
            )

    def mark_gate_released(self, airport: str, gate_number: str):
        if airport != self._current_airport:
            return
        lbl = self._gate_cells.get(gate_number)
        if lbl:
            lbl.setText("OPEN")
            lbl.setStyleSheet(
                f"color: {SUCCESS}; font-size: 9px;"
                f"font-family: {FONT_MONO}; background: transparent;"
            )

    # ------------------------------------------------------------------
    # Collapse toggle
    # ------------------------------------------------------------------

    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._collapsed:
            self._content.setVisible(False)
            self._title.setVisible(False)
            self._count_lbl.setVisible(False)
            self.setMaximumWidth(36)
            self._toggle_btn.setText("▶")
        else:
            self._content.setVisible(True)
            self._title.setVisible(True)
            self._count_lbl.setVisible(True)
            self.setMaximumWidth(260)
            self._toggle_btn.setText("◀")


# ── phpVMS Bid Panel ──────────────────────────────────────────────────────────

class BidPanel(QFrame):
    """Compact panel showing the phpVMS booking matched to the loaded OFP."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {BG_SECONDARY}; border: 1px solid {BORDER}; border-radius: 6px; }}"
        )
        self.setFixedHeight(140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        hdr = QHBoxLayout()
        hdr.addWidget(_label("PHPVMS BOOKING", ACCENT_RED, 11, bold=True))
        hdr.addStretch()
        self._id_lbl = _label("ID: ---", TEXT_SECONDARY, 10, font=FONT_MONO)
        hdr.addWidget(self._id_lbl)
        layout.addLayout(hdr)
        layout.addWidget(_sep())

        grid = QGridLayout()
        grid.setSpacing(10)
        self._callsign = StatWidget("ASSIGNED CALLSIGN", "---", "", 16)
        self._fnum     = StatWidget("FLIGHT NO.", "---", "", 16)
        self._route    = StatWidget("NETWORK ROUTE", "---", "", 16)
        self._aircraft = StatWidget("ASSIGNED ACFT", "---", "", 16)
        grid.addWidget(self._callsign, 0, 0)
        grid.addWidget(self._fnum,     0, 1)
        grid.addWidget(self._route,    1, 0)
        grid.addWidget(self._aircraft, 1, 1)
        layout.addLayout(grid)

    def load_bid(self, bid_data: dict):
        flight = bid_data.get('flight', {})
        acft   = bid_data.get('aircraft', {}) or flight.get('aircraft', {})

        self._id_lbl.setText(f"ID: {bid_data.get('id', '---')}")

        f_num = str(flight.get('flight_number', '---'))
        icao  = flight.get('airline', {}).get('icao', '')
        self._callsign.set_value(f"{icao}{f_num}")
        self._fnum.set_value(f_num)
        self._route.set_value(
            f"{flight.get('dpt_airport_id', '----')} → {flight.get('arr_airport_id', '----')}"
        )
        acft_name = f"{acft.get('registration', '---')} ({acft.get('icao', '---')})"
        self._aircraft.set_value(acft_name)


# ── Main window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    # Cross-thread signal — emitted from background fetch thread,
    # dispatched safely to the main thread by Qt's queued connection.
    _gate_board_ready  = pyqtSignal(str, object)   # (airport_icao, gates_list)
    _phpvms_bid_ready  = pyqtSignal(object)        # bid dict on success, None on failure
    _phpvms_acars_ok   = pyqtSignal(bool)          # ACARS update result from background thread
    _queue_flush_done  = pyqtSignal(int)           # count of offline-queued requests resent
    _pirep_file_result = pyqtSignal(bool)          # final PIREP filing result
    _prefile_result    = pyqtSignal(object)        # prefile PIREP id (str) or None on failure

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AFRICANA VIRTUAL AIRWAYS — Flight Tracker")
        self.setMinimumSize(1100, 700)
        self.resize(1280, 780)

        self._cfg = config.load_config()
        self._ofp: Optional[OFP] = None
        self._tracking = False
        self._gate_requested = False
        self._last_tel: Optional[Telemetry] = None

        # Workers / managers
        self._simconnect_worker: Optional[SimConnectWorker] = None
        self._flight_tracker: Optional[FlightTracker] = None
        self._gate_manager = GateManager(
            self._cfg.get("server_url", "http://localhost:8765"),
            pilot_id=self._cfg.get("vatsim_cid", ""),
            pilot_name=self._cfg.get("pilot_name", ""),
        )
        self._simbrief_worker: Optional[SimBriefFetchWorker] = None
        self._gate_worker: Optional[GateFetchWorker] = None

        # phpVMS Integration
        self._vms = PhpVmsClient()
        self._vms_bid_panel = BidPanel()
        self._acars_last_sent = 0.0  # monotonic timestamp of last successful ACARS push

        # Every phpVMS write (status push, ACARS position, PIREP filing, offline
        # retries) is funneled through this single worker so requests are always
        # sent in the order they actually happened — see phpvms_sync_worker.py.
        self._vms_sync = PhpVmsSyncWorker(self)
        self._vms_sync.start()

        # Network (multi-pilot WebSocket)
        self._net_client: Optional[NetworkClient] = None
        self._online_pilots: dict[str, dict] = {}

        # Discord Rich Presence (no-ops if disabled or no client ID configured)
        self._discord: Optional[DiscordPresenceWorker] = None
        if self._cfg.get("discord_rpc_enabled") and self._cfg.get("discord_client_id"):
            self._discord = DiscordPresenceWorker(self._cfg["discord_client_id"], self)
            self._discord.start()

        self._apply_global_style()
        self._build_ui()
        self._setup_clock_timer()
        self._setup_tray()
        self._setup_msfs_watcher()
        self._setup_queue_retry_timer()

        # Wire cross-thread signals
        self._gate_board_ready.connect(self._apply_gate_board)
        self._phpvms_bid_ready.connect(self._on_bid_ready)
        self._phpvms_acars_ok.connect(self._on_acars_result)
        self._queue_flush_done.connect(self._on_queue_flush_done)
        self._pirep_file_result.connect(self._on_pirep_filed)
        self._prefile_result.connect(self._on_prefile_result)

        # Auto-fetch if credentials already saved
        if self._cfg.get("vatsim_cid"):
            QTimer.singleShot(500, self._auto_fetch)
            QTimer.singleShot(800, self._start_network_client)

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def _apply_global_style(self):
        self.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background: {BG_PRIMARY};
                color: {TEXT_PRIMARY};
                font-family: {FONT_LABEL};
            }}
            QScrollBar:vertical {{
                background: {BG_SECONDARY}; width: 8px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: #444; border-radius: 4px; min-height: 20px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QStatusBar {{
                background: {BG_SECONDARY};
                color: {TEXT_SECONDARY};
                font-size: 11px;
                border-top: 1px solid {BORDER};
            }}
        """)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_topbar())

        content = QWidget()
        content.setStyleSheet(f"background: {BG_PRIMARY};")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 12, 12, 12)
        content_layout.setSpacing(10)

        # Main horizontal split: left (briefing) | right (status + gate)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: #2A2A2A; }")

        # Left: briefing
        self._briefing = BriefingPanel()
        self._briefing.fetch_requested.connect(self._fetch_simbrief)
        left_scroll = QScrollArea()
        left_scroll.setWidget(self._briefing)
        left_scroll.setWidgetResizable(True)
        left_scroll.setMinimumWidth(300)
        left_scroll.setMaximumWidth(420)
        left_scroll.setStyleSheet(
            f"QScrollArea {{ background: transparent; border: none; }}"
        )
        splitter.addWidget(left_scroll)

        # Right: status + controls + gate banner
        right = QWidget()
        right.setStyleSheet("background: transparent;")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(10)

        self._status_panel = StatusPanel()
        right_layout.addWidget(self._status_panel, stretch=1)

        # phpVMS booking info
        right_layout.addWidget(self._vms_bid_panel)

        # Control buttons
        right_layout.addWidget(self._build_controls())

        # Gate assignment banner
        self._gate_banner = GateBanner()
        right_layout.addWidget(self._gate_banner)

        splitter.addWidget(right)

        # Network panel — right sidebar
        self._network_panel = NetworkPanel()
        splitter.addWidget(self._network_panel)
        splitter.setSizes([340, 720, 220])
        content_layout.addWidget(splitter)
        root.addWidget(content)

        # Status bar
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._status_sim = QLabel("SimConnect: Disconnected")
        self._status_sim.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")
        self._status_clock = QLabel("--:--:-- UTC")
        self._status_clock.setStyleSheet(f"color: {TEXT_SECONDARY}; font-size: 11px;")
        self._statusbar.addWidget(self._status_sim)
        self._statusbar.addPermanentWidget(self._status_clock)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(52)
        bar.setStyleSheet(
            f"background: {BG_SECONDARY}; border-bottom: 2px solid {ACCENT_RED};"
        )
        row = QHBoxLayout(bar)
        row.setContentsMargins(16, 0, 16, 0)
        row.setSpacing(12)

        # Branding
        brand = _label("◈ AFRICANA VIRTUAL AIRWAYS", ACCENT_RED, 18, bold=True)
        row.addWidget(brand)

        sub = _label("FLIGHT TRACKER", TEXT_SECONDARY, 11)
        row.addWidget(sub)
        row.addStretch()

        # Connection dots
        self._dot_network  = ConnDot("Network")
        self._dot_simbrief = ConnDot("SimBrief")
        self._dot_msfs     = ConnDot("MSFS")
        self._dot_phpvms   = ConnDot("phpVMS")
        row.addWidget(self._dot_network)
        row.addWidget(self._dot_simbrief)
        row.addWidget(self._dot_msfs)
        row.addWidget(self._dot_phpvms)
        row.addSpacing(8)

        # Pilot info
        self._pilot_label = _label(
            self._cfg.get("pilot_name") or self._cfg.get("vatsim_cid") or "No pilot",
            TEXT_SECONDARY, 11
        )
        row.addWidget(self._pilot_label)

        # Setup button
        setup_btn = QPushButton("⚙  SETUP")
        setup_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {TEXT_SECONDARY}; "
            f"border: 1px solid {BORDER}; border-radius: 4px; padding: 4px 10px; "
            f"font-size: 11px; }}"
            f"QPushButton:hover {{ color: {TEXT_PRIMARY}; border-color: {ACCENT_RED}; }}"
        )
        setup_btn.clicked.connect(self._open_setup)
        row.addWidget(setup_btn)

        return bar

    def _build_controls(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet("background: transparent;")
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        self._track_btn = QPushButton("▶  START TRACKING")
        self._track_btn.setFixedHeight(42)
        self._track_btn.setStyleSheet(
            f"QPushButton {{ background: {ACCENT_RED}; color: {TEXT_PRIMARY}; "
            f"border: none; border-radius: 5px; font-size: 13px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {ACCENT_RED_DARK}; }}"
            f"QPushButton:disabled {{ background: #444; color: #888; }}"
        )
        self._track_btn.clicked.connect(self._toggle_tracking)
        row.addWidget(self._track_btn, stretch=1)

        self._refresh_btn = QPushButton("↻  REFRESH OFP")
        self._refresh_btn.setFixedHeight(42)
        self._refresh_btn.setStyleSheet(
            f"QPushButton {{ background: {BG_PANEL}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {BORDER}; border-radius: 5px; font-size: 12px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT_RED}; }}"
            f"QPushButton:disabled {{ color: #555; }}"
        )
        self._refresh_btn.clicked.connect(self._fetch_simbrief_manual)
        row.addWidget(self._refresh_btn)

        return w

    # ------------------------------------------------------------------
    # Clock timer
    # ------------------------------------------------------------------

    def _setup_clock_timer(self):
        timer = QTimer(self)
        timer.timeout.connect(self._tick_clock)
        timer.start(1000)

    @pyqtSlot()
    def _tick_clock(self):
        now = datetime.now(tz=timezone.utc)
        self._status_clock.setText(now.strftime("%H:%M:%S") + " UTC")
        if self._flight_tracker and self._tracking and self._last_tel:
            elapsed = self._flight_tracker.elapsed_seconds
            dist = self._flight_tracker.distance_to_dest_nm
            self._status_panel.update_telemetry(self._last_tel, elapsed, dist)

    # ------------------------------------------------------------------
    # System tray
    # ------------------------------------------------------------------

    def _setup_tray(self):
        # Draw a circular tray icon: red disc with white "A" initial
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor(ACCENT_RED)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 32, 32)
        p.setPen(QPen(QColor("#ffffff")))
        f = QFont("Arial", 16, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, "A")
        p.end()
        icon = QIcon(pix)

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("AFV Tracker — Africana Virtual Airways")

        menu = QMenu()
        act_show = menu.addAction("Show AFV Tracker")
        act_show.triggered.connect(self._show_from_tray)
        menu.addSeparator()
        act_quit = menu.addAction("Quit")
        act_quit.triggered.connect(self._quit_app)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _show_from_tray(self):
        self.show()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _notify_gate(self, gate_number: str, airport: str):
        """Tray popup + taskbar flash + sound when a gate is assigned."""
        self._tray.showMessage(
            "Gate Assigned",
            f"Gate {gate_number} at {airport}",
            QSystemTrayIcon.MessageIcon.Information,
            8000,
        )
        QApplication.alert(self, 0)   # flash taskbar until window is focused
        sounds.play("gate_assigned")

    # ------------------------------------------------------------------
    # MSFS process watcher — auto-show and auto-track
    # ------------------------------------------------------------------

    # Known process names for MSFS 2020 and 2024
    _MSFS_PROCESSES = {"flightsimulator.exe", "microsoft.flightsimulator2024.exe"}

    def _setup_msfs_watcher(self):
        self._msfs_was_running = False
        self._msfs_timer = QTimer(self)
        self._msfs_timer.timeout.connect(self._check_msfs)
        self._msfs_timer.start(5_000)   # check every 5 seconds

    @pyqtSlot()
    def _check_msfs(self):
        try:
            import psutil
            running = any(
                p.info["name"].lower() in self._MSFS_PROCESSES
                for p in psutil.process_iter(["name"])
                if p.info["name"]
            )
        except Exception:
            return

        if running and not self._msfs_was_running:
            # MSFS just started
            self._msfs_was_running = True
            log.info("MSFS detected — showing AFV Tracker.")
            self._show_from_tray()
            self._tray.showMessage(
                "AFV Tracker",
                "MSFS detected. Connecting…",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            # Start tracking automatically
            if not self._tracking:
                QTimer.singleShot(1000, self._start_tracking)

        elif not running and self._msfs_was_running:
            # MSFS closed
            self._msfs_was_running = False
            log.info("MSFS closed — stopping tracking.")
            if self._tracking:
                self._stop_tracking()
            self.hide()
            self._tray.showMessage(
                "AFV Tracker",
                "MSFS closed. Running in background.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    # ------------------------------------------------------------------
    # Setup dialog
    # ------------------------------------------------------------------

    def _open_setup(self):
        prev_theme    = config.get("theme", "dark")
        prev_discord  = config.get("discord_rpc_enabled", True)
        dlg = PilotSetupDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            (vatsim_cid, simbrief_id, name, discord, unit, va_url, pilot_key,
             theme, discord_rpc_enabled, sound_enabled) = dlg.get_values()
            if vatsim_cid:
                config.set_value("vatsim_cid",  vatsim_cid)
                config.set_value("simbrief_id", simbrief_id)
                config.set_value("pilot_name",  name)
                config.set_value("discord",     discord)
                config.set_value("weight_unit", unit)
                config.set_value("VA_URL", va_url)
                config.set_value("Pilot_Key", pilot_key)
                config.set_value("theme", theme)
                config.set_value("discord_rpc_enabled", discord_rpc_enabled)
                config.set_value("sound_enabled", sound_enabled)
                self._vms.refresh_credentials()
                self._cfg = config.load_config()
                self._pilot_label.setText(name or vatsim_cid)
                self._gate_manager.pilot_id   = vatsim_cid
                self._gate_manager.pilot_name = name
                # Register / update pilot in the database
                self._register_pilot(vatsim_cid, simbrief_id, name, discord)
                if simbrief_id:
                    self._fetch_simbrief(simbrief_id)
                elif self._ofp:
                    # Credentials changed but OFP already loaded — re-try bid fetch
                    self._on_ofp_loaded(self._ofp)
                self._start_network_client()
                if theme != prev_theme or discord_rpc_enabled != prev_discord:
                    QMessageBox.information(
                        self, "Restart required",
                        "Restart AFV Tracker for the theme / Discord Rich "
                        "Presence change to take effect."
                    )

    def _register_pilot(self, vatsim_cid: str, simbrief_id: str,
                        name: str, discord: str):
        """POST pilot details to the server (create or update)."""
        import threading, requests as req
        server = config.get("server_url", "http://localhost:8765")
        payload = {
            "vatsim_cid":  vatsim_cid,
            "simbrief_id": simbrief_id or None,
            "name":        name,
            "discord":     discord or None,
        }
        def _post():
            try:
                req.post(f"{server}/api/pilots/register", json=payload, timeout=8)
            except Exception as e:
                log.warning("Pilot registration failed: %s", e)
        threading.Thread(target=_post, daemon=True).start()

    # ------------------------------------------------------------------
    # SimBrief fetching
    # ------------------------------------------------------------------

    def _auto_fetch(self):
        sb = config.get("simbrief_id", "")
        if sb:
            self._fetch_simbrief(sb)

    def _fetch_simbrief_manual(self):
        sb = config.get("simbrief_id", "")
        if not sb:
            self._open_setup()
            return
        self._fetch_simbrief(sb)

    @pyqtSlot(str)
    def _fetch_simbrief(self, pilot_id: str):
        if self._simbrief_worker and self._simbrief_worker.isRunning():
            return
        self._briefing.set_fetch_button_enabled(False)
        self._briefing._status.setText("Fetching OFP from SimBrief…")
        self._briefing._status.setStyleSheet(f"color: {WARNING}; font-size: 11px;")
        self._dot_simbrief.set_connected(False)

        self._simbrief_worker = SimBriefFetchWorker(pilot_id, self)
        self._simbrief_worker.success.connect(self._on_ofp_loaded)
        self._simbrief_worker.failure.connect(self._on_ofp_error)
        self._simbrief_worker.finished.connect(
            lambda: self._briefing.set_fetch_button_enabled(True)
        )
        self._simbrief_worker.start()

    @pyqtSlot(object)
    def _on_ofp_loaded(self, ofp: OFP):
        self._ofp = ofp
        self._briefing.load_ofp(ofp)
        self._dot_simbrief.set_connected(True)

        # Update flight tracker destination
        dest_coords = _AIRPORT_COORDS.get(ofp.destination_icao)
        if self._flight_tracker and dest_coords:
            self._flight_tracker.set_destination(*dest_coords)

        # Load gate board for destination in background.
        # Emit a signal (not QTimer.singleShot) so Qt queues the call
        # safely back onto the main thread.
        import threading
        def _fetch_board():
            gates = self._gate_manager.fetch_gate_board(ofp.destination_icao)
            if gates:
                self._gate_board_ready.emit(ofp.destination_icao, gates)
        threading.Thread(target=_fetch_board, daemon=True).start()

        # Fetch phpVMS bids in background — avoids blocking the GUI thread
        if not self._vms.api_key:
            self._dot_phpvms.set_connected(False, "phpVMS (no key)")
            self._statusbar.showMessage("phpVMS: no API key set — open Setup to configure.")
        else:
            self._dot_phpvms.set_connected(False, "phpVMS")
            self._statusbar.showMessage("Fetching phpVMS bid…")
            flight_number = ofp.flight_number
            planned_fuel  = ofp.fuel.total_lbs
            flight_level  = ofp.cruise_altitude
            route         = ofp.route or ""

            def _fetch_bid():
                bids = self._vms.get_bids()
                if not bids:
                    self._phpvms_bid_ready.emit(None)
                    return
                match = next(
                    (b for b in bids
                     if str(b.get('flight', {}).get('flight_number', '')) in str(flight_number)),
                    bids[0],
                )
                self._phpvms_bid_ready.emit(match)

            import threading
            threading.Thread(target=_fetch_bid, daemon=True).start()

    @pyqtSlot(str, object)
    def _apply_gate_board(self, airport: str, gates):
        self._network_panel.load_gate_board(airport, gates)

    @pyqtSlot(object)
    def _on_bid_ready(self, bid):
        if bid is None:
            self._dot_phpvms.set_connected(False, "phpVMS")
            self._statusbar.showMessage(
                "phpVMS: no bids found — book a flight on the website first."
            )
            return
        self._dot_phpvms.set_connected(True, "phpVMS")
        self._vms_bid_panel.load_bid(bid)
        self._statusbar.showMessage("phpVMS bid matched — prefiling PIREP…")
        if self._ofp:
            planned_fuel  = self._ofp.fuel.total_lbs
            flight_level  = self._ofp.cruise_altitude
            route         = self._ofp.route or ""

            def _prefile():
                pirep_id = self._vms.prefile_pirep(
                    bid_data=bid,
                    planned_fuel=planned_fuel,
                    flight_level=flight_level,
                    route=route,
                )
                self._prefile_result.emit(pirep_id)

            # Queued (not called directly) so it can't block the GUI thread on
            # network I/O, and so it can't race a phase-change status push that
            # fires while this is still in flight.
            self._vms_sync.submit(_prefile)

    @pyqtSlot(object)
    def _on_prefile_result(self, pirep_id):
        if pirep_id:
            self._statusbar.showMessage(f"PIREP prefiled (ID {pirep_id}) — ready to fly.")
            # Phase changes that fired before the prefile completed had no PIREP id,
            # so the status push was skipped. Push the current phase now so phpVMS
            # doesn't stay stuck on "Initiated" and its flight-time counter starts.
            if self._flight_tracker:
                _cur_phase = self._flight_tracker.phase
                _cur_status = self._PIREP_STATUS_MAP.get(_cur_phase)
                if _cur_status:
                    def _push_initial_status():
                        self._vms.update_pirep_status(_cur_status)
                    self._vms_sync.submit(_push_initial_status)
        else:
            self._statusbar.showMessage("phpVMS: bid matched but prefile failed — check logs.")
            self._dot_phpvms.set_connected(False, "phpVMS")

    @pyqtSlot(bool)
    def _on_acars_result(self, ok: bool):
        self._dot_phpvms.set_connected(ok, "phpVMS")
        if not ok:
            log.warning("phpVMS ACARS update failed — position not sent")

    @pyqtSlot()
    def _check_pirep_health(self):
        """Verify the active PIREP is still IN_PROGRESS on phpVMS (runs every 60 s)."""
        if not self._vms.current_pirep_id:
            return

        def _health():
            active = self._vms.is_pirep_active()
            self._phpvms_acars_ok.emit(active)

        threading.Thread(target=_health, daemon=True).start()

    # ------------------------------------------------------------------
    # Offline queue — retries ACARS/PIREP requests that failed to send
    # ------------------------------------------------------------------

    def _setup_queue_retry_timer(self):
        timer = QTimer(self)
        timer.timeout.connect(self._retry_offline_queue)
        timer.start(45_000)
        # Also try shortly after startup in case items are left over from a
        # previous session that closed while offline.
        QTimer.singleShot(5_000, self._retry_offline_queue)

    @pyqtSlot()
    def _retry_offline_queue(self):
        def _retry():
            sent = self._vms.retry_pending()
            if sent:
                self._queue_flush_done.emit(sent)
        # Goes through the same serialized worker as live pushes so a replayed
        # queued item can never race a fresher live update.
        self._vms_sync.submit(_retry)

    @pyqtSlot(int)
    def _on_queue_flush_done(self, sent: int):
        self._statusbar.showMessage(
            f"Resent {sent} queued phpVMS update(s) after reconnecting."
        )

    @pyqtSlot(str)
    def _on_ofp_error(self, msg: str):
        self._briefing.set_error(msg)
        self._dot_simbrief.set_connected(False)
        log.warning("SimBrief error: %s", msg)

    # ------------------------------------------------------------------
    # Tracking
    # ------------------------------------------------------------------

    @pyqtSlot()
    def _toggle_tracking(self):
        if not self._tracking:
            self._start_tracking()
        else:
            self._stop_tracking()

    def _start_tracking(self):
        dest_lat, dest_lon = 0.0, 0.0
        if self._ofp:
            coords = _AIRPORT_COORDS.get(self._ofp.destination_icao, (0.0, 0.0))
            dest_lat, dest_lon = coords

        self._flight_tracker = FlightTracker(dest_lat, dest_lon, self)
        self._flight_tracker.phase_changed.connect(self._on_phase_changed)
        self._flight_tracker.approach_reached.connect(self._on_approach)
        self._flight_tracker.flight_complete.connect(self._on_flight_complete)

        # Discord presence: fix the "elapsed" start time once so it counts up
        # continuously across the whole flight instead of resetting per phase.
        self._discord_start_ts = time.time()
        if self._discord:
            self._push_discord_presence(FlightPhase.PRE_FLIGHT)

        interval = self._cfg.get("simconnect_poll_interval", 5)
        self._simconnect_worker = SimConnectWorker(interval, self)
        self._simconnect_worker.telemetry_update.connect(self._on_telemetry)
        self._simconnect_worker.connected.connect(self._on_sim_connected)
        self._simconnect_worker.disconnected.connect(self._on_sim_disconnected)
        self._simconnect_worker.error.connect(self._on_sim_error)
        self._simconnect_worker.start()

        # Periodically verify the PIREP is still IN_PROGRESS on phpVMS.
        # Catches server-side auto-cancellations that a successful POST can't detect.
        self._pirep_health_timer = QTimer(self)
        self._pirep_health_timer.timeout.connect(self._check_pirep_health)
        self._pirep_health_timer.start(60_000)

        self._tracking = True
        self._gate_requested = False
        self._gate_banner.hide_banner()
        self._track_btn.setText("■  STOP TRACKING")
        self._statusbar.showMessage("Connecting to MSFS…")

    def _stop_tracking(self):
        if self._simconnect_worker:
            self._simconnect_worker.stop()
            self._simconnect_worker = None

        if hasattr(self, "_pirep_health_timer"):
            self._pirep_health_timer.stop()

        if self._discord:
            self._discord.clear_activity()

        self._tracking = False
        self._track_btn.setText("▶  START TRACKING")
        self._dot_msfs.set_connected(False)
        self._status_sim.setText("SimConnect: Disconnected")
        self._status_sim.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")
        self._statusbar.showMessage("Tracking stopped.")

    # ------------------------------------------------------------------
    # SimConnect signals
    # ------------------------------------------------------------------

    @pyqtSlot(object)
    def _on_telemetry(self, tel: Telemetry):
        self._last_tel = tel
        if self._flight_tracker:
            self._flight_tracker.update(tel)
            dist = self._flight_tracker.distance_to_dest_nm
            elapsed = self._flight_tracker.elapsed_seconds
            self._status_panel.update_telemetry(tel, elapsed, dist)
            # Send live ACARS to phpVMS — throttled, off the main thread.
            # Use a shorter interval during approach/landing so phpVMS live map
            # doesn't expire between updates.
            _phase = self._flight_tracker.phase
            _acars_interval = (
                15 if _phase in (FlightPhase.APPROACH, FlightPhase.LANDING,
                                 FlightPhase.TAXI_IN)
                else 30
            )
            now = time.monotonic()
            if self._vms.current_pirep_id and now - self._acars_last_sent >= _acars_interval:
                try:
                    self._acars_last_sent = now
                    _lat, _lon, _alt = tel.latitude, tel.longitude, tel.altitude_ft
                    _gs  = tel.groundspeed_kts
                    _hdg = getattr(tel, "heading_true", tel.heading_mag)
                    _state = self._flight_tracker.phase.vms_code
                    _distance_nm     = self._flight_tracker.distance_flown_nm
                    _flight_time_min = elapsed / 60.0
                    # Push PIREP status on every ACARS tick — acts as automatic retry
                    # if the phase-change push failed (e.g. transient network error).
                    _pirep_status = self._PIREP_STATUS_MAP.get(_phase)

                    _vs = int(getattr(tel, "vertical_speed_fpm", 0) or 0)

                    def _send_acars():
                        ok = self._vms.update_acars(
                            lat=_lat, lon=_lon, alt=_alt,
                            gs=_gs, heading=_hdg, state=_state, vs=_vs,
                            distance_nm=_distance_nm,
                        )
                        if _pirep_status:
                            self._vms.update_pirep_status(
                                _pirep_status,
                                flight_time_min=_flight_time_min,
                                distance_nm=_distance_nm,
                            )
                        self._phpvms_acars_ok.emit(ok)

                    self._vms_sync.submit(_send_acars)
                except Exception:
                    log.exception("ACARS update scheduling failed")
        # Broadcast position to other pilots on the network
        self._broadcast_own_telemetry(tel)

    # phpVMS v7 PirepStatus codes (see app/Models/Enums/PirepStatus.php).
    # Must be set via PUT /api/pireps/{id} — ACARS positions do NOT advance this.
    # Valid: INI BST RDT PBT OFB DIR DIC GRT TXI TOF ICL TKO ENR DV TEN APR FIN
    #        LDG LAN ONB ARR DX EMG PSD
    _PIREP_STATUS_MAP = {
        FlightPhase.PRE_FLIGHT: "BST",   # BOARDING
        FlightPhase.TAXI_OUT:   "TXI",   # TAXI
        FlightPhase.TAKEOFF:    "TOF",   # TAKEOFF
        FlightPhase.CLIMB:      "ICL",   # INIT_CLIM
        FlightPhase.CRUISE:     "ENR",   # ENROUTE
        FlightPhase.DESCENT:    "ENR",   # ENROUTE (no separate descent code)
        FlightPhase.APPROACH:   "TEN",   # APPROACH
        FlightPhase.LANDING:    "LDG",   # LANDING
        FlightPhase.TAXI_IN:    "LAN",   # LANDED
        FlightPhase.PARKED:     "ARR",   # ARRIVED (file_pirep also sets this)
    }

    def _push_discord_presence(self, phase: FlightPhase):
        if not self._discord:
            return
        origin = self._ofp.origin_icao if self._ofp else "????"
        dest   = self._ofp.destination_icao if self._ofp else "????"
        callsign = self._ofp.callsign if self._ofp else ""
        state = f"{phase.value} · {callsign}" if callsign else phase.value
        self._discord.update_activity(
            details=f"{origin} → {dest}",
            state=state,
            start_ts=getattr(self, "_discord_start_ts", None),
        )

    @pyqtSlot(object)
    def _on_phase_changed(self, phase: FlightPhase):
        self._status_panel.update_phase(phase)
        self._statusbar.showMessage(f"Phase: {phase.value}")
        self._push_discord_presence(phase)
        if phase == FlightPhase.TAKEOFF:
            sounds.play("flight_start")
        elif phase == FlightPhase.LANDING:
            sounds.play("landing")
        # Force an immediate ACARS update on approach so phpVMS gets the status
        # without waiting up to 30 s for the next scheduled tick.
        if phase == FlightPhase.APPROACH:
            self._acars_last_sent = 0.0
        # Push the phase status to phpVMS explicitly (ACARS positions don't do this).
        try:
            status_code = self._PIREP_STATUS_MAP.get(phase)
            if status_code and self._vms.current_pirep_id:
                _elapsed_min = (self._flight_tracker.elapsed_seconds / 60.0
                                if self._flight_tracker else None)
                _dist_nm = (self._flight_tracker.distance_flown_nm
                            if self._flight_tracker else None)

                def _push_status():
                    self._vms.update_pirep_status(
                        status_code,
                        flight_time_min=_elapsed_min,
                        distance_nm=_dist_nm,
                    )
                self._vms_sync.submit(_push_status)
        except Exception:
            log.exception("PIREP status push failed for phase %s", phase)

        # Reopened mid-flight past approach — gate was released on disconnect,
        # so request a fresh one now.
        if phase in (FlightPhase.APPROACH, FlightPhase.LANDING,
                     FlightPhase.TAXI_IN, FlightPhase.PARKED):
            if not self._gate_requested and self._ofp:
                self._on_approach(self._flight_tracker.distance_to_dest_nm
                                  if self._flight_tracker else 0.0)

        # Flight complete — release the gate now that we're parked.
        if phase == FlightPhase.PARKED:
            assignment = self._gate_manager.current_assignment
            if assignment and not assignment.fallback:
                threading.Thread(
                    target=self._gate_manager.release_gate,
                    args=(assignment.airport_icao, assignment.gate_number),
                    daemon=True,
                ).start()

    @pyqtSlot(float)
    def _on_approach(self, dist_nm: float):
        if self._gate_requested or not self._ofp:
            return
        self._gate_requested = True
        airport = self._ofp.destination_icao
        aircraft = self._ofp.aircraft_icao
        reg = self._ofp.registration or ""

        self._gate_worker = GateFetchWorker(
            self._gate_manager, airport, aircraft, reg, self
        )
        self._gate_worker.success.connect(self._on_gate_assigned)
        self._gate_worker.failure.connect(self._on_gate_error)
        self._gate_worker.start()
        self._statusbar.showMessage(
            f"Requesting gate at {airport} for {aircraft}…"
        )

    @pyqtSlot(object)
    def _on_gate_assigned(self, assignment: GateAssignment):
        self._gate_banner.show_assignment(assignment)
        self._statusbar.showMessage(f"Gate assigned: {assignment.gate_number}")
        self._notify_gate(assignment.gate_number, assignment.airport_icao)

    @pyqtSlot(str)
    def _on_gate_error(self, msg: str):
        log.warning("Gate error: %s", msg)
        self._statusbar.showMessage(f"Gate error: {msg}")

    @pyqtSlot(str)
    def _on_sim_connected(self, version: str):
        self._dot_msfs.set_connected(True, version)
        self._status_sim.setText(f"SimConnect: {version}")
        self._status_sim.setStyleSheet(f"color: {SUCCESS}; font-size: 11px;")
        self._statusbar.showMessage(f"Connected to {version}.")

    @pyqtSlot()
    def _on_sim_disconnected(self):
        self._dot_msfs.set_connected(False)   # resets label to "MSFS"
        self._status_sim.setText("SimConnect: Disconnected — retrying…")
        self._status_sim.setStyleSheet(f"color: {WARNING}; font-size: 11px;")

    @pyqtSlot(str)
    def _on_sim_error(self, msg: str):
        self._dot_msfs.set_connected(False)
        self._status_sim.setText("SimConnect: Error")
        self._status_sim.setStyleSheet(f"color: {ACCENT_RED}; font-size: 11px;")
        self._statusbar.showMessage(f"SimConnect: {msg}")
        log.error("SimConnect fatal error: %s", msg)
        sounds.play("error")
        self._stop_tracking()

    @pyqtSlot(dict)
    def _on_flight_complete(self, data: dict):
        if not self._ofp:
            return
        cfg = config.load_config()
        payload = {
            "vatsim_cid":       cfg.get("vatsim_cid", ""),
            "pilot_name":       cfg.get("pilot_name", ""),
            "callsign":         self._ofp.callsign,
            "flight_number":    self._ofp.flight_number,
            "origin":           self._ofp.origin_icao,
            "destination":      self._ofp.destination_icao,
            "aircraft_type":    self._ofp.aircraft_icao,
            **data,
        }
        self._post_flight_log(payload)
        QMessageBox.information(
            self, "Flight Complete",
            f"Flight {self._ofp.flight_number} logged.\n"
            f"Flight time: {int(data['flight_time_sec'])//3600:02d}h "
            f"{(int(data['flight_time_sec'])%3600)//60:02d}m\n"
            f"Landing rate: {data.get('landing_rate_fpm') or 'N/A'} fpm"
        )

        # File the PIREP on phpVMS — queued on the sync worker (not called
        # directly here) so it (a) doesn't block the GUI thread on network I/O
        # and (b) runs strictly after any still-pending ACARS/status pushes for
        # this flight instead of racing them.
        flight_time_mins = int(data['flight_time_sec']) // 60
        fuel_used        = data.get('fuel_used_lbs', 0) or 0
        distance_nm      = data.get('distance_flown_nm', 0) or 0
        landing_rate     = data.get('landing_rate_fpm') or 0
        log_text = (
            f"Filed by Africana Tracker.\n"
            f"Block time: {flight_time_mins // 60:02d}:{flight_time_mins % 60:02d}\n"
            f"Distance flown: {distance_nm:.1f} nm\n"
            f"Fuel used: {fuel_used:.0f} lbs\n"
            f"Landing rate: {landing_rate:.0f} fpm"
        )

        def _file():
            ok = self._vms.file_pirep(
                flight_time_min=flight_time_mins,
                fuel_used=fuel_used,
                distance_nm=distance_nm,
                landing_rate=landing_rate,
                log_text=log_text,
            )
            self._pirep_file_result.emit(ok)

        self._vms_sync.submit(_file)

    @pyqtSlot(bool)
    def _on_pirep_filed(self, success: bool):
        if success:
            log.info("PIREP filed successfully on Africana Virtual Airways.")
            self._statusbar.showMessage("PIREP filed on phpVMS.")
        else:
            self._statusbar.showMessage("PIREP filing failed — see logs.")

    def _post_flight_log(self, payload: dict):
        import threading, requests as req
        server = config.get("server_url", "http://localhost:8765")
        def _post():
            try:
                req.post(f"{server}/api/flights/complete", json=payload, timeout=10)
            except Exception as e:
                log.warning("Failed to post flight log: %s", e)
        threading.Thread(target=_post, daemon=True).start()

    # ------------------------------------------------------------------
    # Network client — multi-pilot ecosystem
    # ------------------------------------------------------------------

    def _start_network_client(self):
        pid = config.get("vatsim_cid", "")
        if not pid:
            return
        if self._net_client and self._net_client.isRunning():
            self._net_client.stop()
            self._net_client.wait(2000)

        server = config.get("server_url", "http://localhost:8765")
        self._net_client = NetworkClient(server_url=server, pilot_id=pid, parent=self)  # pid = vatsim_cid
        self._net_client.connected.connect(self._on_net_connected)
        self._net_client.disconnected.connect(self._on_net_disconnected)
        self._net_client.roster_received.connect(self._on_roster_received)
        self._net_client.pilot_update.connect(self._on_remote_pilot_update)
        self._net_client.pilot_offline.connect(self._on_pilot_offline)
        self._net_client.gate_assigned.connect(self._on_remote_gate_assigned)
        self._net_client.gate_released.connect(self._on_remote_gate_released)
        self._net_client.start()

    @pyqtSlot()
    def _on_net_connected(self):
        self._dot_network.set_connected(True, "Network")
        self._statusbar.showMessage("Network: connected to AFV ecosystem.")

    @pyqtSlot()
    def _on_net_disconnected(self):
        self._dot_network.set_connected(False)

    @pyqtSlot(list)
    def _on_roster_received(self, pilots: list):
        self._online_pilots = {p.get("pilot_id", ""): p for p in pilots}
        own_cid = config.get("vatsim_cid", "")
        for p in pilots:
            if p.get("pilot_id") != own_cid:
                self._network_panel.update_pilot(p)

    @pyqtSlot(dict)
    def _on_remote_pilot_update(self, data: dict):
        pid = data.get("pilot_id", "")
        self._online_pilots[pid] = data
        self._network_panel.update_pilot(data)

    @pyqtSlot(str)
    def _on_pilot_offline(self, pilot_id: str):
        self._online_pilots.pop(pilot_id, None)
        self._network_panel.remove_pilot(pilot_id)

    @pyqtSlot(dict)
    def _on_remote_gate_assigned(self, data: dict):
        airport = data.get("airport", "")
        dest    = self._ofp.destination_icao if self._ofp else ""
        self._network_panel.mark_gate_assigned(
            airport, data.get("gate_number", ""), data.get("pilot_name", "")
        )
        # If it's our destination, also update the status bar
        if dest and airport == dest:
            pilot = data.get("pilot_name") or data.get("pilot_id", "")
            self._statusbar.showMessage(
                f"Gate {data.get('gate_number')} at {airport} assigned to {pilot}."
            )

    @pyqtSlot(dict)
    def _on_remote_gate_released(self, data: dict):
        self._network_panel.mark_gate_released(
            data.get("airport", ""), data.get("gate_number", "")
        )

    def _broadcast_own_telemetry(self, tel: Telemetry):
        """Push our own telemetry to all other connected pilots."""
        if not self._net_client or not self._net_client.isRunning():
            return
        if not self._ofp:
            return
        phase_str = self._flight_tracker.phase.value if self._flight_tracker else "UNKNOWN"
        self._net_client.send_pilot_update({
            "pilot_id":      config.get("vatsim_cid", ""),
            "name":          config.get("pilot_name", ""),
            "phase":         phase_str,
            "lat":           tel.latitude,
            "lon":           tel.longitude,
            "alt":           tel.altitude_ft,
            "gs":            tel.groundspeed_kts,
            "origin":        self._ofp.origin_icao,
            "destination":   self._ofp.destination_icao,
            "flight_number": self._ofp.flight_number,
        })

    def closeEvent(self, event):
        # Hide to tray instead of quitting — MSFS watcher keeps running in background.
        event.ignore()
        self.hide()
        self._tray.showMessage(
            "AFV Tracker",
            "Running in the background. Double-click the tray icon to restore.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )

    def _quit_app(self):
        """Full quit — called from tray menu or MSFS close."""
        self._stop_tracking()
        if self._net_client:
            self._net_client.stop()
            self._net_client.wait(2000)
        if self._discord:
            self._discord.close()
        self._vms_sync.close()
        QApplication.quit()


# ── Airport coordinates (lat, lon) for distance calc ──────────────────────────
# Seeded for AFV hub airports + additional African airports

_AIRPORT_COORDS: dict[str, tuple[float, float]] = {
    # ── Live DB airports ──────────────────────────────────────────────────────
    "DAAG": ( 36.6910,   3.2154),  # Algiers Houari Boumediene
    "DNMM": (  6.5774,   3.3214),  # Lagos Murtala Muhammed
    "DTTA": ( 36.8510,  10.2272),  # Tunis Carthage
    "EDDF": ( 50.0264,   8.5431),  # Frankfurt
    "EGLL": ( 51.4775,  -0.4614),  # London Heathrow
    "FACT": (-33.9648,  18.6017),  # Cape Town
    "FALE": (-29.6144,  31.1197),  # Durban King Shaka
    "FAOR": (-26.1339,  28.2421),  # Johannesburg OR Tambo
    "FQBR": (-19.7964,  34.9076),  # Beira
    "FQMA": (-25.9208,  32.5726),  # Maputo
    "FQNC": (-14.4882,  40.5123),  # Nacala
    "FQPB": (-12.9917,  40.5240),  # Pemba
    "FZAA": ( -4.3858,  15.4446),  # Kinshasa N'Djili
    "HKJK": ( -1.3192,  36.9275),  # Nairobi Jomo Kenyatta
    "KORD": ( 41.9742, -87.9073),  # Chicago O'Hare
    "LFPG": ( 49.0097,   2.5479),  # Paris Charles de Gaulle
    "NZAA": (-37.0082, 174.7850),  # Auckland
    "SBGR": (-23.4356, -46.4731),  # São Paulo Guarulhos
    "YSSY": (-33.9461, 151.1772),  # Sydney Kingsford Smith
    # ── Additional AFV hubs ───────────────────────────────────────────────────
    "FTTG": ( 12.1337,  15.0340),  # N'Djamena
    "FMMI": (-18.7969,  47.4788),  # Antananarivo
    "HTDA": ( -6.8781,  39.2026),  # Dar es Salaam
    "FALA": (-25.9385,  27.9261),  # Johannesburg Lanseria
    "HAAB": (  8.9779,  38.7993),  # Addis Ababa
    "HECA": ( 30.1219,  31.4056),  # Cairo
    "GOBD": ( 14.7397, -17.4902),  # Dakar
    "DIAP": (  5.2594,  -3.9263),  # Abidjan
    "GMME": ( 33.9997,  -6.7519),  # Rabat
    "FBSK": (-24.5552,  25.9182),  # Gaborone
    "FYWH": (-22.4799,  17.4709),  # Windhoek
    "FLEW": (-15.3308,  28.4522),  # Lusaka
    "FVHA": (-17.9318,  31.0928),  # Harare
    "FANS": (-29.6242,  27.4790),  # Maseru
    "FDSK": (-26.3586,  31.7168),  # Manzini
    # ── Middle East / Gulf ────────────────────────────────────────────────────
    "OMDB": ( 25.2528,  55.3644),  # Dubai International
    "OMDW": ( 24.8963,  55.1717),  # Dubai World Central
    "OMAA": ( 24.4430,  54.6511),  # Abu Dhabi
    "OTHH": ( 25.2731,  51.6086),  # Doha Hamad
    "OEJN": ( 21.6796,  39.1565),  # Jeddah
    "OEDF": ( 26.4712,  49.7979),  # Dammam
    "OEAA": ( 24.9576,  46.6988),  # Riyadh
    "OOMS": ( 23.5933,  58.2844),  # Muscat
    "OKBK": ( 29.2266,  47.9689),  # Kuwait
    # ── Asia ─────────────────────────────────────────────────────────────────
    "VABB": ( 19.0896,  72.8656),  # Mumbai
    "VIDP": ( 28.5562,  77.1000),  # Delhi
    "WSSS": (  1.3644, 103.9915),  # Singapore Changi
    "VHHH": ( 22.3080, 113.9185),  # Hong Kong
    "ZBAA": ( 40.0801, 116.5846),  # Beijing Capital
    # ── Turkey ───────────────────────────────────────────────────────────────
    "LTFM": ( 41.2753,  28.7519),  # Istanbul
    # ── North America ────────────────────────────────────────────────────────
    "KBOS": ( 42.3656, -71.0096),  # Boston Logan
    # ── Europe ───────────────────────────────────────────────────────────────
    "LPPT": ( 38.7813,  -9.1359),  # Lisbon Humberto Delgado
}
