"""
ChessGym
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Clean chess GUI with Stockfish engine + optional opening book.
PyQt6 version — HD/4K quality with vector piece rendering.

Install: py -m pip install python-chess PyQt6 PyQt6-sip
Run:     py main.py
"""

import sys, os, threading, time, struct, subprocess, json, random, datetime
import math, wave, tempfile, logging, traceback, shutil, zipfile
import urllib.request, ssl, requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_sound_muted = False

def play_menu_click():
    if _sound_muted:
        return
    try:
        def _play():
            try:
                sample_rate = 44100
                duration = 0.05
                frequency = 1600
                num_samples = int(sample_rate * duration)
                samples = []
                for i in range(num_samples):
                    t = i / sample_rate
                    envelope = math.exp(-t / (duration * 0.4))
                    sample = math.sin(2 * math.pi * frequency * t) * envelope * 0.35
                    int_sample = max(-32767, min(32767, int(sample * 32767)))
                    samples.append(int_sample)
                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp_path = tmp.name
                tmp.close()
                with wave.open(tmp_path, 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(struct.pack('<' + 'h' * num_samples, *samples))
                import winsound
                winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                time.sleep(0.3)
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            except (Exception, SystemExit):
                pass
        threading.Thread(target=_play, daemon=True).start()
    except (Exception, SystemExit):
        pass


def play_move_sound():
    """Soft thud — deep muffled impact of a heavy piece on wood."""
    if _sound_muted:
        return
    try:
        def _play():
            try:
                sample_rate = 44100
                total_duration = 0.15
                num_samples = int(sample_rate * total_duration)
                samples = [0.0] * num_samples

                # Component 1: noise burst (0.15s, power-5 decay, lowpass@300Hz, gain=0.5)
                lp_rc = 1.0 / (2.0 * math.pi * 300.0)
                lp_alpha = 1.0 / (1.0 + sample_rate * lp_rc)
                prev = 0.0
                for i in range(num_samples):
                    t = i / sample_rate
                    raw = random.uniform(-1.0, 1.0)
                    prev = prev + lp_alpha * (raw - prev)
                    env = (1.0 - t / total_duration) ** 5
                    samples[i] += prev * env * 0.5

                # Component 2: low sine tone 1 (120Hz, 0.12s, exponential decay, gain=0.25)
                n2 = int(sample_rate * 0.12)
                for i in range(n2):
                    t = i / sample_rate
                    env = math.exp(-t / 0.03)
                    samples[i] += math.sin(2.0 * math.pi * 120.0 * t) * env * 0.25

                # Component 3: low sine tone 2 (80Hz, 0.10s, exponential decay, gain=0.15)
                n3 = int(sample_rate * 0.10)
                for i in range(n3):
                    t = i / sample_rate
                    env = math.exp(-t / 0.025)
                    samples[i] += math.sin(2.0 * math.pi * 80.0 * t) * env * 0.15

                # Normalize to prevent clipping
                peak = max(abs(s) for s in samples)
                if peak > 0:
                    scale = 0.9 / peak
                    samples = [s * scale for s in samples]

                # Convert to 16-bit PCM
                int_samples = []
                for s in samples:
                    int_samples.append(max(-32767, min(32767, int(s * 32767))))

                tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
                tmp_path = tmp.name
                tmp.close()
                with wave.open(tmp_path, 'w') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(sample_rate)
                    wf.writeframes(struct.pack('<' + 'h' * num_samples, *int_samples))
                import winsound
                winsound.PlaySound(tmp_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                time.sleep(0.3)
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            except (Exception, SystemExit):
                pass
        threading.Thread(target=_play, daemon=True).start()
    except (Exception, SystemExit):
        pass

# -- High DPI support (must be set BEFORE QApplication) ---------------------
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

import chess, chess.engine, chess.pgn
import position_scanner

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QTextBrowser,
    QListWidget, QListWidgetItem, QProgressBar, QFileDialog, QSizePolicy,
    QScrollArea, QDialog, QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QLineEdit,
    QGridLayout,
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QFontDatabase, QPen, QBrush,
    QShortcut, QKeySequence, QPalette, QMouseEvent, QPaintEvent,
    QResizeEvent, QCursor, QRadialGradient, QLinearGradient, QIcon,
)
from PyQt6.QtCore import (
    Qt, QTimer, QRectF, QRect, QPointF, QPoint, QSize, pyqtSignal, QEvent, QUrl,
    QPropertyAnimation, QEasingCurve, QByteArray, QThread, QObject,
)
from PyQt6.QtSvg import QSvgRenderer

# -- Base directory (works in PyInstaller exe and normal script) -------------
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)          # writable: config, saves, logs
    RESOURCE_DIR = getattr(sys, '_MEIPASS', BASE_DIR)    # read-only bundled assets
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = BASE_DIR

# -- Opening Trainer error logger --------------------------------------------
_OT_LOG_PATH = os.path.join(BASE_DIR, "chessgym_errors.log")
_ot_logger = logging.getLogger("chessgym")
_ot_logger.setLevel(logging.DEBUG)
try:
    _ot_log_handler = logging.FileHandler(_OT_LOG_PATH, encoding="utf-8")
    _ot_log_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s"))
    _ot_logger.addHandler(_ot_log_handler)
except Exception:
    pass  # If log file can't be opened, continue without file logging

def _ot_excepthook(exc_type, exc_value, exc_tb):
    """Global exception handler — log to file and show friendly message."""
    if exc_type is KeyboardInterrupt:
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _ot_logger.error("Unhandled exception:\n%s", msg)
    # Try to show a friendly dialog instead of crashing silently
    try:
        from PyQt6.QtWidgets import QMessageBox
        app = QApplication.instance()
        if app:
            QMessageBox.warning(
                None, "ChessGym Error",
                "An unexpected error occurred. Details have been logged to "
                "chessgym_errors.log.\n\nThe app will try to continue.")
    except Exception:
        pass
    # Fall through to default handler so Python still prints to stderr
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _ot_excepthook

# -- App icon helper ---------------------------------------------------------
def get_app_icon():
    ico = os.path.join(RESOURCE_DIR, "icon.ico")
    svg = os.path.join(RESOURCE_DIR, "icon.svg")
    if os.path.exists(ico):
        return QIcon(ico)
    elif os.path.exists(svg):
        return QIcon(svg)
    return QIcon()

# -- SVG piece loader -------------------------------------------------------
try:
    from svg_loader import svg_to_qpixmap as _svg_to_qpixmap
    _SVG_OK = True
except Exception:
    _SVG_OK = False

# -- Font setup --------------------------------------------------------------
_UI_FONT = "DM Sans"
_MONO_FONT = "Courier New"
_FONT_WEIGHT = QFont.Weight.Light   # 300

def _detect_fonts():
    global _UI_FONT, _MONO_FONT
    families = QFontDatabase.families()
    # Try DM Sans first, then Segoe UI, then Arial
    if "DM Sans" in families:
        _UI_FONT = "DM Sans"
    elif "Segoe UI" in families:
        _UI_FONT = "Segoe UI"
    else:
        _UI_FONT = "Arial"
    if "Courier New" not in families:
        _MONO_FONT = "Consolas" if "Consolas" in families else "Courier"

# ============================================================================
#  THEMES
# ============================================================================

THEMES = {
    "soft_light": {
        "bg": "#1e2d42",
        "section_bg": "rgba(200,225,255,0.05)",
        "section_border": "rgba(200,225,255,0.09)",
        "title": "#f0f8ff",
        "text_primary": "rgba(200,225,255,0.8)",
        "text_muted": "rgba(180,215,255,0.55)",
        "accent_bg": "rgba(147,197,253,0.15)",
        "accent_border": "rgba(147,197,253,0.28)",
        "accent_text": "#c8e4ff",
        "btn_bg": "rgba(200,225,255,0.05)",
        "btn_border": "rgba(200,225,255,0.1)",
        "btn_text": "rgba(180,215,255,0.6)",
        "menu_bg": "rgba(200,225,255,0.07)",
        "menu_border": "rgba(200,225,255,0.15)",
        "menu_text": "rgba(220,235,255,0.85)",
        "menu_hover_bg": "rgba(200,225,255,0.11)",
        "menu_hover_border": "rgba(200,225,255,0.22)",
        "dot": "#1e2d42",
        "dot_accent": "rgba(147,197,253,0.5)",
        "pill_bg": "rgba(200,225,255,0.07)",
        "pill_border": "rgba(200,225,255,0.15)",
        "pill_arrow": "rgba(180,215,255,0.6)",
        "pill_num": "#e8f4ff",
        "pill_divider": "rgba(200,225,255,0.1)",
        "pill_label": "rgba(200,225,255,0.8)",
        "book_bg": "rgba(200,225,255,0.05)",
        "book_border": "rgba(200,225,255,0.12)",
        "book_text": "rgba(180,215,255,0.6)",
        "book_btn_bg": "rgba(200,225,255,0.07)",
        "book_btn_border": "rgba(200,225,255,0.15)",
        "book_btn_text": "rgba(180,215,255,0.7)",
        "book_label": "rgba(200,225,255,0.75)",
        "section_label": "rgba(180,215,255,0.45)",
        "toggle_active_bg": "rgba(147,197,253,0.18)",
        "toggle_active_border": "rgba(147,197,253,0.25)",
        "toggle_active_text": "#c8e4ff",
        "toggle_inactive_text": "rgba(147,197,253,0.45)",
        "scrollbar": "rgba(255,255,255,0.08)",
        "scrollbar_hover": "rgba(255,255,255,0.15)",
    },
    "wisteria_mist": {
        "bg": "#F5F2FC",
        "section_bg": "rgba(180,160,230,0.12)",
        "section_border": "#C8B8EC",
        "title": "#4A3070",
        "text_primary": "#4A3070",
        "text_muted": "#6858A0",
        "accent_bg": "#8868C0",
        "accent_border": "#6848A8",
        "accent_text": "#ffffff",
        "btn_bg": "rgba(180,160,230,0.15)",
        "btn_border": "#C0A8E8",
        "btn_text": "#4A3070",
        "menu_bg": "rgba(180,160,230,0.15)",
        "menu_border": "#C0A8E8",
        "menu_text": "#4A3070",
        "menu_hover_bg": "rgba(136,104,192,0.25)",
        "menu_hover_border": "#8868C0",
        "dot": "#D8D0F0",
        "dot_accent": "#8868C0",
        "pill_bg": "rgba(180,160,230,0.1)",
        "pill_border": "#C0A8E8",
        "pill_arrow": "#6858A0",
        "pill_num": "#4A3070",
        "pill_divider": "rgba(180,160,230,0.2)",
        "pill_label": "#4A3070",
        "book_bg": "rgba(180,160,230,0.08)",
        "book_border": "#C8B8EC",
        "book_text": "#6858A0",
        "book_btn_bg": "rgba(180,160,230,0.15)",
        "book_btn_border": "#C0A8E8",
        "book_btn_text": "#4A3070",
        "book_label": "#4A3070",
        "section_label": "#7860A8",
        "toggle_active_bg": "#8868C0",
        "toggle_active_border": "#6848A8",
        "toggle_active_text": "#ffffff",
        "toggle_inactive_text": "#6858A0",
        "scrollbar": "rgba(180,160,230,0.2)",
        "scrollbar_hover": "rgba(180,160,230,0.35)",
    },
    "espresso": {
        "bg": "#4a3020",
        "section_bg": "rgba(200,210,220,0.06)",
        "section_border": "rgba(200,210,220,0.12)",
        "title": "#d8dde2",
        "text_primary": "#d8dde2",
        "text_muted": "rgba(200,210,220,0.4)",
        "accent_bg": "rgba(200,210,220,0.13)",
        "accent_border": "rgba(200,210,220,0.28)",
        "accent_text": "#d8dde2",
        "btn_bg": "rgba(200,210,220,0.08)",
        "btn_border": "rgba(200,210,220,0.15)",
        "btn_text": "#c8d4de",
        "menu_bg": "rgba(200,210,220,0.08)",
        "menu_border": "rgba(200,210,220,0.15)",
        "menu_text": "rgba(200,210,220,0.85)",
        "menu_hover_bg": "rgba(200,210,220,0.13)",
        "menu_hover_border": "rgba(200,210,220,0.25)",
        "dot": "#7a5035",
        "dot_accent": "rgba(200,215,225,0.4)",
        "pill_bg": "rgba(200,210,220,0.07)",
        "pill_border": "rgba(200,210,220,0.15)",
        "pill_arrow": "rgba(200,210,220,0.55)",
        "pill_num": "#d8dde2",
        "pill_divider": "rgba(200,210,220,0.1)",
        "pill_label": "#d8dde2",
        "book_bg": "rgba(200,210,220,0.06)",
        "book_border": "rgba(200,210,220,0.12)",
        "book_text": "rgba(200,210,220,0.55)",
        "book_btn_bg": "rgba(200,210,220,0.08)",
        "book_btn_border": "rgba(200,210,220,0.15)",
        "book_btn_text": "rgba(200,210,220,0.65)",
        "book_label": "rgba(200,210,220,0.75)",
        "section_label": "rgba(200,210,220,0.4)",
        "toggle_active_bg": "rgba(200,210,220,0.16)",
        "toggle_active_border": "rgba(200,210,220,0.28)",
        "toggle_active_text": "#d8dde2",
        "toggle_inactive_text": "rgba(200,210,220,0.45)",
        "scrollbar": "rgba(200,210,220,0.2)",
        "scrollbar_hover": "rgba(200,210,220,0.35)",
    },
    "lemon_creme": {
        "bg": "#fef7cc",
        "section_bg": "rgba(44,42,0,0.05)",
        "section_border": "rgba(44,42,0,0.13)",
        "title": "#2c2a00",
        "text_primary": "#2c2a00",
        "text_muted": "rgba(44,42,0,0.5)",
        "accent_bg": "rgba(44,42,0,0.13)",
        "accent_border": "rgba(44,42,0,0.25)",
        "accent_text": "#2c2a00",
        "btn_bg": "rgba(44,42,0,0.07)",
        "btn_border": "rgba(44,42,0,0.18)",
        "btn_text": "#2c2a00",
        "menu_bg": "rgba(44,42,0,0.07)",
        "menu_border": "rgba(44,42,0,0.18)",
        "menu_text": "#2c2a00",
        "menu_hover_bg": "rgba(44,42,0,0.12)",
        "menu_hover_border": "rgba(44,42,0,0.25)",
        "dot": "#c8b400",
        "dot_accent": "rgba(44,42,0,0.35)",
        "pill_bg": "rgba(44,42,0,0.06)",
        "pill_border": "rgba(44,42,0,0.16)",
        "pill_arrow": "rgba(44,42,0,0.6)",
        "pill_num": "#2c2a00",
        "pill_divider": "rgba(44,42,0,0.1)",
        "pill_label": "#2c2a00",
        "book_bg": "rgba(44,42,0,0.05)",
        "book_border": "rgba(44,42,0,0.13)",
        "book_text": "rgba(44,42,0,0.55)",
        "book_btn_bg": "rgba(44,42,0,0.07)",
        "book_btn_border": "rgba(44,42,0,0.18)",
        "book_btn_text": "rgba(44,42,0,0.6)",
        "book_label": "#2c2a00",
        "section_label": "rgba(44,42,0,0.5)",
        "toggle_active_bg": "rgba(44,42,0,0.13)",
        "toggle_active_border": "rgba(44,42,0,0.25)",
        "toggle_active_text": "#1a1800",
        "toggle_inactive_text": "rgba(44,42,0,0.45)",
        "scrollbar": "rgba(44,42,0,0.2)",
        "scrollbar_hover": "rgba(44,42,0,0.35)",
    },
    "slate_linen": {
        "bg": "#EEF1F5",
        "section_bg": "rgba(100,130,160,0.1)",
        "section_border": "#B0C0D0",
        "title": "#1E2A35",
        "text_primary": "#1E2A35",
        "text_muted": "#3A5870",
        "accent_bg": "#4A7090",
        "accent_border": "#2A4860",
        "accent_text": "#EEF1F5",
        "btn_bg": "rgba(100,130,160,0.15)",
        "btn_border": "#A8B8C8",
        "btn_text": "#1E2A35",
        "menu_bg": "rgba(100,130,160,0.15)",
        "menu_border": "#A8B8C8",
        "menu_text": "#1E2A35",
        "menu_hover_bg": "rgba(74,112,144,0.25)",
        "menu_hover_border": "#4A7090",
        "dot": "#C8D0D8",
        "dot_accent": "#4A7090",
        "pill_bg": "rgba(100,130,160,0.1)",
        "pill_border": "#A8B8C8",
        "pill_arrow": "#3A5870",
        "pill_num": "#1E2A35",
        "pill_divider": "rgba(100,130,160,0.2)",
        "pill_label": "#1E2A35",
        "book_bg": "rgba(100,130,160,0.08)",
        "book_border": "#B0C0D0",
        "book_text": "#3A5870",
        "book_btn_bg": "rgba(100,130,160,0.15)",
        "book_btn_border": "#A8B8C8",
        "book_btn_text": "#1E2A35",
        "book_label": "#1E2A35",
        "section_label": "#4A6070",
        "toggle_active_bg": "#4A7090",
        "toggle_active_border": "#2A4860",
        "toggle_active_text": "#EEF1F5",
        "toggle_inactive_text": "#3A5870",
        "scrollbar": "rgba(100,130,160,0.2)",
        "scrollbar_hover": "rgba(100,130,160,0.35)",
    },
    "sage_stone": {
        "bg": "#EDF2E8",
        "section_bg": "rgba(130,160,120,0.12)",
        "section_border": "#A8C0A0",
        "title": "#2A3828",
        "text_primary": "#2A3828",
        "text_muted": "#4A6845",
        "accent_bg": "#5A8050",
        "accent_border": "#3A5835",
        "accent_text": "#EDF2E8",
        "btn_bg": "rgba(130,160,120,0.18)",
        "btn_border": "#A8C0A0",
        "btn_text": "#2A3828",
        "menu_bg": "rgba(130,160,120,0.18)",
        "menu_border": "#A8C0A0",
        "menu_text": "#2A3828",
        "menu_hover_bg": "rgba(90,128,80,0.25)",
        "menu_hover_border": "#5A8050",
        "dot": "#C0D0B8",
        "dot_accent": "#5A8050",
        "pill_bg": "rgba(130,160,120,0.1)",
        "pill_border": "#A8C0A0",
        "pill_arrow": "#4A6845",
        "pill_num": "#2A3828",
        "pill_divider": "rgba(130,160,120,0.2)",
        "pill_label": "#2A3828",
        "book_bg": "rgba(130,160,120,0.08)",
        "book_border": "#A8C0A0",
        "book_text": "#4A6845",
        "book_btn_bg": "rgba(130,160,120,0.18)",
        "book_btn_border": "#A8C0A0",
        "book_btn_text": "#2A3828",
        "book_label": "#2A3828",
        "section_label": "#4A6845",
        "toggle_active_bg": "#5A8050",
        "toggle_active_border": "#3A5835",
        "toggle_active_text": "#EDF2E8",
        "toggle_inactive_text": "#4A6845",
        "scrollbar": "rgba(130,160,120,0.2)",
        "scrollbar_hover": "rgba(130,160,120,0.35)",
    },
    "light_oak": {
        "bg": "#F5ECD8",
        "section_bg": "rgba(160,110,50,0.1)",
        "section_border": "#C8A060",
        "title": "#3D2508",
        "text_primary": "#3D2508",
        "text_muted": "#6A4420",
        "accent_bg": "#8B5E28",
        "accent_border": "#5C3A10",
        "accent_text": "#F5ECD8",
        "btn_bg": "rgba(160,110,50,0.12)",
        "btn_border": "#C09050",
        "btn_text": "#3D2508",
        "menu_bg": "rgba(160,110,50,0.12)",
        "menu_border": "#C09050",
        "menu_text": "#3D2508",
        "menu_hover_bg": "rgba(139,94,40,0.25)",
        "menu_hover_border": "#8B5E28",
        "dot": "#D8C8A0",
        "dot_accent": "#8B5E28",
        "pill_bg": "rgba(160,110,50,0.08)",
        "pill_border": "#C09050",
        "pill_arrow": "#6A4420",
        "pill_num": "#3D2508",
        "pill_divider": "rgba(160,110,50,0.18)",
        "pill_label": "#3D2508",
        "book_bg": "rgba(160,110,50,0.07)",
        "book_border": "#C8A060",
        "book_text": "#6A4420",
        "book_btn_bg": "rgba(160,110,50,0.12)",
        "book_btn_border": "#C09050",
        "book_btn_text": "#3D2508",
        "book_label": "#3D2508",
        "section_label": "#7A4D18",
        "toggle_active_bg": "#8B5E28",
        "toggle_active_border": "#5C3A10",
        "toggle_active_text": "#F5ECD8",
        "toggle_inactive_text": "#6A4420",
        "scrollbar": "rgba(160,110,50,0.18)",
        "scrollbar_hover": "rgba(160,110,50,0.32)",
    },
}

THEME_ORDER = ["soft_light", "slate_linen", "sage_stone", "light_oak", "wisteria_mist"]
_LIGHT_THEMES = {"slate_linen", "sage_stone", "wisteria_mist", "light_oak"}


def _stat_green():
    return "rgba(0,140,60,0.95)" if _current_theme_name in _LIGHT_THEMES else "rgba(80,200,120,0.9)"

def _stat_red():
    return "rgba(180,0,0,0.9)" if _current_theme_name in _LIGHT_THEMES else "rgba(220,80,80,0.85)"

def _stat_blue():
    return "rgba(0,100,200,0.9)" if _current_theme_name in _LIGHT_THEMES else "rgba(147,197,253,0.85)"

def _stat_red_bright():
    return "rgba(180,0,0,0.9)" if _current_theme_name in _LIGHT_THEMES else "rgba(220,80,80,0.9)"


# -- Active theme state (mutable, updated by set_theme) ---------------------
_current_theme_name = "soft_light"
T = dict(THEMES["soft_light"])


def set_theme(name):
    """Switch the active theme globally and update color aliases."""
    global _current_theme_name, T
    global BG, PANEL_BG, BORDER_CLR, TEXT_COL, MUTED, SEC_TEXT, ACCENT
    global BTN_BG, BTN_BORDER, BTN_TEXT, BTN_H_BG, BTN_H_BORDER, BTN_H_TEXT
    global SEP_COLOR, SECTION_LBL, CLK_ACT, CLK_INACT
    global CLK_FRAME_BG, CLK_FRAME_BORDER, CLK_ACTIVE_BORDER, CLK_ACTIVE_BG
    global BORDER_COL, ERROR_CLR

    if name not in THEMES:
        return
    _current_theme_name = name
    t = THEMES[name]
    T.update(t)

    # Map theme values to legacy color aliases used throughout the code
    BG          = t["bg"]
    PANEL_BG    = t["bg"]
    BORDER_CLR  = t["section_border"]
    TEXT_COL    = t["title"]
    MUTED       = t["text_muted"]
    SEC_TEXT     = t["text_primary"]
    ACCENT      = t["accent_text"]
    BTN_BG      = t["btn_bg"]
    BTN_BORDER  = t["btn_border"]
    BTN_TEXT    = t["btn_text"]
    BTN_H_BG    = t["accent_bg"]
    BTN_H_BORDER= t["accent_border"]
    BTN_H_TEXT  = t["title"]
    SEP_COLOR   = t["section_border"]
    SECTION_LBL = t["text_muted"]
    ERROR_CLR   = "#ff6b6b"
    BORDER_COL  = t["bg"]
    CLK_ACT     = t["accent_text"]
    CLK_INACT   = t["text_muted"]
    CLK_FRAME_BG      = t["section_bg"]
    CLK_FRAME_BORDER  = t["section_border"]
    CLK_ACTIVE_BORDER = t["accent_border"]
    CLK_ACTIVE_BG     = t["accent_bg"]

# ============================================================================
#  LEGACY COLOR ALIASES — initialized from default theme
# ============================================================================

BG          = "#1e2d42"
PANEL_BG    = "#1e2d42"
BORDER_CLR  = "rgba(200,225,255,0.09)"
TEXT_COL    = "#f0f8ff"
MUTED       = "rgba(180,215,255,0.55)"
SEC_TEXT     = "rgba(200,225,255,0.8)"
ACCENT      = "#c8e4ff"
BTN_BG      = "rgba(200,225,255,0.05)"
BTN_BORDER  = "rgba(200,225,255,0.1)"
BTN_TEXT    = "rgba(180,215,255,0.6)"
BTN_H_BG    = "rgba(147,197,253,0.15)"
BTN_H_BORDER= "rgba(147,197,253,0.28)"
BTN_H_TEXT  = "#f0f8ff"
SEP_COLOR   = "rgba(200,225,255,0.09)"
ERROR_CLR   = "#ff6b6b"
SECTION_LBL = "rgba(180,215,255,0.55)"

# Board square colors — NEVER change with theme
LIGHT_SQ = "#EAC388"; DARK_SQ = "#A0724E"
BORDER_COL = "#1e2d42"

# Clock
CLK_ACT     = ACCENT
CLK_INACT   = "rgba(180,215,255,0.55)"

# Clock frame styles
CLK_FRAME_BG      = "rgba(200,225,255,0.05)"
CLK_FRAME_BORDER  = "rgba(200,225,255,0.09)"
CLK_ACTIVE_BORDER = "rgba(147,197,253,0.28)"
CLK_ACTIVE_BG     = "rgba(147,197,253,0.15)"

SQ = 80; BOARD_PX = SQ * 8; BOARD_OX = 10; BOARD_OY = 10

def _frost_scrollbar_ss():
    sb = T.get('scrollbar', 'rgba(255,255,255,0.08)')
    sbh = T.get('scrollbar_hover', 'rgba(255,255,255,0.15)')
    return f"""
    QScrollBar:vertical {{
        background: {T['bg']}; width: 8px; margin: 0;
        border: none;
    }}
    QScrollBar::handle:vertical {{
        background: {sb}; min-height: 30px;
        border-radius: 4px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {sbh};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0; background: none;
    }}
    QScrollBar:horizontal {{
        background: {T['bg']}; height: 8px; margin: 0;
        border: none;
    }}
    QScrollBar::handle:horizontal {{
        background: {sb}; min-width: 30px;
        border-radius: 4px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0; background: none;
    }}
"""

# -- Keep FROST_GLOBAL_SS as a backwards-compat alias (used in hardcoded strings) --
FROST_GLOBAL_SS = _frost_scrollbar_ss()

# -- Opening Book System (PGN + CTG) ------------------------------------------

def load_book_file(path):
    if not path or not os.path.isfile(path):
        return None
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext == ".pgn":
            return _load_pgn_book(path)
        elif ext == ".ctg":
            return _load_ctg_book(path)
    except Exception as e:
        print(f"Book load error ({os.path.basename(path)}): {e}")
    return None

def _load_pgn_book(path):
    book = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        while True:
            game = chess.pgn.read_game(f)
            if game is None:
                break
            _pgn_walk(game, chess.Board(), book)
    book = {k: list(v) for k, v in book.items()}
    print(f"PGN book: {len(book)} positions from {os.path.basename(path)}")
    return book if book else None

def _pgn_walk(node, board, book):
    for child in node.variations:
        fk = " ".join(board.fen().split()[:2])
        if fk not in book:
            book[fk] = set()
        book[fk].add(child.move.uci())
        board.push(child.move)
        _pgn_walk(child, board, book)
        board.pop()

def _load_ctg_book(ctg_path):
    base = os.path.splitext(ctg_path)[0]
    for ext in (".ctb", ".cto"):
        p = base + ext
        if not os.path.isfile(p):
            print(f"CTG: missing {os.path.basename(p)}")
            return None
    with open(ctg_path, 'rb') as f:
        ctg = f.read()
    book = {}
    HDR = 28; PAGE = 4096
    offset = HDR
    while offset + PAGE <= len(ctg):
        _ctg_scan_page(ctg[offset:offset + PAGE], book)
        offset += PAGE
    book = {k: list(v) for k, v in book.items()}
    n = len(book)
    if n:
        print(f"CTG book: {n} positions from {os.path.basename(ctg_path)}")
    else:
        print(f"CTG book: no positions found in {os.path.basename(ctg_path)}")
    return book if book else None

_CTG_PIECE = {
    0: None,
    1: chess.Piece(chess.PAWN, chess.WHITE),
    2: chess.Piece(chess.KNIGHT, chess.WHITE),
    3: chess.Piece(chess.BISHOP, chess.WHITE),
    4: chess.Piece(chess.ROOK, chess.WHITE),
    5: chess.Piece(chess.QUEEN, chess.WHITE),
    6: chess.Piece(chess.KING, chess.WHITE),
    7: chess.Piece(chess.PAWN, chess.BLACK),
    8: chess.Piece(chess.KNIGHT, chess.BLACK),
    9: chess.Piece(chess.BISHOP, chess.BLACK),
    10: chess.Piece(chess.ROOK, chess.BLACK),
    11: chess.Piece(chess.QUEEN, chess.BLACK),
    12: chess.Piece(chess.KING, chess.BLACK),
}

def _ctg_scan_page(page, book):
    if len(page) < 6:
        return
    used = struct.unpack_from('>H', page, 0)[0]
    pos = 4
    end = min(4 + used, len(page))
    while pos < end - 1:
        elen = page[pos]
        if elen < 35 or pos + 1 + elen > end:
            break
        bd = _ctg_decode_board(page, pos + 1)
        if bd is not None:
            nm = page[pos + 34] if pos + 34 < end else 0
            mvs = _ctg_decode_moves(page, pos + 35, min(pos + 1 + elen, end), nm, bd)
            if mvs:
                fk = " ".join(bd.fen().split()[:2])
                if fk not in book:
                    book[fk] = set()
                book[fk].update(mvs)
        pos += 1 + elen

def _ctg_decode_board(page, off):
    if off + 33 > len(page):
        return None
    try:
        bd = chess.Board(fen=None)
        bd.clear_board()
        for i in range(32):
            hi = (page[off + i] >> 4) & 0x0F
            lo = page[off + i] & 0x0F
            if hi > 12 or lo > 12:
                return None
            p1 = _CTG_PIECE.get(hi)
            p2 = _CTG_PIECE.get(lo)
            if p1: bd.set_piece_at(i * 2, p1)
            if p2: bd.set_piece_at(i * 2 + 1, p2)
        fl = page[off + 32]
        bd.castling_rights = chess.BB_EMPTY
        if fl & 0x01: bd.castling_rights |= chess.BB_H1
        if fl & 0x02: bd.castling_rights |= chess.BB_A1
        if fl & 0x04: bd.castling_rights |= chess.BB_H8
        if fl & 0x08: bd.castling_rights |= chess.BB_A8
        bd.turn = chess.WHITE if (fl & 0x10) else chess.BLACK
        if len(bd.pieces(chess.KING, chess.WHITE)) != 1: return None
        if len(bd.pieces(chess.KING, chess.BLACK)) != 1: return None
        return bd
    except:
        return None

def _ctg_decode_moves(page, off, end, n, bd):
    moves = []
    p = off
    for _ in range(min(n, 20)):
        if p + 2 > end:
            break
        fsq, tsq = page[p], page[p + 1]
        p += 6
        if fsq >= 64 or tsq >= 64:
            continue
        try:
            mv = chess.Move(fsq, tsq)
            if mv in bd.legal_moves:
                moves.append(mv.uci())
            else:
                for pr in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT):
                    pm = chess.Move(fsq, tsq, promotion=pr)
                    if pm in bd.legal_moves:
                        moves.append(pm.uci()); break
        except:
            continue
    return moves

def get_book_move(board, book):
    if not book:
        return None
    fk = " ".join(board.fen().split()[:2])
    entries = book.get(fk)
    if not entries:
        return None
    legal = []
    for uci in entries:
        try:
            mv = chess.Move.from_uci(uci)
            if mv in board.legal_moves:
                legal.append(mv)
        except:
            continue
    return random.choice(legal) if legal else None

# -- Utilities ---------------------------------------------------------------

def find_stockfish():
    import shutil
    cwd = os.getcwd()
    candidates = [
        os.path.join(RESOURCE_DIR, "stockfish", "stockfish.exe"),
        os.path.join(RESOURCE_DIR, "stockfish", "stockfish"),
        os.path.join(BASE_DIR, "stockfish", "stockfish.exe"),
        os.path.join(BASE_DIR, "stockfish", "stockfish"),
        os.path.join(BASE_DIR, "stockfish.exe"), os.path.join(BASE_DIR, "stockfish"),
        os.path.join(cwd, "stockfish", "stockfish.exe"),
        os.path.join(cwd, "stockfish", "stockfish"),
        os.path.join(cwd, "stockfish.exe"), os.path.join(cwd, "stockfish"),
        os.path.abspath("stockfish.exe"), os.path.abspath("stockfish"),
    ]
    sf = shutil.which("stockfish") or shutil.which("stockfish.exe")
    if sf: candidates.insert(0, sf)
    print(f"[Stockfish] BASE_DIR: {BASE_DIR}")
    print(f"[Stockfish] cwd: {cwd}")
    for p in candidates:
        found = os.path.isfile(p)
        print(f"[Stockfish] checking: {p} -> {'FOUND' if found else 'not found'}")
        if found: return p
    return None

PIECE_MAP = {
    (chess.KING,   chess.WHITE): "wK", (chess.QUEEN,  chess.WHITE): "wQ",
    (chess.ROOK,   chess.WHITE): "wR", (chess.BISHOP, chess.WHITE): "wB",
    (chess.KNIGHT, chess.WHITE): "wN", (chess.PAWN,   chess.WHITE): "wP",
    (chess.KING,   chess.BLACK): "bK", (chess.QUEEN,  chess.BLACK): "bQ",
    (chess.ROOK,   chess.BLACK): "bR", (chess.BISHOP, chess.BLACK): "bB",
    (chess.KNIGHT, chess.BLACK): "bN", (chess.PAWN,   chess.BLACK): "bP",
}

# Lichess cburnett piece set — SVG filenames
_LICHESS_MAP = {
    (chess.KING,   chess.WHITE): "wK", (chess.QUEEN,  chess.WHITE): "wQ",
    (chess.ROOK,   chess.WHITE): "wR", (chess.BISHOP, chess.WHITE): "wB",
    (chess.KNIGHT, chess.WHITE): "wN", (chess.PAWN,   chess.WHITE): "wP",
    (chess.KING,   chess.BLACK): "bK", (chess.QUEEN,  chess.BLACK): "bQ",
    (chess.ROOK,   chess.BLACK): "bR", (chess.BISHOP, chess.BLACK): "bB",
    (chess.KNIGHT, chess.BLACK): "bN", (chess.PAWN,   chess.BLACK): "bP",
}

_PIECES_DIR = os.path.join(RESOURCE_DIR, "pieces")

# Cache for QSvgRenderer instances keyed by svg path
_svg_renderer_cache = {}

def load_piece_pixmaps(sq_size):
    """Load Lichess cburnett SVG pieces. Each piece fills 96% of square."""
    images = {}
    if os.path.isdir(_PIECES_DIR):
        margin_frac = 0.02  # 2% margin each side = 96% piece
        piece_px = max(1, int(sq_size * 0.96))
        offset = (sq_size - piece_px) // 2
        for key, fname in _LICHESS_MAP.items():
            svg_path = os.path.join(_PIECES_DIR, f"{fname}.svg")
            if not os.path.isfile(svg_path):
                continue
            try:
                if svg_path not in _svg_renderer_cache:
                    _svg_renderer_cache[svg_path] = QSvgRenderer(svg_path)
                renderer = _svg_renderer_cache[svg_path]
                if not renderer.isValid():
                    continue
                pm = QPixmap(sq_size, sq_size)
                pm.fill(Qt.GlobalColor.transparent)
                painter = QPainter(pm)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                renderer.render(painter, QRectF(offset, offset, piece_px, piece_px))
                painter.end()
                images[key] = pm
            except Exception as e:
                print(f"SVG load error ({fname}): {e}")
    loaded = len(images)
    total = len(_LICHESS_MAP)
    if loaded == total:
        print(f"[Pieces] All {total} Lichess cburnett SVG pieces loaded")
    elif loaded > 0:
        print(f"[Pieces] {loaded}/{total} SVG pieces loaded")
    else:
        print(f"[Pieces] No SVG pieces found in {_PIECES_DIR} — using fallback")
    return images


def draw_piece_painter(painter, piece_type, color, x, y, sq):
    s = sq / 80.0
    if color == chess.WHITE:
        fill_c = QColor("#ffffff"); out_c = QColor("#1a1a1a")
    else:
        fill_c = QColor("#1a1a1a"); out_c = QColor("#ffffff")
    lw = max(2, int(2.5 * s))
    painter.setPen(QPen(out_c, lw))
    painter.setBrush(QBrush(fill_c))
    def px(v): return int(x + v * s)
    def py_(v): return int(y + v * s)
    if piece_type == chess.PAWN:
        painter.drawRect(px(20), py_(65), int(40*s), int(7*s))
        painter.drawEllipse(px(30), py_(20), int(20*s), int(20*s))
    elif piece_type == chess.ROOK:
        painter.drawRect(px(15), py_(64), int(50*s), int(8*s))
        painter.drawRect(px(20), py_(56), int(40*s), int(9*s))
        painter.drawRect(px(24), py_(26), int(32*s), int(31*s))
    elif piece_type == chess.KNIGHT:
        painter.drawRect(px(15), py_(64), int(50*s), int(8*s))
        painter.drawRect(px(20), py_(56), int(40*s), int(9*s))
        painter.drawEllipse(px(24), py_(12), int(32*s), int(44*s))
    elif piece_type == chess.BISHOP:
        painter.drawRect(px(15), py_(64), int(50*s), int(8*s))
        painter.drawRect(px(20), py_(56), int(40*s), int(9*s))
        painter.drawEllipse(px(26), py_(10), int(28*s), int(46*s))
    elif piece_type == chess.QUEEN:
        painter.drawRect(px(12), py_(64), int(56*s), int(8*s))
        painter.drawRect(px(17), py_(56), int(46*s), int(9*s))
        painter.drawEllipse(px(24), py_(28), int(32*s), int(30*s))
        painter.drawEllipse(px(36), py_(10), int(8*s), int(12*s))
    elif piece_type == chess.KING:
        painter.drawRect(px(12), py_(64), int(56*s), int(8*s))
        painter.drawRect(px(17), py_(56), int(46*s), int(9*s))
        painter.drawEllipse(px(22), py_(30), int(36*s), int(32*s))
        painter.drawRect(px(37), py_(3), int(6*s), int(21*s))
        painter.drawRect(px(28), py_(9), int(24*s), int(7*s))


# -- Mini board thumbnail rendering ------------------------------------------
_mini_piece_cache = {}  # {sq_size: {(piece_type, color): QPixmap}}

def _render_mini_board_pixmap(fen, size=144, flipped=False):
    """Render a chess position as a QPixmap thumbnail."""
    try:
        sq = size // 8
        pm = QPixmap(size, size)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        light = QColor("#f0d9b5")
        dark = QColor("#b58863")

        # Draw squares
        for s_idx in chess.SQUARES:
            col = chess.square_file(s_idx)
            row = chess.square_rank(s_idx)
            dc = (7 - col) if flipped else col
            dr = row if flipped else (7 - row)
            is_light = (col + row) % 2 == 1
            p.fillRect(dc * sq, dr * sq, sq, sq, light if is_light else dark)

        # Load pieces at this size
        try:
            if sq not in _mini_piece_cache:
                _mini_piece_cache[sq] = load_piece_pixmaps(sq)
            pieces = _mini_piece_cache[sq]
        except Exception as e:
            _ot_logger.error("Failed to load piece pixmaps (size=%d): %s", sq, e)
            pieces = {}

        # Draw pieces
        try:
            board = chess.Board(fen)
        except Exception:
            _ot_logger.error("Malformed FEN, using starting position: %s", fen)
            board = chess.Board()
        for s_idx in chess.SQUARES:
            piece = board.piece_at(s_idx)
            if piece is None:
                continue
            col = chess.square_file(s_idx)
            row = chess.square_rank(s_idx)
            dc = (7 - col) if flipped else col
            dr = row if flipped else (7 - row)
            key = (piece.piece_type, piece.color)
            try:
                if key in pieces:
                    p.drawPixmap(dc * sq, dr * sq, sq, sq, pieces[key])
                else:
                    draw_piece_painter(p, piece.piece_type, piece.color, dc * sq, dr * sq, sq)
            except Exception as e:
                _ot_logger.error("Failed to draw piece %s at square %d: %s", key, s_idx, e)

        p.end()
        return pm
    except Exception as e:
        _ot_logger.error("Failed to render mini board pixmap: %s", e)
        # Return an empty pixmap instead of crashing
        fallback = QPixmap(size, size)
        fallback.fill(QColor("#b58863"))
        return fallback


# -- Config persistence ------------------------------------------------------
_CONFIG_PATH = os.path.join(BASE_DIR, "chessgym_config.json")
_BOOK_DIR_W = os.path.join(RESOURCE_DIR, "BotOpeningBookW")
_BOOK_DIR_B = os.path.join(RESOURCE_DIR, "BotOpeningBookB")

_DEFAULT_CONFIG = {
    "white_book": None,
    "black_book": None,
    "theme": "soft_light",
    "games_panel_hidden": True,
    "version": "3.3",
}

def _load_config():
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        cfg = dict(_DEFAULT_CONFIG)
        _save_config(cfg)
        return cfg

def _save_config(cfg):
    try:
        with open(_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"[Config] save error: {e}")


# -- Winning Positions -------------------------------------------------------
_WPOS_RANGES = [
    {"label": "+2 to +3",
     "w_dir": os.path.join(RESOURCE_DIR, "WPlusTwoAdv"),
     "b_dir": os.path.join(RESOURCE_DIR, "BPlusTwoAdv")},
    {"label": "+1 to +2",
     "w_dir": os.path.join(RESOURCE_DIR, "WPlusOneAdv"),
     "b_dir": os.path.join(RESOURCE_DIR, "BPlusOneAdv")},
    {"label": "+0.7 to +1",
     "w_dir": os.path.join(RESOURCE_DIR, "WPlusSmallAdv"),
     "b_dir": os.path.join(RESOURCE_DIR, "BPlusSmallAdv")},
]

def _load_winpos_fens(color, range_idx=0):
    r = _WPOS_RANGES[range_idx]
    d = r["w_dir"] if color == "white" else r["b_dir"]
    path = os.path.join(d, "positions.pgn")
    print(f"[WinPos] Loading positions from: {path}")
    if not os.path.isfile(path):
        print(f"[WinPos] File not found: {path}")
        return []
    fens = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            while True:
                try:
                    game = chess.pgn.read_game(f)
                except Exception as e:
                    _ot_logger.error("Error parsing position in %s: %s", path, e)
                    break
                if game is None:
                    break
                fen = game.headers.get("FEN")
                if fen:
                    fens.append(fen)
    except Exception as e:
        _ot_logger.error("Failed to open positions file %s: %s", path, e)
        print(f"[WinPos] ERROR reading {path}: {e}")
    print(f"[WinPos] Loaded {len(fens)} positions")
    return fens


# ============================================================================
#  STYLE HELPERS — Aurora theme
# ============================================================================

def _frost_font(size, weight=None):
    w = weight if weight is not None else _FONT_WEIGHT
    return QFont(_UI_FONT, size, w)

def _mono_font(size):
    return QFont(_MONO_FONT, size, _FONT_WEIGHT)

class _PressScaleFilter(QWidget):
    """No-op stub — button animations removed."""
    def __init__(self, target, press_scale=0.96, bounce=1.02):
        super().__init__(target)


def _add_press_anim(widget):
    """No-op stub — button animations removed."""
    return widget


def _make_button(text, font_size=13, min_height=36, min_width=0, accent=False):
    btn = QPushButton(text)
    btn.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
    if accent:
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['accent_bg']}; color: {T['accent_text']};
                border: 1px solid {T['accent_border']}; border-radius: 12px;
                padding: 8px 20px; min-height: {min_height}px;
            }}
            QPushButton:hover {{
                background-color: {T['accent_border']};
                border-color: {T['accent_text']}; color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: {T['accent_border']}; }}
        """)
    else:
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['btn_bg']}; color: {T['btn_text']};
                border: 1px solid {T['btn_border']}; border-radius: 12px;
                padding: 8px 20px; min-height: {min_height}px;
            }}
            QPushButton:hover {{
                background-color: {T['accent_bg']}; border-color: {T['accent_border']};
                color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: rgba(255,255,255,0.1); }}
        """)
    if min_width:
        btn.setMinimumWidth(min_width)
    btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
    return btn

class MenuButton(QPushButton):
    """Launcher menu button with press animation."""
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFont(QFont(_UI_FONT, 15, QFont.Weight.Normal))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(64)
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['menu_bg']}; color: {T['menu_text']};
                border: 1px solid {T['menu_border']}; border-radius: 14px;
                padding: 10px 20px 10px 24px; min-height: 64px; font-size: 15px;
                font-weight: 400; text-align: left;
            }}
            QPushButton:hover {{
                background-color: {T['menu_hover_bg']};
                border-color: {T['menu_hover_border']};
                color: {T['title']};
            }}
        """)
        self._press_filter = _PressScaleFilter(self)

def _make_label(text, font_size=13, fg=None, font_family=None):
    if fg is None:
        fg = T['title']
    lbl = QLabel(text)
    fam = font_family or _UI_FONT
    lbl.setFont(QFont(fam, font_size, QFont.Weight.Light))
    lbl.setStyleSheet(f"color: {fg}; background: transparent;")
    return lbl

def _separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {T['section_border']};")
    return line

def _hex_to_rgb(hex_color):
    """Convert '#RRGGBB' to 'R, G, B' string for use in rgba()."""
    h = hex_color.lstrip('#')
    return f"{int(h[0:2], 16)}, {int(h[2:4], 16)}, {int(h[4:6], 16)}"

def _qt_deleted(obj):
    """Return True if a Qt/C++ wrapped object has been deleted."""
    try:
        obj.objectName()
        return False
    except RuntimeError:
        return True

def _section_label(text):
    """Uppercase section heading with letter-spacing."""
    lbl = QLabel(text)
    lbl.setFont(QFont(_UI_FONT, 10, QFont.Weight.Normal))
    lbl.setStyleSheet(
        f"color: {T['section_label']}; background: transparent; "
        "letter-spacing: 2px;"
    )
    return lbl


def _empty_state_widget(svg_str, title_text, subtitle_text):
    """Create a centered empty-state overlay with SVG icon + text."""
    container = QWidget()
    container.setStyleSheet("background: transparent;")
    lay = QVBoxLayout(container)
    lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.setSpacing(8)

    # SVG icon
    icon_w = QWidget()
    icon_w.setFixedSize(80, 80)
    renderer = QSvgRenderer()
    renderer.load(QByteArray(svg_str.encode()))
    icon_w._renderer = renderer

    def _paint_icon(event, r=renderer, w=icon_w):
        p = QPainter(w)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r.render(p, QRectF(0, 0, 80, 80))
        p.end()
    icon_w.paintEvent = _paint_icon
    lay.addWidget(icon_w, alignment=Qt.AlignmentFlag.AlignCenter)

    lay.addSpacing(4)
    t_lbl = QLabel(title_text)
    t_lbl.setFont(QFont(_UI_FONT, 18, QFont.Weight.Light))
    t_lbl.setStyleSheet(f"color: {T['text_primary']}; background: transparent; opacity: 0.5;")
    t_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(t_lbl)

    s_lbl = QLabel(subtitle_text)
    s_lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
    s_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent; opacity: 0.35;")
    s_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
    s_lbl.setWordWrap(True)
    lay.addWidget(s_lbl)

    return container


def _empty_king_svg():
    c = T.get('text_muted', '#888888')
    return (f'<svg width="80" height="80" viewBox="0 0 80 80" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="M40 10V18M40 10L36 14M40 10L44 14" stroke="{c}" '
            f'stroke-width="2" stroke-linecap="round" opacity="0.15"/>'
            f'<path d="M25 70H55L58 55H22L25 70Z" stroke="{c}" '
            f'stroke-width="2" fill="none" opacity="0.15"/>'
            f'<path d="M22 55C22 40 28 25 40 18C52 25 58 40 58 55" stroke="{c}" '
            f'stroke-width="2" fill="none" opacity="0.15"/>'
            f'<line x1="20" y1="70" x2="60" y2="70" stroke="{c}" '
            f'stroke-width="2" opacity="0.15"/>'
            f'</svg>')


def _empty_book_svg():
    c = T.get('text_muted', '#888888')
    return (f'<svg width="80" height="80" viewBox="0 0 80 80" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="M15 15H35C37.5 15 40 17 40 20V65C40 62 37.5 60 35 60H15V15Z" '
            f'stroke="{c}" stroke-width="2" fill="none" opacity="0.15"/>'
            f'<path d="M65 15H45C42.5 15 40 17 40 20V65C40 62 42.5 60 45 60H65V15Z" '
            f'stroke="{c}" stroke-width="2" fill="none" opacity="0.15"/>'
            f'<line x1="22" y1="28" x2="33" y2="28" stroke="{c}" '
            f'stroke-width="1.5" opacity="0.12"/>'
            f'<line x1="22" y1="35" x2="33" y2="35" stroke="{c}" '
            f'stroke-width="1.5" opacity="0.12"/>'
            f'<line x1="22" y1="42" x2="30" y2="42" stroke="{c}" '
            f'stroke-width="1.5" opacity="0.12"/>'
            f'</svg>')


def _empty_board_svg():
    c = T.get('text_muted', '#888888')
    return (f'<svg width="80" height="80" viewBox="0 0 80 80" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<rect x="12" y="12" width="56" height="56" rx="3" stroke="{c}" '
            f'stroke-width="2" fill="none" opacity="0.15"/>'
            f'<rect x="12" y="12" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="40" y="12" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="26" y="26" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="54" y="26" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="12" y="40" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="40" y="40" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="26" y="54" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'<rect x="54" y="54" width="14" height="14" fill="{c}" opacity="0.08"/>'
            f'</svg>')


# ============================================================================
#  PILL SPINNER — compact horizontal  [ ‹ | number | › ]  control
# ============================================================================

def _pill_btn_ss():
    return f"""
    QPushButton {{
        background-color: transparent; color: {T['pill_arrow']};
        border: none; font-size: 15px;
        min-width: 36px; max-width: 36px; min-height: 40px; max-height: 40px;
    }}
    QPushButton:hover {{
        background-color: {T['accent_bg']}; color: {T['accent_text']};
    }}
    QPushButton:pressed {{
        background-color: {T['accent_bg']};
    }}
"""

# Keep backward-compat reference
_PILL_BTN_SS = _pill_btn_ss()


class PillSpinner(QWidget):
    """Compact horizontal  [ ‹ | number | › ]  pill control."""

    def __init__(self, mn=0, mx=60, default=3, parent=None):
        super().__init__(parent)
        self._min = mn; self._max = mx; self._val = default

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Pill frame
        self._pill = QFrame()
        self._pill.setFixedHeight(40)
        self._pill.setStyleSheet(
            f"background-color: {T['pill_bg']}; "
            f"border: 1px solid {T['pill_border']}; border-radius: 10px;"
        )
        pl = QHBoxLayout(self._pill)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(0)

        self._left = QPushButton("\u2039")
        self._left.setFont(QFont(_UI_FONT, 15, QFont.Weight.Light))
        self._left.setStyleSheet(_pill_btn_ss())
        self._left.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._left.clicked.connect(self._dec)
        _add_press_anim(self._left)
        pl.addWidget(self._left)

        self._lbl = QLabel(str(default))
        self._lbl.setFont(QFont(_UI_FONT, 17, QFont.Weight.Normal))
        self._lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl.setFixedWidth(38)
        self._lbl.setFixedHeight(40)
        self._lbl.setStyleSheet(
            f"color: {T['pill_num']}; background: transparent; "
            f"border-left: 1px solid {T['pill_divider']}; "
            f"border-right: 1px solid {T['pill_divider']}; "
            "border-top: none; border-bottom: none;"
        )
        pl.addWidget(self._lbl)

        self._right = QPushButton("\u203A")
        self._right.setFont(QFont(_UI_FONT, 15, QFont.Weight.Light))
        self._right.setStyleSheet(_pill_btn_ss())
        self._right.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._right.clicked.connect(self._inc)
        _add_press_anim(self._right)
        pl.addWidget(self._right)

        lay.addWidget(self._pill)

    def _inc(self):
        play_menu_click()
        if self._val < self._max:
            self._val += 1; self._lbl.setText(str(self._val))

    def _dec(self):
        play_menu_click()
        if self._val > self._min:
            self._val -= 1; self._lbl.setText(str(self._val))

    def value(self):
        return self._val

    def setValue(self, v):
        self._val = max(self._min, min(self._max, v))
        self._lbl.setText(str(self._val))


class FrostBackground(QWidget):
    """Base widget with solid themed background."""
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(0, 0, self.width(), self.height(), QColor(T['bg']))
        p.end()


# ============================================================================
#  BOARD WIDGET
# ============================================================================

class BoardWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.board = chess.Board()
        self.flipped = False
        self.piece_imgs = {}
        self.selected = None
        self.legal_tgt = []
        self.last_move = None
        self.drag_sq = None
        self.drag_pos = None
        self.game_over = False
        self._sq = SQ
        self._ox = BOARD_OX
        self._oy = BOARD_OY
        self.setMinimumSize(320 + 40, 320 + 40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_board(self, board):
        self.board = board
        self.update()

    _FRAME_W = 18  # wooden frame border width

    def recalc_layout(self):
        w = self.width(); h = self.height()
        FW = self._FRAME_W
        margin = FW + 6  # frame + shadow clearance
        new_sq = max(32, min(w - 2 * margin, h - 2 * margin) // 8)
        self._ox = max(margin, (w - new_sq * 8) // 2)
        self._oy = max(margin, (h - new_sq * 8) // 2)
        if new_sq != self._sq:
            self._sq = new_sq
            self.piece_imgs = load_piece_pixmaps(new_sq)
        self.update()

    def resizeEvent(self, event: QResizeEvent):
        super().resizeEvent(event)
        self.recalc_layout()

    def _sq_to_pixel(self, sq):
        """Convert chess square to top-left pixel coords."""
        col = chess.square_file(sq); row = chess.square_rank(sq)
        dc = (7 - col) if self.flipped else col
        dr = row if self.flipped else (7 - row)
        return self._ox + dc * self._sq, self._oy + dr * self._sq

    def sq_from_pixel(self, x, y):
        dc = (x - self._ox) // self._sq
        dr = (y - self._oy) // self._sq
        if not (0 <= dc < 8 and 0 <= dr < 8):
            return None
        col = dc if not self.flipped else 7 - dc
        row = (7 - dr) if not self.flipped else dr
        return chess.square(col, row)

    def paintEvent(self, event: QPaintEvent):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        S = self._sq; OX = self._ox; OY = self._oy; BPX = S * 8
        w = self.width(); h = self.height()

        # Background fill
        p.fillRect(0, 0, w, h, QColor(T['bg']))

        FW = self._FRAME_W
        fx = OX - FW; fy = OY - FW
        fw = BPX + 2 * FW; fh = BPX + 2 * FW

        # Drop shadow (0 6px 24px rgba(0,0,0,0.3))
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(8):
            frac = (i + 1) / 8.0
            alpha = max(1, int(15 * (1.0 - frac)))
            spread = int(20 * frac)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(
                fx - spread, fy - spread + 6,
                fw + 2 * spread, fh + 2 * spread,
                4 + spread, 4 + spread)

        # Warm wooden frame
        p.setBrush(QColor("#8B6340"))
        p.drawRoundedRect(fx, fy, fw, fh, 4, 4)

        # Squares — plain, no highlights
        for sq in chess.SQUARES:
            col = chess.square_file(sq); row = chess.square_rank(sq)
            dc, dr = (7 - col, row) if self.flipped else (col, 7 - row)
            x1 = OX + dc * S; y1 = OY + dr * S
            light = (col + row) % 2 == 1
            base = LIGHT_SQ if light else DARK_SQ
            p.fillRect(x1, y1, S, S, QColor(base))

        # Pieces
        for sq in chess.SQUARES:
            if sq == self.drag_sq:
                continue
            piece = self.board.piece_at(sq)
            if piece is None:
                continue
            col = chess.square_file(sq); row = chess.square_rank(sq)
            dc, dr = (7 - col, row) if self.flipped else (col, 7 - row)
            x1 = OX + dc * S; y1 = OY + dr * S
            key = (piece.piece_type, piece.color)
            if key in self.piece_imgs:
                p.drawPixmap(x1, y1, S, S, self.piece_imgs[key])
            else:
                draw_piece_painter(p, piece.piece_type, piece.color, x1, y1, S)

        # Dragged piece
        if self.drag_sq is not None and self.drag_pos is not None:
            piece = self.board.piece_at(self.drag_sq)
            if piece:
                dx, dy = self.drag_pos
                key = (piece.piece_type, piece.color)
                if key in self.piece_imgs:
                    p.drawPixmap(int(dx - S // 2), int(dy - S // 2), S, S, self.piece_imgs[key])
                else:
                    draw_piece_painter(p, piece.piece_type, piece.color,
                                       int(dx - S // 2), int(dy - S // 2), S)

        p.end()


# ============================================================================
#  TOGGLE BUTTON
# ============================================================================

class ToggleButton(QPushButton):
    def __init__(self, text, active=False, parent=None):
        super().__init__(text, parent)
        self._active = active
        self.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumWidth(140)
        self.setMinimumHeight(52)
        self._update_style()

    def set_active(self, active):
        self._active = active
        self._update_style()

    def _update_style(self):
        if self._active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {T['toggle_active_bg']}; color: {T['toggle_active_text']};
                    border: 1px solid {T['toggle_active_border']}; border-radius: 13px;
                    padding: 8px 16px; min-height: 52px; font-size: 13px;
                    font-weight: 500; letter-spacing: 1.5px;
                }}
                QPushButton:hover {{ background-color: {T['toggle_active_border']}; }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent; color: {T['toggle_inactive_text']};
                    border: 1px solid {T['btn_border']}; border-radius: 13px;
                    padding: 8px 16px; min-height: 52px; font-size: 13px;
                    font-weight: 400; letter-spacing: 1.5px;
                }}
                QPushButton:hover {{
                    background-color: {T['accent_bg']}; color: {T['toggle_active_text']};
                    border-color: {T['toggle_active_border']};
                }}
            """)


# ============================================================================
#  MUTE BUTTON WIDGET
# ============================================================================



def _mute_svg(hex_color, opacity):
    """SVG speaker-on icon."""
    return (f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="M3 9H7L12 4V20L7 15H3V9Z" fill="{hex_color}" opacity="{opacity}"/>'
            f'<path d="M16 9C17.5 10.5 17.5 13.5 16 15" '
            f'stroke="{hex_color}" stroke-width="1.8" stroke-linecap="round" opacity="{opacity}"/>'
            f'<path d="M19 7C21.5 9.5 21.5 14.5 19 17" '
            f'stroke="{hex_color}" stroke-width="1.8" stroke-linecap="round" opacity="{opacity}"/>'
            f'</svg>')

def _muted_svg(hex_color, opacity):
    """SVG speaker-off icon with X."""
    return (f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="M3 9H7L12 4V20L7 15H3V9Z" fill="{hex_color}" opacity="{opacity}"/>'
            f'<line x1="15" y1="9" x2="21" y2="15" '
            f'stroke="{hex_color}" stroke-width="1.8" stroke-linecap="round" opacity="{opacity}"/>'
            f'<line x1="21" y1="9" x2="15" y2="15" '
            f'stroke="{hex_color}" stroke-width="1.8" stroke-linecap="round" opacity="{opacity}"/>'
            f'</svg>')


class _MuteButton(QWidget):
    """50x50 ghost-circle mute toggle with SVG speaker icon."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 50)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Mute / Unmute sounds  [M]")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hovered = False
        self._pressed = False
        self._renderer = QSvgRenderer()
        self.refresh()

    def refresh(self):
        light = _current_theme_name in _LIGHT_THEMES
        muted = _sound_muted
        base = "#000000" if light else "#ffffff"

        if muted:
            op = 0.3
        elif self._hovered:
            op = 0.95 if not light else 0.75
        else:
            op = 0.75 if not light else 0.55

        svg_str = _muted_svg(base, op) if muted else _mute_svg(base, op)
        self._renderer.load(QByteArray(svg_str.encode()))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        light = _current_theme_name in _LIGHT_THEMES
        muted = _sound_muted

        if light:
            if self._hovered:
                bg_c = QColor(0, 0, 0, 26)
                bd_c = QColor(0, 0, 0, 46)
            else:
                bg_c = QColor(0, 0, 0, 15)
                bd_c = QColor(0, 0, 0, 31)
        else:
            if self._hovered:
                bg_c = QColor(255, 255, 255, 36)
                bd_c = QColor(255, 255, 255, 51)
            else:
                bg_c = QColor(255, 255, 255, 20)
                bd_c = QColor(255, 255, 255, 31)

        cx, cy = self.width() / 2, self.height() / 2
        r = 24

        p.setPen(QPen(bd_c, 1))
        p.setBrush(QBrush(bg_c))
        p.drawEllipse(QPointF(cx, cy), r, r)

        icon_sz = 22
        ix = cx - icon_sz / 2
        iy = cy - icon_sz / 2
        self._renderer.render(p, QRectF(ix, iy, icon_sz, icon_sz))
        p.end()

    def enterEvent(self, event):
        self._hovered = True
        self.refresh()

    def leaveEvent(self, event):
        self._hovered = False
        self.refresh()

    def mousePressEvent(self, event):
        self.clicked.emit()
        event.accept()


def _gear_svg(hex_color, opacity):
    """SVG gear icon."""
    return (f'<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg">'
            f'<path d="M12 15a3 3 0 100-6 3 3 0 000 6z" stroke="{hex_color}" '
            f'stroke-width="1.6" fill="none" opacity="{opacity}"/>'
            f'<path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06'
            f'a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09'
            f'a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83'
            f'l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09'
            f'a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83'
            f'l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09'
            f'a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83'
            f'l-.06.06a1.65 1.65 0 00-.33 1.82V9c.26.604.852.997 1.51 1H21a2 2 0 110 4h-.09'
            f'a1.65 1.65 0 00-1.51 1z" stroke="{hex_color}" stroke-width="1.6" fill="none" opacity="{opacity}"/>'
            f'</svg>')


class _GearButton(QWidget):
    """50x50 ghost-circle settings gear button with SVG icon."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 50)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Settings  [S]")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._hovered = False
        self._pressed = False
        self._renderer = QSvgRenderer()
        self.refresh()

    def refresh(self):
        light = _current_theme_name in _LIGHT_THEMES
        base = "#000000" if light else "#ffffff"
        op = (0.75 if self._hovered else 0.55) if light else (0.95 if self._hovered else 0.75)
        self._renderer.load(QByteArray(_gear_svg(base, op).encode()))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        light = _current_theme_name in _LIGHT_THEMES

        if light:
            bg_c = QColor(0, 0, 0, 26) if self._hovered else QColor(0, 0, 0, 15)
            bd_c = QColor(0, 0, 0, 31)
        else:
            bg_c = QColor(255, 255, 255, 36) if self._hovered else QColor(255, 255, 255, 20)
            bd_c = QColor(255, 255, 255, 31)

        scale = 0.92 if self._pressed else 1.0
        cx, cy = self.width() / 2, self.height() / 2
        r = 24 * scale

        p.setPen(QPen(bd_c, 1))
        p.setBrush(QBrush(bg_c))
        p.drawEllipse(QPointF(cx, cy), r, r)

        icon_sz = 22 * scale
        ix = cx - icon_sz / 2
        iy = cy - icon_sz / 2
        self._renderer.render(p, QRectF(ix, iy, icon_sz, icon_sz))
        p.end()

    def enterEvent(self, event):
        self._hovered = True
        self.refresh()

    def leaveEvent(self, event):
        self._hovered = False
        self.refresh()

    def mousePressEvent(self, event):
        self._pressed = True
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event):
        was_pressed = self._pressed
        self._pressed = False
        self.update()
        if was_pressed:
            try:
                pt = event.position().toPoint()
            except AttributeError:
                pt = event.pos()
            if self.rect().contains(pt):
                self.clicked.emit()
        event.accept()


# ============================================================================
#  LAUNCHER PAGE
# ============================================================================

class LauncherPage(FrostBackground):
    finished = pyqtSignal(str)
    theme_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(40, 0, 40, 0)
        outer.addStretch(2)

        # Title
        title = _make_label("ChessGym", 34, T['title'])
        title.setFont(QFont(_UI_FONT, 34, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)
        outer.addSpacing(24)

        # Menu buttons — centered column, wide
        btn_col = QVBoxLayout()
        btn_col.setSpacing(10)
        btn_col.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for text, signal in [("Play Against Bot", "play"),
                             ("Winning Positions", "winpos"),
                             ("Opening Trainer", "trainer"),
                             ("PGN Viewer", "pgn")]:
            btn = MenuButton(f"{text}  \u2192")
            btn.setMinimumWidth(480)
            btn.setMaximumWidth(540)
            btn.clicked.connect(lambda checked, s=signal: (play_menu_click(), self.finished.emit(s)))
            btn_col.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # Check for Updates button
        self._update_btn = MenuButton("Check for Updates")
        self._update_btn.setMinimumWidth(480)
        self._update_btn.setMaximumWidth(540)
        self._update_btn.clicked.connect(lambda checked: self._do_update_check())
        btn_col.addWidget(self._update_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        outer.addLayout(btn_col)
        outer.addStretch(3)

        # -- Theme dot switcher at bottom --
        outer.addSpacing(8)
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background-color: {T['section_border']};")
        outer.addWidget(sep)

        outer.addSpacing(16)
        theme_lbl = QLabel("THEME")
        theme_lbl.setFont(QFont(_UI_FONT, 9, QFont.Weight.Normal))
        theme_lbl.setStyleSheet(
            f"color: {T['text_muted']}; background: transparent; "
            "letter-spacing: 3px;"
        )
        theme_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(theme_lbl)

        dot_row = QHBoxLayout()
        dot_row.setSpacing(14)
        dot_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._dot_btns = []
        self._dot_anims = {}
        self._switching_theme = False
        for name in THEME_ORDER:
            dot = QPushButton()
            dot.setFixedSize(32, 32)
            dot.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            dot.clicked.connect(lambda checked, n=name: self._dot_clicked(n))
            dot._press_filter = _PressScaleFilter(dot, press_scale=0.88, bounce=1.08)
            self._dot_btns.append((name, dot))
            dot_row.addWidget(dot)
        self._update_dots()
        outer.addLayout(dot_row)
        outer.addSpacing(16)

        # -- Mute button (bottom-left) --
        self._mute_btn = _MuteButton(self)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._mute_btn.show()

        # -- Version label (bottom-right, subtle) --
        self._ver_lbl = QLabel("v3.3", self)
        self._ver_lbl.setFont(QFont(_UI_FONT, 11))
        self._ver_lbl.setStyleSheet("color: rgba(255,183,197,0.6); background: transparent;")
        self._ver_lbl.adjustSize()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_mute_btn'):
            self._mute_btn.move(20, self.height() - 70)
        if hasattr(self, '_ver_lbl'):
            self._ver_lbl.move(self.width() - self._ver_lbl.width() - 16, self.height() - 36)


    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_M:
            self._toggle_mute()
        else:
            super().keyPressEvent(event)

    def _toggle_mute(self):
        global _sound_muted
        _sound_muted = not _sound_muted
        self._mute_btn.refresh()
        try:
            cfg = _load_config()
            cfg["sound_muted"] = _sound_muted
            _save_config(cfg)
        except Exception:
            pass

    def _do_update_check(self):
        from PyQt6.QtWidgets import QMessageBox
        play_menu_click()
        # Create the .bat file
        bat_path = os.path.join(BASE_DIR, "do_update.bat")
        with open(bat_path, "w", encoding="ascii") as f:
            f.write(
                '@echo off\r\n'
                "powershell.exe -NonInteractive -Command "
                "\"Invoke-WebRequest -Uri 'https://chessgym-server.onrender.com/download' "
                "-OutFile '%~dp0main.py'\"\r\n"
                'del "%~0"\r\n'
            )
        os.startfile(bat_path)
        QMessageBox.information(
            self, "Updating",
            "Update is downloading. ChessGym will now close.\n\n"
            "Please reopen in 30 seconds.")
        sys.exit(0)

    def _update_dots(self):
        # Inner glow colors per theme
        _dot_glows = {
            "soft_light": "rgba(147,197,253,0.4)",
            "slate_linen": "rgba(74,112,144,0.45)",
            "sage_stone": "rgba(90,128,80,0.45)",
            "light_oak": "rgba(139,94,40,0.45)",
            "wisteria_mist": "rgba(136,104,192,0.45)",
        }
        for name, dot in self._dot_btns:
            th = THEMES[name]
            active = (name == _current_theme_name)
            glow = _dot_glows.get(name, "transparent")
            if active:
                dot.setStyleSheet(f"""
                    QPushButton {{
                        background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.6,
                            fx:0.5, fy:0.5, stop:0 {glow}, stop:1 {th['dot']});
                        border: 2px solid {th['dot_accent']};
                        border-radius: 16px;
                        min-width: 32px; max-width: 32px;
                        min-height: 32px; max-height: 32px;
                        padding: 3px;
                    }}
                """)
            else:
                dot.setStyleSheet(f"""
                    QPushButton {{
                        background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.6,
                            fx:0.5, fy:0.5, stop:0 {glow}, stop:1 {th['dot']});
                        border: 1px solid rgba(255,255,255,0.06);
                        border-radius: 16px;
                        min-width: 32px; max-width: 32px;
                        min-height: 32px; max-height: 32px;
                        opacity: 0.7;
                    }}
                    QPushButton:hover {{
                        border: 2px solid rgba(255,255,255,0.3);
                        opacity: 1.0;
                    }}
                """)

    def _dot_clicked(self, name):
        if self._switching_theme:
            return
        self._switching_theme = True
        try:
            play_menu_click()
            self._switch_theme(name)
        finally:
            self._switching_theme = False

    def _switch_theme(self, name):
        set_theme(name)
        # Save to config
        try:
            cfg = _load_config()
            cfg["theme"] = name
            _save_config(cfg)
        except Exception:
            pass
        # Update dots and mute button in-place (do NOT rebuild the page)
        self._update_dots()
        self._mute_btn.refresh()
        self.theme_changed.emit(name)


# ============================================================================
#  GAME MODE PAGE
# ============================================================================

class GameModePage(FrostBackground):
    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 420)
        self._mode = "standard"

        outer = QVBoxLayout(self)
        outer.addStretch(2)
        hc = QHBoxLayout(); hc.addStretch()

        # Fixed-width content container
        content = QWidget()
        content.setFixedWidth(460)
        content.setStyleSheet("background: transparent;")
        inner = QVBoxLayout(content)
        inner.setSpacing(0)
        inner.setContentsMargins(0, 0, 0, 0)

        title = _make_label("ChessGym", 34, T['title'])
        title.setFont(QFont(_UI_FONT, 34, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)
        inner.addSpacing(28)

        # GAME MODE - section card
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 14px;
            }}
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(22, 20, 22, 20)
        cl.setSpacing(12)
        gm_lbl = QLabel("GAME MODE")
        gm_lbl.setFont(QFont(_UI_FONT, 10, QFont.Weight.Normal))
        gm_lbl.setStyleSheet(
            f"color: {T['section_label']}; background: transparent; "
            "letter-spacing: 2.5px;")
        cl.addWidget(gm_lbl)
        mr = QHBoxLayout(); mr.setSpacing(0)
        self._btn_std = ToggleButton("Standard", active=True)
        self._btn_std.setFont(QFont(_UI_FONT, 15, QFont.Weight.Normal))
        self._btn_std.setMinimumHeight(64)
        self._btn_std.setStyleSheet(self._btn_std.styleSheet().replace(
            "letter-spacing: 1.5px", "letter-spacing: 1px").replace(
            "border-radius: 13px", "border-radius: 11px"))
        self._btn_std.clicked.connect(lambda: (play_menu_click(), self._pick("standard")))
        _add_press_anim(self._btn_std)
        mr.addWidget(self._btn_std)
        self._btn_960 = ToggleButton("Chess960", active=False)
        self._btn_960.setFont(QFont(_UI_FONT, 15, QFont.Weight.Normal))
        self._btn_960.setMinimumHeight(64)
        self._btn_960.setStyleSheet(self._btn_960.styleSheet().replace(
            "letter-spacing: 1.5px", "letter-spacing: 1px").replace(
            "border-radius: 13px", "border-radius: 11px"))
        self._btn_960.clicked.connect(lambda: (play_menu_click(), self._pick("chess960")))
        _add_press_anim(self._btn_960)
        mr.addWidget(self._btn_960)
        self._btn_fen = ToggleButton("FEN Position", active=False)
        self._btn_fen.setFont(QFont(_UI_FONT, 15, QFont.Weight.Normal))
        self._btn_fen.setMinimumHeight(64)
        self._btn_fen.setStyleSheet(self._btn_fen.styleSheet().replace(
            "letter-spacing: 1.5px", "letter-spacing: 1px").replace(
            "border-radius: 13px", "border-radius: 11px"))
        self._btn_fen.clicked.connect(lambda: (play_menu_click(), self._pick("fen")))
        _add_press_anim(self._btn_fen)
        mr.addWidget(self._btn_fen)
        cl.addLayout(mr)
        inner.addWidget(card)

        inner.addSpacing(12)
        btn_cont = _make_button("Continue  \u2192", 15, min_height=64, accent=True)
        btn_cont.setStyleSheet(btn_cont.styleSheet().replace("border-radius: 12px", "border-radius: 14px"))
        btn_cont.clicked.connect(lambda: (play_menu_click(), self._continue()))
        _add_press_anim(btn_cont)
        inner.addWidget(btn_cont)

        inner.addSpacing(10)
        btn_back = QPushButton("Back to Menu")
        btn_back.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['section_label']};
                border: none; padding: 8px 20px; min-height: 36px;
            }}
            QPushButton:hover {{ color: {T['text_primary']}; }}
        """)
        btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        _add_press_anim(btn_back)
        inner.addWidget(btn_back, alignment=Qt.AlignmentFlag.AlignCenter)

        hc.addWidget(content); hc.addStretch()
        outer.addLayout(hc); outer.addStretch(3)

    def _pick(self, mode):
        self._mode = mode
        self._btn_std.set_active(mode == "standard")
        self._btn_960.set_active(mode == "chess960")
        self._btn_fen.set_active(mode == "fen")

    def _continue(self):
        self.finished.emit(self._mode)


# ============================================================================
#  SETUP PAGE
# ============================================================================

class SetupPage(FrostBackground):
    finished = pyqtSignal(object)

    def __init__(self, chess960=False, parent=None):
        super().__init__(parent)
        self._chess960 = chess960
        self._cfg = _load_config()
        self.white_book_path = self._cfg.get("white_book") if not chess960 else None
        self.black_book_path = self._cfg.get("black_book") if not chess960 else None
        if self.white_book_path and not os.path.isfile(self.white_book_path):
            self.white_book_path = None
        if self.black_book_path and not os.path.isfile(self.black_book_path):
            self.black_book_path = None
        self._color = "white"
        self._build_ui()

    def _make_section_card(self):
        """Create a section card frame with subtle background."""
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 13px;
            }}
        """)
        return card

    def _make_book_btn(self, text):
        """Create a fluffy Browse/Clear button for opening books."""
        btn = QPushButton(text)
        btn.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['book_btn_bg']}; color: {T['book_btn_text']};
                border: 1px solid {T['book_btn_border']}; border-radius: 10px;
                padding: 0 14px; min-height: 40px; max-height: 40px; font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {T['accent_bg']}; border-color: {T['accent_border']};
                color: {T['title']};
            }}
        """)
        _add_press_anim(btn)
        return btn

    def _make_book_display(self, text="(none)"):
        """Create a filename display label styled as a soft box."""
        lbl = QLabel(text)
        lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        lbl.setFixedHeight(40)
        lbl.setMinimumWidth(140)
        lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {T['book_bg']}; color: {T['book_text']};
                border: 1px solid {T['book_border']}; border-radius: 10px;
                padding: 0 12px; font-size: 13px;
            }}
        """)
        return lbl

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        hc = QHBoxLayout(); hc.addStretch()

        inner = QVBoxLayout()
        inner.setSpacing(10)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = _make_label("ChessGym", 28, T['title'])
        title.setFont(QFont(_UI_FONT, 28, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)
        inner.addSpacing(8)

        # 1. PLAY AS — section card
        card1 = self._make_section_card()
        cl1 = QVBoxLayout(card1)
        cl1.setContentsMargins(18, 16, 18, 16)
        cl1.setSpacing(12)
        cl1.addWidget(_section_label("PLAY AS"))
        cr = QHBoxLayout(); cr.setSpacing(12)
        self._btn_white = ToggleButton("WHITE", active=True)
        self._btn_white.setMinimumWidth(180)
        self._btn_white.clicked.connect(lambda: (play_menu_click(), self._pick_color("white")))
        _add_press_anim(self._btn_white)
        cr.addWidget(self._btn_white)
        self._btn_black = ToggleButton("BLACK", active=False)
        self._btn_black.setMinimumWidth(180)
        self._btn_black.clicked.connect(lambda: (play_menu_click(), self._pick_color("black")))
        _add_press_anim(self._btn_black)
        cr.addWidget(self._btn_black)
        cl1.addLayout(cr)
        inner.addWidget(card1)

        # 2. YOUR TIME CONTROL — section card with pill spinners
        card2 = self._make_section_card()
        cl2 = QVBoxLayout(card2)
        cl2.setContentsMargins(18, 16, 18, 16)
        cl2.setSpacing(6)
        cl2.addWidget(_section_label("YOUR TIME CONTROL"))
        r_pm = QHBoxLayout(); r_pm.setSpacing(0)
        lbl_pm = QLabel("Minutes")
        lbl_pm.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        lbl_pm.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_pm.setFixedWidth(80); lbl_pm.setFixedHeight(44)
        r_pm.addWidget(lbl_pm); r_pm.addStretch()
        self.p_min = PillSpinner(0, 60, 3)
        r_pm.addWidget(self.p_min)
        cl2.addLayout(r_pm)
        r_pi = QHBoxLayout(); r_pi.setSpacing(0)
        lbl_pi = QLabel("Increment")
        lbl_pi.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        lbl_pi.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_pi.setFixedWidth(80); lbl_pi.setFixedHeight(44)
        r_pi.addWidget(lbl_pi); r_pi.addStretch()
        self.p_inc = PillSpinner(0, 60, 2)
        r_pi.addWidget(self.p_inc)
        cl2.addLayout(r_pi)
        inner.addWidget(card2)

        # 3. ENGINE TIME CONTROL — section card with pill spinners
        card3 = self._make_section_card()
        cl3 = QVBoxLayout(card3)
        cl3.setContentsMargins(18, 16, 18, 16)
        cl3.setSpacing(6)
        cl3.addWidget(_section_label("ENGINE TIME CONTROL"))
        r_em = QHBoxLayout(); r_em.setSpacing(0)
        lbl_em = QLabel("Minutes")
        lbl_em.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        lbl_em.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_em.setFixedWidth(80); lbl_em.setFixedHeight(44)
        r_em.addWidget(lbl_em); r_em.addStretch()
        self.e_min = PillSpinner(0, 60, 1)
        r_em.addWidget(self.e_min)
        cl3.addLayout(r_em)
        r_ei = QHBoxLayout(); r_ei.setSpacing(0)
        lbl_ei = QLabel("Increment")
        lbl_ei.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        lbl_ei.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_ei.setFixedWidth(80); lbl_ei.setFixedHeight(44)
        r_ei.addWidget(lbl_ei); r_ei.addStretch()
        self.e_inc = PillSpinner(0, 60, 2)
        r_ei.addWidget(self.e_inc)
        cl3.addLayout(r_ei)
        inner.addWidget(card3)

        # 4. OPENING BOOKS — section card
        if not self._chess960:
            card4 = self._make_section_card()
            cl4 = QVBoxLayout(card4)
            cl4.setContentsMargins(18, 16, 18, 16)
            cl4.setSpacing(8)
            cl4.addWidget(_section_label("OPENING BOOKS"))

            wlbl = QLabel("White")
            wlbl.setFont(QFont(_UI_FONT, 14, QFont.Weight.Normal))
            wlbl.setStyleSheet(f"color: {T['book_label']}; background: transparent;")
            cl4.addWidget(wlbl)
            wb_row = QHBoxLayout(); wb_row.setSpacing(8)
            self.wb_lbl = self._make_book_display()
            wb_row.addWidget(self.wb_lbl, 1)
            btn_wb = self._make_book_btn("Browse")
            btn_wb.clicked.connect(lambda: (play_menu_click(), self._browse_wb()))
            wb_row.addWidget(btn_wb)
            btn_wc = self._make_book_btn("Clear")
            btn_wc.clicked.connect(lambda: (play_menu_click(), self._clear_wb()))
            wb_row.addWidget(btn_wc)
            cl4.addLayout(wb_row)

            cl4.addSpacing(4)
            blbl = QLabel("Black")
            blbl.setFont(QFont(_UI_FONT, 14, QFont.Weight.Normal))
            blbl.setStyleSheet(f"color: {T['book_label']}; background: transparent;")
            cl4.addWidget(blbl)
            bb_row = QHBoxLayout(); bb_row.setSpacing(8)
            self.bb_lbl = self._make_book_display()
            bb_row.addWidget(self.bb_lbl, 1)
            btn_bb = self._make_book_btn("Browse")
            btn_bb.clicked.connect(lambda: (play_menu_click(), self._browse_bb()))
            bb_row.addWidget(btn_bb)
            btn_bc = self._make_book_btn("Clear")
            btn_bc.clicked.connect(lambda: (play_menu_click(), self._clear_bb()))
            bb_row.addWidget(btn_bc)
            cl4.addLayout(bb_row)
            inner.addWidget(card4)

            if self.white_book_path:
                self.wb_lbl.setText(os.path.basename(self.white_book_path))
            if self.black_book_path:
                self.bb_lbl.setText(os.path.basename(self.black_book_path))

        inner.addSpacing(12)
        btn_start = _make_button("Start Game  \u2192", 14, min_height=52, min_width=320, accent=True)
        btn_start.setStyleSheet(btn_start.styleSheet().replace("border-radius: 12px", "border-radius: 13px"))
        btn_start.clicked.connect(lambda: (play_menu_click(), self._start()))
        _add_press_anim(btn_start)
        inner.addWidget(btn_start, alignment=Qt.AlignmentFlag.AlignCenter)
        btn_back = QPushButton("Back to Menu")
        btn_back.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['section_label']};
                border: none; padding: 8px 20px; min-height: 36px;
            }}
            QPushButton:hover {{ color: {T['text_primary']}; }}
        """)
        btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        _add_press_anim(btn_back)
        inner.addWidget(btn_back, alignment=Qt.AlignmentFlag.AlignCenter)

        hc.addLayout(inner); hc.addStretch()
        outer.addLayout(hc); outer.addStretch(2)

    def _pick_color(self, color):
        self._color = color
        self._btn_white.set_active(color == "white")
        self._btn_black.set_active(color == "black")

    def _save_book_config(self):
        self._cfg["white_book"] = self.white_book_path
        self._cfg["black_book"] = self.black_book_path
        _save_config(self._cfg)

    def _browse_wb(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select White Opening Book", _BOOK_DIR_W,
            "Opening Books (*.pgn *.ctg);;All files (*.*)")
        if path:
            self.white_book_path = path
            self.wb_lbl.setText(os.path.basename(path))
            self._save_book_config()

    def _clear_wb(self):
        self.white_book_path = None
        self.wb_lbl.setText("(none)")
        self._save_book_config()

    def _browse_bb(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Black Opening Book", _BOOK_DIR_B,
            "Opening Books (*.pgn *.ctg);;All files (*.*)")
        if path:
            self.black_book_path = path
            self.bb_lbl.setText(os.path.basename(path))
            self._save_book_config()

    def _clear_bb(self):
        self.black_book_path = None
        self.bb_lbl.setText("(none)")
        self._save_book_config()

    def _start(self):
        self.finished.emit({
            "p_min": self.p_min.value(), "p_inc": self.p_inc.value(),
            "e_min": self.e_min.value(), "e_inc": self.e_inc.value(),
            "player_color": chess.WHITE if self._color == "white" else chess.BLACK,
            "white_book": self.white_book_path,
            "black_book": self.black_book_path,
            "chess960": self._chess960,
        })


# ============================================================================
#  FEN BUILDER PAGE  —  free-move board to construct a position
# ============================================================================

class FenBuilderPage(FrostBackground):
    finished = pyqtSignal(str)  # emits FEN string (or "back" with empty)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(700, 600)
        self._board = chess.Board()
        self._selected = None
        self._drag_sq = None
        self._drag_pos = None

        root = QHBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(20)

        # Left — board
        self._board_w = BoardWidget()
        self._board_w.set_board(self._board)
        self._board_w.setMinimumSize(400, 400)
        self._board_w.mousePressEvent = self._board_press
        self._board_w.mouseMoveEvent = self._board_drag
        self._board_w.mouseReleaseEvent = self._board_release
        root.addWidget(self._board_w, 3)

        # Right — controls
        panel = QVBoxLayout()
        panel.setSpacing(12)

        title = _make_label("Build Your Position", 22, T['title'])
        title.setFont(QFont(_UI_FONT, 22, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel.addWidget(title)
        panel.addSpacing(4)

        hint = QLabel("Click a piece, then click its destination.\nBoth sides can move freely — no turn restriction.")
        hint.setFont(QFont(_UI_FONT, 11, QFont.Weight.Light))
        hint.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel.addWidget(hint)
        panel.addSpacing(8)

        # FEN display
        self._fen_display = QLineEdit()
        self._fen_display.setReadOnly(True)
        self._fen_display.setFont(QFont("Consolas", 11))
        self._fen_display.setStyleSheet(f"""
            QLineEdit {{
                background-color: {T['section_bg']}; color: {T['text_primary']};
                border: 1px solid {T['section_border']}; border-radius: 8px;
                padding: 8px 10px; min-height: 36px;
            }}
        """)
        self._fen_display.setText(self._board.fen())
        panel.addWidget(self._fen_display)

        btn_copy = _make_button("Copy FEN", 12, min_height=40)
        btn_copy.clicked.connect(lambda: (play_menu_click(), self._copy_fen()))
        _add_press_anim(btn_copy)
        panel.addWidget(btn_copy)

        # Reset button
        btn_reset = _make_button("Reset Board", 12, min_height=40)
        btn_reset.clicked.connect(lambda: (play_menu_click(), self._reset_board()))
        _add_press_anim(btn_reset)
        panel.addWidget(btn_reset)

        btn_flip = _make_button("Flip Board", 12, min_height=40)
        btn_flip.clicked.connect(lambda: (play_menu_click(), self._flip_board()))
        _add_press_anim(btn_flip)
        panel.addWidget(btn_flip)

        # Status label for copy feedback
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
        self._status_lbl.setStyleSheet(f"color: {T['toggle_active_text']}; background: transparent;")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        panel.addWidget(self._status_lbl)

        panel.addStretch()

        # Back to Menu button — dark purple
        btn_back = QPushButton("Back to Menu")
        btn_back.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_back.setStyleSheet("""
            QPushButton {
                background-color: #4A3070; color: #ffffff;
                border: 1px solid #5C3D90; border-radius: 12px;
                padding: 8px 20px; min-height: 44px;
            }
            QPushButton:hover {
                background-color: #5C3D90; border-color: #7050B0;
            }
            QPushButton:pressed { background-color: #3A2060; }
        """)
        btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        _add_press_anim(btn_back)
        panel.addWidget(btn_back)

        root.addLayout(panel, 2)

    # -- Board interaction (free move, no turn restriction) --

    def _board_press(self, ev: QMouseEvent):
        sq = self._board_w.sq_from_pixel(int(ev.position().x()), int(ev.position().y()))
        if sq is None:
            return
        piece = self._board.piece_at(sq)
        if self._selected is not None:
            # Try to make a move from selected to sq
            self._try_move(self._selected, sq)
            self._selected = None
            self._board_w.selected = None
            self._board_w.update()
        elif piece is not None:
            self._selected = sq
            self._drag_sq = sq
            self._drag_pos = (int(ev.position().x()), int(ev.position().y()))
            self._board_w.selected = sq
            self._board_w.drag_sq = sq
            self._board_w.drag_pos = self._drag_pos
            self._board_w.update()

    def _board_drag(self, ev: QMouseEvent):
        if self._drag_sq is not None:
            self._drag_pos = (int(ev.position().x()), int(ev.position().y()))
            self._board_w.drag_pos = self._drag_pos
            self._board_w.update()

    def _board_release(self, ev: QMouseEvent):
        if self._drag_sq is not None:
            tgt = self._board_w.sq_from_pixel(int(ev.position().x()), int(ev.position().y()))
            if tgt is not None and tgt != self._drag_sq:
                self._try_move(self._drag_sq, tgt)
                self._selected = None
                self._board_w.selected = None
            self._drag_sq = None
            self._drag_pos = None
            self._board_w.drag_sq = None
            self._board_w.drag_pos = None
            self._board_w.update()

    def _try_move(self, from_sq, to_sq):
        """Attempt to move piece — override turn so both sides can move."""
        piece = self._board.piece_at(from_sq)
        if piece is None:
            return
        # Temporarily set turn to the piece's color so the move is legal
        orig_turn = self._board.turn
        self._board.turn = piece.color
        # Check for promotion
        move = chess.Move(from_sq, to_sq)
        if piece.piece_type == chess.PAWN:
            dest_rank = chess.square_rank(to_sq)
            if (piece.color == chess.WHITE and dest_rank == 7) or \
               (piece.color == chess.BLACK and dest_rank == 0):
                move = chess.Move(from_sq, to_sq, promotion=chess.QUEEN)
        if move in self._board.legal_moves:
            self._board.push(move)
        else:
            self._board.turn = orig_turn
            return
        self._board_w.set_board(self._board)
        self._fen_display.setText(self._board.fen())

    def _copy_fen(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self._board.fen())
        self._status_lbl.setText("FEN copied to clipboard!")
        lbl = self._status_lbl
        QTimer.singleShot(2000, lambda: lbl.setText("") if not _qt_deleted(lbl) else None)

    def _reset_board(self):
        self._board = chess.Board()
        self._selected = None
        self._board_w.selected = None
        self._board_w.set_board(self._board)
        self._fen_display.setText(self._board.fen())

    def _flip_board(self):
        self._board_w.flipped = not self._board_w.flipped
        self._board_w.update()


# ============================================================================
#  FEN SETUP PAGE  —  paste FEN, choose side/time, start game
# ============================================================================

class FenSetupPage(FrostBackground):
    finished = pyqtSignal(object)  # dict config or "back" or "builder"

    def __init__(self, initial_fen="", parent=None):
        super().__init__(parent)
        self._color = "white"
        self._side_to_move = "w"
        self._build_ui(initial_fen)

    def _build_ui(self, initial_fen):
        _card_ss = f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 10px;
            }}
        """
        _card_m = (14, 10, 14, 10)  # compact card margins

        outer = QVBoxLayout(self)
        outer.addStretch(1)
        hc = QHBoxLayout(); hc.addStretch()

        inner = QVBoxLayout()
        inner.setSpacing(6)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = _make_label("ChessGym", 24, T['title'])
        title.setFont(QFont(_UI_FONT, 24, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)
        inner.addSpacing(4)

        # 1. FEN INPUT — section card
        card_fen = QFrame()
        card_fen.setStyleSheet(_card_ss)
        cl_fen = QVBoxLayout(card_fen)
        cl_fen.setContentsMargins(*_card_m)
        cl_fen.setSpacing(6)
        cl_fen.addWidget(_section_label("FEN POSITION"))

        self._fen_input = QLineEdit()
        self._fen_input.setPlaceholderText("Paste FEN string here...")
        self._fen_input.setFont(QFont("Consolas", 11))
        self._fen_input.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self._fen_input.setStyleSheet(f"""
            QLineEdit {{
                background-color: {T['btn_bg']}; color: {T['text_primary']};
                border: 1px solid {T['btn_border']}; border-radius: 8px;
                padding: 6px 10px; min-height: 30px; max-height: 30px;
            }}
            QLineEdit:focus {{
                border-color: {T['accent_border']};
            }}
        """)
        if initial_fen:
            self._fen_input.setText(initial_fen)
        cl_fen.addWidget(self._fen_input)

        btn_row_fen = QHBoxLayout(); btn_row_fen.setSpacing(6)
        btn_build = _make_button("Build Your Position  \u2192", 12, min_height=34)
        btn_build.clicked.connect(lambda: (play_menu_click(), self.finished.emit("builder")))
        _add_press_anim(btn_build)
        btn_row_fen.addWidget(btn_build, 7)
        btn_paste = _make_button("Paste", 12, min_height=34)
        btn_paste.clicked.connect(lambda: (play_menu_click(), self._paste_fen()))
        _add_press_anim(btn_paste)
        btn_row_fen.addWidget(btn_paste, 3)
        cl_fen.addLayout(btn_row_fen)

        # Error label
        self._error_lbl = QLabel("")
        self._error_lbl.setFont(QFont(_UI_FONT, 10, QFont.Weight.Normal))
        self._error_lbl.setStyleSheet("color: rgba(220,50,50,0.9); background: transparent;")
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._error_lbl.hide()
        cl_fen.addWidget(self._error_lbl)

        inner.addWidget(card_fen)

        # 2. SIDE TO MOVE — section card
        card_stm = QFrame()
        card_stm.setStyleSheet(_card_ss)
        cl_stm = QVBoxLayout(card_stm)
        cl_stm.setContentsMargins(*_card_m)
        cl_stm.setSpacing(6)
        cl_stm.addWidget(_section_label("SIDE TO MOVE"))
        stm_row = QHBoxLayout(); stm_row.setSpacing(8)
        self._btn_stm_white = ToggleButton("White to Move", active=True)
        self._btn_stm_white.setMinimumWidth(140); self._btn_stm_white.setMinimumHeight(38)
        self._btn_stm_white.setMaximumHeight(38)
        self._btn_stm_white.clicked.connect(lambda: (play_menu_click(), self._pick_side_to_move("w")))
        _add_press_anim(self._btn_stm_white)
        stm_row.addWidget(self._btn_stm_white)
        self._btn_stm_black = ToggleButton("Black to Move", active=False)
        self._btn_stm_black.setMinimumWidth(140); self._btn_stm_black.setMinimumHeight(38)
        self._btn_stm_black.setMaximumHeight(38)
        self._btn_stm_black.clicked.connect(lambda: (play_menu_click(), self._pick_side_to_move("b")))
        _add_press_anim(self._btn_stm_black)
        stm_row.addWidget(self._btn_stm_black)
        cl_stm.addLayout(stm_row)
        inner.addWidget(card_stm)

        # 3. PLAY AS — section card
        card1 = QFrame()
        card1.setStyleSheet(_card_ss)
        cl1 = QVBoxLayout(card1)
        cl1.setContentsMargins(*_card_m)
        cl1.setSpacing(6)
        cl1.addWidget(_section_label("PLAY AS"))
        cr = QHBoxLayout(); cr.setSpacing(8)
        self._btn_white = ToggleButton("WHITE", active=True)
        self._btn_white.setMinimumWidth(140); self._btn_white.setMinimumHeight(38)
        self._btn_white.setMaximumHeight(38)
        self._btn_white.clicked.connect(lambda: (play_menu_click(), self._pick_color("white")))
        _add_press_anim(self._btn_white)
        cr.addWidget(self._btn_white)
        self._btn_black = ToggleButton("BLACK", active=False)
        self._btn_black.setMinimumWidth(140); self._btn_black.setMinimumHeight(38)
        self._btn_black.setMaximumHeight(38)
        self._btn_black.clicked.connect(lambda: (play_menu_click(), self._pick_color("black")))
        _add_press_anim(self._btn_black)
        cr.addWidget(self._btn_black)
        cl1.addLayout(cr)
        inner.addWidget(card1)

        # 4. YOUR TIME CONTROL
        card2 = QFrame()
        card2.setStyleSheet(_card_ss)
        cl2 = QVBoxLayout(card2)
        cl2.setContentsMargins(*_card_m)
        cl2.setSpacing(2)
        cl2.addWidget(_section_label("YOUR TIME CONTROL"))
        r_pm = QHBoxLayout(); r_pm.setSpacing(0)
        lbl_pm = QLabel("Minutes")
        lbl_pm.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        lbl_pm.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_pm.setFixedWidth(75); lbl_pm.setFixedHeight(36)
        r_pm.addWidget(lbl_pm); r_pm.addStretch()
        self.p_min = PillSpinner(0, 60, 3)
        r_pm.addWidget(self.p_min)
        cl2.addLayout(r_pm)
        r_pi = QHBoxLayout(); r_pi.setSpacing(0)
        lbl_pi = QLabel("Increment")
        lbl_pi.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        lbl_pi.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_pi.setFixedWidth(75); lbl_pi.setFixedHeight(36)
        r_pi.addWidget(lbl_pi); r_pi.addStretch()
        self.p_inc = PillSpinner(0, 60, 2)
        r_pi.addWidget(self.p_inc)
        cl2.addLayout(r_pi)
        inner.addWidget(card2)

        # 5. ENGINE TIME CONTROL
        card3 = QFrame()
        card3.setStyleSheet(_card_ss)
        cl3 = QVBoxLayout(card3)
        cl3.setContentsMargins(*_card_m)
        cl3.setSpacing(2)
        cl3.addWidget(_section_label("ENGINE TIME CONTROL"))
        r_em = QHBoxLayout(); r_em.setSpacing(0)
        lbl_em = QLabel("Minutes")
        lbl_em.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        lbl_em.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_em.setFixedWidth(75); lbl_em.setFixedHeight(36)
        r_em.addWidget(lbl_em); r_em.addStretch()
        self.e_min = PillSpinner(0, 60, 1)
        r_em.addWidget(self.e_min)
        cl3.addLayout(r_em)
        r_ei = QHBoxLayout(); r_ei.setSpacing(0)
        lbl_ei = QLabel("Increment")
        lbl_ei.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        lbl_ei.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        lbl_ei.setFixedWidth(75); lbl_ei.setFixedHeight(36)
        r_ei.addWidget(lbl_ei); r_ei.addStretch()
        self.e_inc = PillSpinner(0, 60, 2)
        r_ei.addWidget(self.e_inc)
        cl3.addLayout(r_ei)
        inner.addWidget(card3)

        # Start Game button
        inner.addSpacing(6)
        btn_start = _make_button("Start Game  \u2192", 13, min_height=44, min_width=320, accent=True)
        btn_start.setStyleSheet(btn_start.styleSheet().replace("border-radius: 12px", "border-radius: 12px"))
        btn_start.clicked.connect(lambda: (play_menu_click(), self._start()))
        _add_press_anim(btn_start)
        inner.addWidget(btn_start, alignment=Qt.AlignmentFlag.AlignCenter)

        # Back to Menu
        btn_back = QPushButton("Back to Menu")
        btn_back.setFont(QFont(_UI_FONT, 11, QFont.Weight.Light))
        btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['section_label']};
                border: none; padding: 4px 16px; min-height: 28px;
            }}
            QPushButton:hover {{ color: {T['text_primary']}; }}
        """)
        btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        _add_press_anim(btn_back)
        inner.addWidget(btn_back, alignment=Qt.AlignmentFlag.AlignCenter)

        hc.addLayout(inner); hc.addStretch()
        outer.addLayout(hc); outer.addStretch(2)

    def set_fen(self, fen):
        """Set the FEN input field text (called when returning from builder)."""
        if fen:
            self._fen_input.setText(fen)

    def _pick_color(self, color):
        self._color = color
        self._btn_white.set_active(color == "white")
        self._btn_black.set_active(color == "black")

    def _pick_side_to_move(self, side):
        self._side_to_move = side
        self._btn_stm_white.set_active(side == "w")
        self._btn_stm_black.set_active(side == "b")

    def _paste_fen(self):
        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()
        if text:
            self._fen_input.setText(text)

    def _start(self):
        fen = self._fen_input.text().strip()
        if not fen:
            self._error_lbl.setText("Please enter a FEN string or use Build Your Position.")
            self._error_lbl.show()
            return
        # Update the side-to-move field in the FEN
        parts = fen.split()
        if len(parts) >= 2:
            parts[1] = self._side_to_move
            fen = " ".join(parts)
        # Validate FEN
        try:
            test_board = chess.Board(fen)
            if not test_board.is_valid():
                self._error_lbl.setText("Invalid FEN: the position is not legal.")
                self._error_lbl.show()
                return
        except ValueError as e:
            self._error_lbl.setText(f"Invalid FEN: {e}")
            self._error_lbl.show()
            return
        self._error_lbl.hide()
        self.finished.emit({
            "p_min": self.p_min.value(), "p_inc": self.p_inc.value(),
            "e_min": self.e_min.value(), "e_inc": self.e_inc.value(),
            "player_color": chess.WHITE if self._color == "white" else chess.BLACK,
            "white_book": None, "black_book": None,
            "chess960": False,
            "custom_fen": fen,
        })


# ============================================================================
#  CHESS GAME PAGE
# ============================================================================

class ChessGamePage(QWidget):
    finished = pyqtSignal(str)

    def __init__(self, cfg, sf_path, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {T['bg']}; border: none;")
        self.cfg = cfg
        self.sf_path = sf_path
        self._chess960 = cfg.get("chess960", False)
        self._winpos = cfg.get("winpos", False)
        self._winpos_color = cfg.get("winpos_color", "white")
        self._winpos_range = cfg.get("winpos_range", 0)

        custom_fen = cfg.get("custom_fen")
        if custom_fen:
            self.board = chess.Board(custom_fen)
            self._start_fen = custom_fen
        elif self._winpos:
            fen = cfg.get("winpos_fen")
            self.board = chess.Board(fen)
            self._start_fen = fen
        elif self._chess960:
            try:
                pos_id = random.randint(0, 959)
                self.board = chess.Board.from_chess960_pos(pos_id)
                self.board.chess960 = True
                if not self.board.is_valid():
                    self.board = chess.Board.from_chess960_pos(518)
                    self.board.chess960 = True
                self._start_fen = self.board.fen()
            except Exception as e:
                print(f"Chess960 setup error: {e}")
                self.board = chess.Board()
                self.board.chess960 = True
                self._start_fen = self.board.fen()
        else:
            self.board = chess.Board()
            self._start_fen = None

        self.player_color = cfg["player_color"]
        self.engine_color = not self.player_color
        self.flipped = (self.player_color == chess.BLACK)
        self.p_time = cfg["p_min"] * 60.0
        self.e_time = cfg["e_min"] * 60.0
        self.p_inc = float(cfg["p_inc"])
        self.e_inc = float(cfg["e_inc"])
        self.clock_running = None
        self.clock_start = None
        self.selected = None
        self.legal_tgt = []
        self.drag_sq = None
        self.drag_pos = None
        self.last_move = None
        self.history = []
        self.status = ""
        self.game_over = False
        self.result_str = None
        self.engine_thinking = False
        self.engine_move_q = None

        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = subprocess.SW_HIDE
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(sf_path, startupinfo=si)
            self.engine.configure({"Threads": 6, "Hash": 1024})
        except Exception as e:
            print(f"Engine init error: {e}")
            raise

        self.white_book = load_book_file(cfg.get("white_book")) if not self._chess960 else None
        self.black_book = load_book_file(cfg.get("black_book")) if not self._chess960 else None

        self._build_ui()
        self._sync_board_widget()
        self._update_captured()

        self._tick_timer = QTimer(self)
        self._tick_timer.timeout.connect(self._tick)
        self._tick_timer.start(100)

        if self._winpos:
            self._start_clock("player")
            self._set_status("Your move")
        elif self.board.turn == self.player_color:
            self._start_clock("player")
            self._set_status("Your move")
        else:
            self._set_status("Engine thinking...")
            self._start_clock("engine")
            self._engine_go()

    def _captured_pieces(self, color):
        """Return list of piece symbols captured from the given color."""
        start = {"Q": 1, "R": 2, "B": 2, "N": 2, "P": 8}
        current = {"Q": 0, "R": 0, "B": 0, "N": 0, "P": 0}
        pmap = {chess.QUEEN: "Q", chess.ROOK: "R", chess.BISHOP: "B",
                chess.KNIGHT: "N", chess.PAWN: "P"}
        for sq in chess.SQUARES:
            p = self.board.piece_at(sq)
            if p and p.color == color and p.piece_type in pmap:
                current[pmap[p.piece_type]] += 1
        captured = []
        sym_w = {"Q": "\u2655", "R": "\u2656", "B": "\u2657", "N": "\u2658", "P": "\u2659"}
        sym_b = {"Q": "\u265B", "R": "\u265C", "B": "\u265D", "N": "\u265E", "P": "\u265F"}
        syms = sym_w if color == chess.WHITE else sym_b
        for pt in ["Q", "R", "B", "N", "P"]:
            diff = start[pt] - current[pt]
            for _ in range(diff):
                captured.append(syms[pt])
        return captured


    def _game_btn(self, text):
        """Create a fluffy game panel button."""
        btn = QPushButton(text)
        btn.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedHeight(44)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['btn_bg']};
                border: 1px solid {T['btn_border']};
                border-radius: 10px; padding: 0 12px;
                color: {T['btn_text']};
            }}
            QPushButton:hover {{
                background-color: {T['accent_bg']}; border-color: {T['accent_border']};
                color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: {T['accent_bg']}; }}
        """)
        _add_press_anim(btn)
        return btn

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left side: board + captured pieces (68%) ---
        left = QVBoxLayout()
        left.setContentsMargins(10, 8, 4, 8)
        left.setSpacing(2)

        # Board
        self.board_widget = BoardWidget()
        self.board_widget.piece_imgs = load_piece_pixmaps(SQ)
        self.board_widget.flipped = self.flipped
        self.board_widget.board = self.board
        self.board_widget.mousePressEvent = self._on_press
        self.board_widget.mouseMoveEvent = self._on_drag
        self.board_widget.mouseReleaseEvent = self._on_release
        left.addWidget(self.board_widget, 1)

        root.addLayout(left, 68)

        # --- Right side: panel (32%) ---
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {T['bg']};
                border-left: 1px solid {T['section_border']};
            }}
            {_frost_scrollbar_ss()}
        """)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.setSpacing(6)

        # 1. ChessGym Bot clock
        self.e_clk_frame = QFrame()
        self.e_clk_frame.setStyleSheet(self._clk_ss())
        ecl = QVBoxLayout(self.e_clk_frame)
        ecl.setContentsMargins(16, 14, 16, 14)
        ecl.setSpacing(0)
        # Color indicator + label row
        e_id_row = QHBoxLayout()
        e_id_row.setContentsMargins(0, 0, 0, 0)
        e_id_row.setSpacing(6)
        self._e_color_dot = QLabel()
        self._e_color_dot.setFixedSize(10, 10)
        bot_circle = "#1a1a1a" if self.engine_color == chess.BLACK else "#ffffff"
        bot_border = "1px solid #555" if self.engine_color == chess.WHITE else "none"
        self._e_color_dot.setStyleSheet(
            f"background-color: {bot_circle}; border-radius: 5px; border: {bot_border};")
        e_id_row.addWidget(self._e_color_dot)
        lbl_eng = QLabel("ChessGym Bot")
        lbl_eng.setFont(QFont(_UI_FONT, 11, QFont.Weight.Light))
        lbl_eng.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none; opacity: 0.6;")
        e_id_row.addWidget(lbl_eng)
        e_id_row.addStretch()
        ecl.addLayout(e_id_row)
        self.e_clk_lbl = QLabel(self._fmt_time(self.e_time))
        self.e_clk_lbl.setFont(QFont(_UI_FONT, 52, QFont.Weight.ExtraLight))
        self.e_clk_lbl.setStyleSheet(f"color: {T['title']}; background: transparent; border: none; letter-spacing: 2px;")
        self.e_clk_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        ecl.addWidget(self.e_clk_lbl)
        pl.addWidget(self.e_clk_frame)

        # 2. Status
        self.status_lbl = QLabel("")
        self.status_lbl.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
        self.status_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setContentsMargins(0, 6, 0, 6)
        pl.addWidget(self.status_lbl)

        # 3. Move history
        self.hist_text = QTextBrowser()
        self.hist_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {T['bg']}; color: {T['text_primary']};
                border: none; padding: 2px 0px;
            }}
            {_frost_scrollbar_ss()}
        """)
        self.hist_text.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.hist_text.setReadOnly(True)
        self.hist_text.setOpenLinks(False)
        pl.addWidget(self.hist_text, 1)

        # 4. You clock
        self.p_clk_frame = QFrame()
        self.p_clk_frame.setStyleSheet(self._clk_ss())
        pcl = QVBoxLayout(self.p_clk_frame)
        pcl.setContentsMargins(16, 14, 16, 14)
        pcl.setSpacing(0)
        # Color indicator + label row
        p_id_row = QHBoxLayout()
        p_id_row.setContentsMargins(0, 0, 0, 0)
        p_id_row.setSpacing(6)
        self._p_color_dot = QLabel()
        self._p_color_dot.setFixedSize(10, 10)
        you_circle = "#1a1a1a" if self.player_color == chess.BLACK else "#ffffff"
        you_border = "1px solid #555" if self.player_color == chess.WHITE else "none"
        self._p_color_dot.setStyleSheet(
            f"background-color: {you_circle}; border-radius: 5px; border: {you_border};")
        p_id_row.addWidget(self._p_color_dot)
        lbl_you = QLabel("You")
        lbl_you.setFont(QFont(_UI_FONT, 11, QFont.Weight.Light))
        lbl_you.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none; opacity: 0.6;")
        p_id_row.addWidget(lbl_you)
        p_id_row.addStretch()
        pcl.addLayout(p_id_row)
        self.p_clk_lbl = QLabel(self._fmt_time(self.p_time))
        self.p_clk_lbl.setFont(QFont(_UI_FONT, 52, QFont.Weight.ExtraLight))
        self.p_clk_lbl.setStyleSheet(f"color: {T['title']}; background: transparent; border: none; letter-spacing: 2px;")
        self.p_clk_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        pcl.addWidget(self.p_clk_lbl)
        pl.addWidget(self.p_clk_frame)

        # 5. Buttons — 2-column grid + full-width Menu
        r1 = QHBoxLayout(); r1.setSpacing(4)
        new_label = "Next Position" if self._winpos else "New Game"
        btn_new = self._game_btn(new_label)
        btn_new.clicked.connect(self._new_game)
        r1.addWidget(btn_new)
        btn_flip = self._game_btn("Flip")
        btn_flip.clicked.connect(self._flip)
        r1.addWidget(btn_flip)
        pl.addLayout(r1)

        r2 = QHBoxLayout(); r2.setSpacing(4)
        self.resign_btn = self._game_btn("Resign")
        self.resign_btn.clicked.connect(self._resign)
        r2.addWidget(self.resign_btn)
        btn_save = self._game_btn("Save PGN")
        btn_save.clicked.connect(self._save_pgn)
        r2.addWidget(btn_save)
        pl.addLayout(r2)

        btn_menu = self._game_btn("Menu")
        btn_menu.clicked.connect(self._back_to_menu_cmd)
        pl.addWidget(btn_menu)

        root.addWidget(panel, 32)

        # Overlay for game-end dialog
        self._overlay = None
        self._end_dialog = None

        QShortcut(QKeySequence("F11"), self).activated.connect(self._toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self).activated.connect(self._exit_fullscreen)

    @staticmethod
    def _clk_ss():
        return (f"background-color: {T['section_bg']}; "
                f"border: 1px solid {T['section_border']}; border-radius: 11px;")

    def _sync_board_widget(self):
        bw = self.board_widget
        bw.board = self.board
        bw.flipped = self.flipped
        bw.selected = self.selected
        bw.legal_tgt = self.legal_tgt
        bw.last_move = self.last_move
        bw.drag_sq = self.drag_sq
        bw.drag_pos = self.drag_pos
        bw.game_over = self.game_over
        bw.update()

    def _toggle_fullscreen(self):
        win = self.window()
        if win.isFullScreen(): win.showMaximized()
        else: win.showFullScreen()

    def _exit_fullscreen(self):
        win = self.window()
        if win.isFullScreen(): win.showMaximized()

    def _fmt_time(self, secs):
        secs = max(0.0, secs)
        m = int(secs) // 60; s = int(secs) % 60
        return f"{m}:{s:02d}"

    def _start_clock(self, side):
        self.clock_running = side; self.clock_start = time.time()

    def _stop_clock(self):
        if self.clock_running is None: return
        elapsed = time.time() - self.clock_start
        if self.clock_running == "player":
            self.p_time -= elapsed; self.p_time += self.p_inc
        else:
            self.e_time -= elapsed; self.e_time += self.e_inc
        self.clock_running = None; self.clock_start = None

    def _live_time(self, side):
        base = self.p_time if side == "player" else self.e_time
        if self.clock_running == side and self.clock_start:
            base -= (time.time() - self.clock_start)
        return max(0.0, base)

    def _update_captured(self):
        pass

    def _tick(self):
        if not self.game_over:
            pt = self._live_time("player"); et = self._live_time("engine")
            self.p_clk_lbl.setText(self._fmt_time(pt))
            self.e_clk_lbl.setText(self._fmt_time(et))

            if pt <= 0 and self.clock_running == "player":
                self._end_game("You lost · Time", "0-1"); return
            if et <= 0 and self.clock_running == "engine":
                self._end_game("You won · Bot timeout", "1-0"); return
            if self.engine_move_q is not None:
                mv = self.engine_move_q; self.engine_move_q = None
                self._apply_engine_move(mv)

    def _set_status(self, msg):
        self.status = msg
        if msg == "Your move":
            self.status_lbl.setText("Your move")
        elif "thinking" in msg.lower() or "engine" in msg.lower():
            self.status_lbl.setText("ChessGym Bot is thinking...")
        else:
            self.status_lbl.setText(msg)

    def _on_press(self, event: QMouseEvent):
        if self.game_over or self.board.turn != self.player_color: return
        pos = event.position()
        x, y = int(pos.x()), int(pos.y())
        sq = self.board_widget.sq_from_pixel(x, y)
        if sq is None:
            self.selected = None; self.legal_tgt = []
            self._sync_board_widget(); return
        if self.selected is not None:
            p = self.board.piece_at(self.selected)
            promo = chess.QUEEN if p and p.piece_type == chess.PAWN and chess.square_rank(sq) in (0, 7) else None
            move = chess.Move(self.selected, sq, promotion=promo)
            if move in self.board.legal_moves:
                self._make_player_move(move); return
        p = self.board.piece_at(sq)
        if p and p.color == self.player_color:
            self.selected = sq
            self.legal_tgt = [m.to_square for m in self.board.legal_moves if m.from_square == sq]
            self.drag_sq = sq; self.drag_pos = (x, y)
        else:
            self.selected = None; self.legal_tgt = []
            self.drag_sq = None; self.drag_pos = None
        self._sync_board_widget()

    def _on_drag(self, event: QMouseEvent):
        if self.drag_sq is None: return
        pos = event.position()
        self.drag_pos = (int(pos.x()), int(pos.y()))
        self._sync_board_widget()

    def _on_release(self, event: QMouseEvent):
        if self.drag_sq is None: return
        from_sq = self.drag_sq
        self.drag_sq = None; self.drag_pos = None
        pos = event.position()
        to_sq = self.board_widget.sq_from_pixel(int(pos.x()), int(pos.y()))
        if to_sq is not None and to_sq != from_sq:
            p = self.board.piece_at(from_sq)
            promo = chess.QUEEN if p and p.piece_type == chess.PAWN and chess.square_rank(to_sq) in (0, 7) else None
            move = chess.Move(from_sq, to_sq, promotion=promo)
            if move in self.board.legal_moves:
                self._make_player_move(move, animate=False); return
        self._sync_board_widget()

    def _make_player_move(self, move, animate=True):
        self._stop_clock()
        san = self.board.san(move)
        self.board.push(move)
        play_move_sound()
        self.last_move = move; self.history.append(san)
        self.selected = None; self.legal_tgt = []
        self._update_history(); self._update_captured(); self._sync_board_widget()
        if self._check_game_over(): return
        self._set_status("Engine thinking...")
        self._start_clock("engine"); self._engine_go()

    def _engine_go(self):
        self.engine_thinking = True
        remaining = max(0.1, self._live_time("engine"))
        think_time = min(remaining * 0.05 + self.e_inc * 0.8, remaining * 0.25)
        think_time = max(0.1, think_time)
        limit = chess.engine.Limit(time=think_time)
        bc = self.board.copy()
        if self._chess960: bc.chess960 = True
        book = None if self._winpos else (self.white_book if self.engine_color == chess.WHITE else self.black_book)
        def think():
            try:
                if self.game_over: self.engine_thinking = False; return
                mv = get_book_move(bc, book)
                if mv is None:
                    result = self.engine.play(bc, limit)
                    mv = result.move
                if not self.game_over: self.engine_move_q = mv
            except Exception as e:
                print(f"Engine error: {e}")
                try:
                    if not self.game_over:
                        result = self.engine.play(bc, chess.engine.Limit(time=1.0))
                        self.engine_move_q = result.move
                except Exception as e2:
                    print(f"Engine retry also failed: {e2}")
            self.engine_thinking = False
        threading.Thread(target=think, daemon=True).start()

    def _apply_engine_move(self, move):
        if self.game_over: return
        self._stop_clock()
        if move and move in self.board.legal_moves:
            san = self.board.san(move)
            self.board.push(move)
            play_move_sound()
            self.last_move = move; self.history.append(san)
            self._update_history(); self._update_captured()
            self._sync_board_widget()
            if self._check_game_over(): return
            self._set_status("Your move")
            self._start_clock("player")
        else:
            self._sync_board_widget()
            if self._check_game_over(): return
            self._set_status("Your move")
            self._start_clock("player")

    def _check_game_over(self):
        b = self.board
        if b.is_checkmate():
            if b.turn == self.player_color:
                result_text = "You lost \u00b7 Checkmate"
            else:
                result_text = "You won \u00b7 Checkmate"
            res = "0-1" if b.turn == chess.WHITE else "1-0"
            self._end_game(result_text, res); return True
        if b.is_stalemate():
            self._end_game("Draw \u00b7 Stalemate", "1/2-1/2"); return True
        if b.is_insufficient_material():
            self._end_game("Draw \u00b7 Insufficient material", "1/2-1/2"); return True
        if b.can_claim_fifty_moves():
            self._end_game("Draw \u00b7 50-move rule", "1/2-1/2"); return True
        if b.can_claim_threefold_repetition():
            self._end_game("Draw \u00b7 Repetition", "1/2-1/2"); return True
        return False

    def _end_game(self, result_text, result):
        self.game_over = True; self.clock_running = None
        self.engine_thinking = False; self.engine_move_q = None
        self.result_str = result
        self._set_status(result_text)
        self._append_result_to_history(result_text)
        self._sync_board_widget()
        self._auto_save_pgn()

    def _append_result_to_history(self, result_text):
        """Append a muted result line at the end of the move history."""
        html = self.hist_text.toHtml()
        result_html = (
            f'<div style="font-family:{_UI_FONT},sans-serif;font-size:12pt;'
            f'font-weight:400;font-style:italic;color:{T["text_muted"]};'
            f'padding-top:8px;">{result_text}</div>')
        # Insert before the closing body/html tag
        if '</body>' in html:
            html = html.replace('</body>', result_html + '</body>')
        else:
            html += result_html
        self.hist_text.setHtml(html)
        self._smooth_scroll_history()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._overlay:
            self._overlay.setGeometry(0, 0, self.width(), self.height())
        if self._end_dialog:
            dx = (self.width() - 380) // 2
            dy = (self.height() - 220) // 2
            self._end_dialog.move(dx, dy)

    def _update_history(self):
        if not self.history:
            self.hist_text.setHtml(""); return
        last_idx = len(self.history) - 1
        rows = []
        for i in range(0, len(self.history), 2):
            mn = i // 2 + 1
            # Alternating row bg
            rbg = T['section_bg'] if mn % 2 == 0 else "transparent"
            m1 = self.history[i] if i < len(self.history) else ""
            m2 = self.history[i + 1] if i + 1 < len(self.history) else ""
            # Highlight current move
            if i == last_idx:
                m1_html = (f'<span style="background-color:{T["accent_bg"]};'
                           f'color:{T["accent_text"]};padding:2px 4px;border-radius:3px;">{m1}</span>')
            else:
                m1_html = f'<span style="color:{T["text_primary"]};">{m1}</span>'
            if i + 1 == last_idx and m2:
                m2_html = (f'<span style="background-color:{T["accent_bg"]};'
                           f'color:{T["accent_text"]};padding:2px 4px;border-radius:3px;">{m2}</span>')
            elif m2:
                m2_html = f'<span style="color:{T["text_primary"]};">{m2}</span>'
            else:
                m2_html = ""
            rows.append(
                f'<tr style="background:{rbg};height:28px;">'
                f'<td style="color:{T["text_muted"]};padding:3px 6px 3px 4px;'
                f'text-align:right;white-space:nowrap;font-size:11pt;font-weight:300;">{mn}.</td>'
                f'<td style="padding:3px 8px;white-space:nowrap;font-size:13pt;font-weight:400;">{m1_html}</td>'
                f'<td style="padding:3px 8px;white-space:nowrap;font-size:13pt;font-weight:400;">{m2_html}</td>'
                f'</tr>')
        html = (f'<table cellspacing="0" cellpadding="0" '
                f'style="font-family:{_UI_FONT},sans-serif;font-size:13pt;width:100%;">'
                + "".join(rows) + '</table>')
        self.hist_text.setHtml(html)
        self._smooth_scroll_history()

    def _smooth_scroll_history(self):
        sb = self.hist_text.verticalScrollBar()
        target = sb.maximum()
        if target <= 0 or sb.value() >= target - 2:
            sb.setValue(target); return
        anim = QPropertyAnimation(sb, b"value", self.hist_text)
        anim.setStartValue(sb.value())
        anim.setEndValue(target)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # Store ref to prevent GC
        self.hist_text._scroll_anim = anim
        anim.start()

    def _flip(self):
        self.flipped = not self.flipped
        self._sync_board_widget()

    def _resign(self):
        if self.game_over: return
        self.engine_thinking = False; self.engine_move_q = None
        res = "0-1" if self.player_color == chess.WHITE else "1-0"
        self._end_game("You lost · Resigned", res)

    def _build_pgn_game(self):
        game = chess.pgn.Game()
        if self._winpos: game.headers["Event"] = "ChessGym Winning Position"
        elif self._chess960: game.headers["Event"] = "ChessGym Chess960"
        else: game.headers["Event"] = "ChessGym Training"
        game.headers["White"] = "You" if self.player_color == chess.WHITE else "ChessGym Bot"
        game.headers["Black"] = "ChessGym Bot" if self.player_color == chess.WHITE else "You"
        game.headers["Date"] = datetime.datetime.now().strftime("%Y.%m.%d")
        game.headers["Result"] = self.result_str or "*"
        if self._chess960 and self._start_fen:
            game.headers["Variant"] = "Chess960"
            starting = chess.Board(self._start_fen); starting.chess960 = True
            game.setup(starting)
        elif self._winpos and self._start_fen:
            game.setup(chess.Board(self._start_fen))
        node = game; tmp = game.board()
        for san in self.history:
            try: mv = tmp.parse_san(san); node = node.add_variation(mv); tmp.push(mv)
            except: break
        return game

    def _auto_save_pgn(self):
        try:
            folder = os.path.join(BASE_DIR, "ChessGym Games")
            os.makedirs(folder, exist_ok=True)
            fname = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S") + ".pgn"
            path = os.path.join(folder, fname)
            game = self._build_pgn_game()
            with open(path, "w", encoding="utf-8") as f: f.write(str(game))
            QTimer.singleShot(1500, lambda: self._set_status("Game saved"))
        except Exception as e:
            print(f"[AutoSave] Failed to save game: {e}")

    def _save_pgn(self):
        game = self._build_pgn_game()
        path, _ = QFileDialog.getSaveFileName(self, "Save PGN",
            os.path.join(BASE_DIR, f"chessgym_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.pgn"),
            "PGN files (*.pgn);;All files (*.*)")
        if path:
            with open(path, "w", encoding="utf-8") as f: f.write(str(game))
            self._set_status("PGN saved!")

    def _new_game(self):
        # Auto-save the current game if it has moves (whether finished or abandoned)
        if self.history:
            if not self.game_over:
                self.result_str = "*"
            self._auto_save_pgn()
        if self._winpos:
            fens = _load_winpos_fens(self._winpos_color, self._winpos_range)
            if fens:
                fen = random.choice(fens); self.board = chess.Board(fen); self._start_fen = fen
            else:
                self._set_status("No positions available"); return
        elif self._chess960:
            try:
                pos_id = random.randint(0, 959)
                self.board = chess.Board.from_chess960_pos(pos_id)
                self.board.chess960 = True
                if not self.board.is_valid():
                    self.board = chess.Board.from_chess960_pos(518); self.board.chess960 = True
                self._start_fen = self.board.fen()
            except Exception as e:
                self.board = chess.Board(); self.board.chess960 = True; self._start_fen = self.board.fen()
        else:
            self.board = chess.Board()
        self.selected = None; self.legal_tgt = []
        self.last_move = None; self.history = []
        self.game_over = False; self.engine_thinking = False
        self.engine_move_q = None; self.result_str = None
        self.drag_sq = None; self.drag_pos = None
        self.p_time = self.cfg["p_min"] * 60.0
        self.e_time = self.cfg["e_min"] * 60.0
        self.clock_running = None; self.clock_start = None
        self.p_clk_lbl.setText(self._fmt_time(self.p_time))
        self.e_clk_lbl.setText(self._fmt_time(self.e_time))
        self._update_history(); self._update_captured(); self._sync_board_widget()
        if self._winpos:
            self._start_clock("player"); self._set_status("Your move")
        elif self.board.turn == self.player_color:
            self._start_clock("player"); self._set_status("Your move")
        else:
            self._set_status("Engine thinking...")
            self._start_clock("engine"); self._engine_go()

    def _back_to_menu_cmd(self):
        # Auto-save the current game if it has moves (whether finished or abandoned)
        if self.history and not self.game_over:
            self.result_str = "*"
            self._auto_save_pgn()
        self._cleanup_engine()
        self.finished.emit("back")

    def _cleanup_engine(self):
        self.game_over = True; self.engine_thinking = False
        self.engine_move_q = None; self.clock_running = None
        self._tick_timer.stop()
        try: self.engine.quit()
        except: pass

    def cleanup(self):
        self._cleanup_engine()


# ============================================================================
#  WINNING POSITIONS SETUP PAGE
# ============================================================================

class WinPosSetupPage(FrostBackground):
    finished = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._range_idx = 0
        self._color = "white"
        self._build_ui()

    def _make_section_card(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 13px;
            }}
        """)
        return card

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        hc = QHBoxLayout(); hc.addStretch()

        inner = QVBoxLayout()
        inner.setSpacing(10)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._title_lbl = _make_label("ChessGym", 28, T['title'])
        self._title_lbl.setFont(QFont(_UI_FONT, 28, QFont.Weight.Light))
        self._title_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(self._title_lbl)
        inner.addSpacing(8)

        # 1. ADVANTAGE LEVEL — section card
        card1 = self._make_section_card()
        cl1 = QVBoxLayout(card1)
        cl1.setContentsMargins(18, 16, 18, 16)
        cl1.setSpacing(12)
        self._sec_lbl_adv = _section_label("ADVANTAGE LEVEL")
        cl1.addWidget(self._sec_lbl_adv)
        self._range_btn_row = QHBoxLayout(); self._range_btn_row.setSpacing(8)
        self._range_btns = []
        for i, r in enumerate(_WPOS_RANGES):
            btn = ToggleButton(r["label"], active=(i == 0))
            btn.setFont(QFont(_UI_FONT, 12, QFont.Weight.Normal))
            btn.setMinimumWidth(110)
            btn.clicked.connect(lambda checked, idx=i: (play_menu_click(), self._pick_range(idx)))
            _add_press_anim(btn)
            self._range_btn_row.addWidget(btn)
            self._range_btns.append(btn)
        cl1.addLayout(self._range_btn_row)

        # Position count indicator
        self._pos_count_lbl = QLabel("")
        self._pos_count_lbl.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
        self._pos_count_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
        self._pos_count_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pos_count_lbl.setWordWrap(True)
        cl1.addWidget(self._pos_count_lbl)
        self._update_pos_count()

        self._card1 = card1; self._cl1 = cl1
        inner.addWidget(card1)

        # 2. PLAY AS — section card
        card2 = self._make_section_card()
        cl2 = QVBoxLayout(card2)
        cl2.setContentsMargins(18, 16, 18, 16)
        cl2.setSpacing(12)
        self._sec_lbl_play = _section_label("PLAY AS")
        cl2.addWidget(self._sec_lbl_play)
        cr = QHBoxLayout(); cr.setSpacing(12)
        self._btn_white = ToggleButton("WHITE", active=True)
        self._btn_white.setMinimumWidth(180)
        self._btn_white.clicked.connect(lambda: (play_menu_click(), self._pick_color("white")))
        _add_press_anim(self._btn_white)
        cr.addWidget(self._btn_white)
        self._btn_black = ToggleButton("BLACK", active=False)
        self._btn_black.setMinimumWidth(180)
        self._btn_black.clicked.connect(lambda: (play_menu_click(), self._pick_color("black")))
        _add_press_anim(self._btn_black)
        cr.addWidget(self._btn_black)
        cl2.addLayout(cr)
        self._card2 = card2; self._cl2 = cl2
        inner.addWidget(card2)

        # 3. YOUR TIME CONTROL — section card with pill spinners
        card3 = self._make_section_card()
        cl3 = QVBoxLayout(card3)
        cl3.setContentsMargins(18, 16, 18, 16)
        cl3.setSpacing(6)
        self._sec_lbl_ytc = _section_label("YOUR TIME CONTROL")
        cl3.addWidget(self._sec_lbl_ytc)
        r_pm = QHBoxLayout(); r_pm.setSpacing(0)
        self._lbl_pm = QLabel("Minutes")
        self._lbl_pm.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        self._lbl_pm.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        self._lbl_pm.setFixedWidth(80); self._lbl_pm.setFixedHeight(44)
        r_pm.addWidget(self._lbl_pm); r_pm.addStretch()
        self.p_min = PillSpinner(0, 60, 3)
        r_pm.addWidget(self.p_min)
        cl3.addLayout(r_pm)
        r_pi = QHBoxLayout(); r_pi.setSpacing(0)
        self._lbl_pi = QLabel("Increment")
        self._lbl_pi.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        self._lbl_pi.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        self._lbl_pi.setFixedWidth(80); self._lbl_pi.setFixedHeight(44)
        r_pi.addWidget(self._lbl_pi); r_pi.addStretch()
        self.p_inc = PillSpinner(0, 60, 2)
        r_pi.addWidget(self.p_inc)
        cl3.addLayout(r_pi)
        self._card3 = card3; self._cl3 = cl3
        inner.addWidget(card3)

        # 4. ENGINE TIME CONTROL — section card with pill spinners
        card4 = self._make_section_card()
        cl4 = QVBoxLayout(card4)
        cl4.setContentsMargins(18, 16, 18, 16)
        cl4.setSpacing(6)
        self._sec_lbl_etc = _section_label("ENGINE TIME CONTROL")
        cl4.addWidget(self._sec_lbl_etc)
        r_em = QHBoxLayout(); r_em.setSpacing(0)
        self._lbl_em = QLabel("Minutes")
        self._lbl_em.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        self._lbl_em.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        self._lbl_em.setFixedWidth(80); self._lbl_em.setFixedHeight(44)
        r_em.addWidget(self._lbl_em); r_em.addStretch()
        self.e_min = PillSpinner(0, 60, 1)
        r_em.addWidget(self.e_min)
        cl4.addLayout(r_em)
        r_ei = QHBoxLayout(); r_ei.setSpacing(0)
        self._lbl_ei = QLabel("Increment")
        self._lbl_ei.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        self._lbl_ei.setStyleSheet(f"color: {T['pill_label']}; background: transparent;")
        self._lbl_ei.setFixedWidth(80); self._lbl_ei.setFixedHeight(44)
        r_ei.addWidget(self._lbl_ei); r_ei.addStretch()
        self.e_inc = PillSpinner(0, 60, 2)
        r_ei.addWidget(self.e_inc)
        cl4.addLayout(r_ei)
        self._card4 = card4; self._cl4 = cl4
        inner.addWidget(card4)

        inner.addSpacing(12)
        self._btn_start = _make_button("Start Game  \u2192", 14, min_height=52, min_width=320, accent=True)
        self._btn_start.setStyleSheet(self._btn_start.styleSheet().replace("border-radius: 12px", "border-radius: 13px"))
        self._btn_start.clicked.connect(lambda: (play_menu_click(), self._start()))
        _add_press_anim(self._btn_start)
        inner.addWidget(self._btn_start, alignment=Qt.AlignmentFlag.AlignCenter)
        self._btn_back = QPushButton("Back to Menu")
        self._btn_back.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        self._btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['section_label']};
                border: none; padding: 8px 20px; min-height: 36px;
            }}
            QPushButton:hover {{ color: {T['text_primary']}; }}
        """)
        self._btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        _add_press_anim(self._btn_back)
        inner.addWidget(self._btn_back, alignment=Qt.AlignmentFlag.AlignCenter)
        self._btn_scanner = _make_button("Add New Positions", 11, min_height=32)
        self._btn_scanner.clicked.connect(lambda: (play_menu_click(), self.finished.emit("scanner")))
        _add_press_anim(self._btn_scanner)
        inner.addWidget(self._btn_scanner, alignment=Qt.AlignmentFlag.AlignCenter)

        self._inner = inner
        hc.addLayout(inner); hc.addStretch()
        outer.addLayout(hc); outer.addStretch(2)

        # Store all time-control labels for rescaling
        self._time_labels = [self._lbl_pm, self._lbl_pi, self._lbl_em, self._lbl_ei]
        self._section_labels = [self._sec_lbl_adv, self._sec_lbl_play, self._sec_lbl_ytc, self._sec_lbl_etc]
        self._card_layouts = [self._cl1, self._cl2, self._cl3, self._cl4]
        self._last_scale = -1.0

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        """Dynamically scale fonts and spacing based on window size."""
        w = self.width(); h = self.height()
        # Reference design size — scale relative to this
        ref = 800
        s = min(w, h) / ref
        s = max(0.55, min(s, 1.0))

        # Avoid redundant updates when scale hasn't meaningfully changed
        if abs(s - self._last_scale) < 0.02:
            return
        self._last_scale = s

        # Title
        self._title_lbl.setFont(QFont(_UI_FONT, max(16, int(28 * s)), QFont.Weight.Light))

        # Section labels
        sec_fs = max(8, int(10 * s))
        for lbl in self._section_labels:
            lbl.setFont(QFont(_UI_FONT, sec_fs, QFont.Weight.Normal))

        # Advantage-level range buttons
        range_fs = max(9, int(12 * s))
        range_mw = max(60, int(110 * s))
        range_mh = max(34, int(52 * s))
        for btn in self._range_btns:
            btn.setFont(QFont(_UI_FONT, range_fs, QFont.Weight.Normal))
            btn.setMinimumWidth(range_mw)
            btn.setMinimumHeight(range_mh)
            # Update stylesheet min-height to match
            cur = btn.styleSheet()
            import re as _re
            cur = _re.sub(r'min-height:\s*\d+px', f'min-height: {range_mh}px', cur)
            cur = _re.sub(r'font-size:\s*\d+px', f'font-size: {range_fs}px', cur)
            btn.setStyleSheet(cur)
        self._range_btn_row.setSpacing(max(4, int(8 * s)))

        # Position count label
        self._pos_count_lbl.setFont(QFont(_UI_FONT, max(8, int(11 * s)), QFont.Weight.Normal))

        # Play-as buttons
        color_mw = max(90, int(180 * s))
        color_mh = max(34, int(52 * s))
        color_fs = max(10, int(13 * s))
        for btn in [self._btn_white, self._btn_black]:
            btn.setFont(QFont(_UI_FONT, color_fs, QFont.Weight.Normal))
            btn.setMinimumWidth(color_mw)
            btn.setMinimumHeight(color_mh)
            cur = btn.styleSheet()
            import re as _re
            cur = _re.sub(r'min-height:\s*\d+px', f'min-height: {color_mh}px', cur)
            cur = _re.sub(r'font-size:\s*\d+px', f'font-size: {color_fs}px', cur)
            btn.setStyleSheet(cur)

        # Time-control labels
        tc_fs = max(9, int(13 * s))
        tc_w = max(50, int(80 * s))
        tc_h = max(28, int(44 * s))
        for lbl in self._time_labels:
            lbl.setFont(QFont(_UI_FONT, tc_fs, QFont.Weight.Light))
            lbl.setFixedWidth(tc_w)
            lbl.setFixedHeight(tc_h)

        # Card margins
        cm_h = max(10, int(18 * s))
        cm_v = max(8, int(16 * s))
        cm_sp_top = max(6, int(12 * s))
        cm_sp_tc = max(3, int(6 * s))
        for i, cl in enumerate(self._card_layouts):
            cl.setContentsMargins(cm_h, cm_v, cm_h, cm_v)
            cl.setSpacing(cm_sp_top if i <= 1 else cm_sp_tc)

        # Inner layout spacing
        self._inner.setSpacing(max(5, int(10 * s)))

        # Start button
        start_fs = max(10, int(14 * s))
        start_mh = max(34, int(52 * s))
        start_mw = max(180, int(320 * s))
        self._btn_start.setFont(QFont(_UI_FONT, start_fs, QFont.Weight.Normal))
        self._btn_start.setMinimumHeight(start_mh)
        self._btn_start.setMinimumWidth(start_mw)

        # Back button
        self._btn_back.setFont(QFont(_UI_FONT, max(9, int(12 * s)), QFont.Weight.Light))

        # Scanner button
        self._btn_scanner.setFont(QFont(_UI_FONT, max(8, int(11 * s)), QFont.Weight.Normal))

    def _pick_range(self, idx):
        self._range_idx = idx
        for i, btn in enumerate(self._range_btns): btn.set_active(i == idx)
        self._update_pos_count()

    def _pick_color(self, color):
        self._color = color
        self._btn_white.set_active(color == "white")
        self._btn_black.set_active(color == "black")
        self._update_pos_count()

    def _update_pos_count(self):
        fens = _load_winpos_fens(self._color, self._range_idx)
        n = len(fens)
        if n == 0:
            self._pos_count_lbl.setText("No positions yet \u2014 click 'Add New Positions' to scan a PGN database")
            self._pos_count_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
        else:
            self._pos_count_lbl.setText(f"{n} position{'s' if n != 1 else ''} available")
            self._pos_count_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")

    def _start(self):
        color = self._color; ri = self._range_idx
        fens = _load_winpos_fens(color, ri)
        if not fens:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(
                self, "No Positions Available",
                "No positions found for this category.\n\n"
                "Please click 'Add New Positions' first\n"
                "to scan your PGN database.")
            return
        fen = random.choice(fens)
        self.finished.emit({
            "p_min": self.p_min.value(), "p_inc": self.p_inc.value(),
            "e_min": self.e_min.value(), "e_inc": self.e_inc.value(),
            "player_color": chess.WHITE if color == "white" else chess.BLACK,
            "white_book": None, "black_book": None, "chess960": False,
            "winpos": True, "winpos_fen": fen,
            "winpos_color": color, "winpos_range": ri,
        })


# ============================================================================
#  SCANNER PAGE
# ============================================================================

class ScannerPage(FrostBackground):
    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop_event = threading.Event()
        self._scan_thread = None
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.addStretch()
        hc = QHBoxLayout(); hc.addStretch()

        inner = QVBoxLayout()
        inner.setSpacing(8)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = _make_label("ChessGym", 28, T['title'])
        title.setFont(QFont(_UI_FONT, 28, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)
        inner.addWidget(_separator())
        self._counts_lbl = _make_label("", 13, T['text_muted'], font_family=_MONO_FONT)
        self._counts_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(self._counts_lbl)
        self._refresh_counts()

        inner.addWidget(_separator())
        inner.addWidget(_section_label("PGN FILES IN SCANNER INPUT"))

        # Scrollable file list container
        self._file_list_area = QScrollArea()
        self._file_list_area.setWidgetResizable(True)
        self._file_list_area.setMaximumHeight(130)
        self._file_list_area.setStyleSheet(f"""
            QScrollArea {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']}; border-radius: 8px;
            }}
            {_frost_scrollbar_ss()}
        """)
        self._file_list_container = QWidget()
        self._file_list_container.setStyleSheet("background: transparent; border: none;")
        self._file_list_layout = QVBoxLayout(self._file_list_container)
        self._file_list_layout.setContentsMargins(0, 4, 0, 4)
        self._file_list_layout.setSpacing(0)
        self._file_list_layout.addStretch()
        self._file_list_area.setWidget(self._file_list_container)
        inner.addWidget(self._file_list_area)

        # Clear All button (must be created before _refresh_file_list)
        self._clear_all_btn = QPushButton("CLEAR ALL")
        self._clear_all_btn.setFont(QFont(_UI_FONT, 10, QFont.Weight.Normal))
        self._clear_all_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._clear_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {T['toggle_inactive_text']};
                font-size: 10px; letter-spacing: 1px;
                padding: 2px 8px;
            }}
            QPushButton:hover {{
                color: rgba(200,80,80,0.7);
            }}
        """)
        self._clear_all_btn.clicked.connect(self._clear_all_files)
        self._clear_all_btn.hide()
        inner.addWidget(self._clear_all_btn, alignment=Qt.AlignmentFlag.AlignRight)
        self._refresh_file_list()

        btn_add = _make_button("Select PGN Database", 12, min_height=36)
        btn_add.clicked.connect(lambda: (play_menu_click(), self._add_pgn()))
        inner.addWidget(btn_add, alignment=Qt.AlignmentFlag.AlignCenter)

        inner.addWidget(_separator())
        self._status_lbl = _make_label("Ready to scan.", 13, T['text_muted'])
        self._status_lbl.setWordWrap(True)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(self._status_lbl)

        self._progress = QProgressBar()
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background-color: {T['section_bg']}; border: 1px solid {T['section_border']};
                border-radius: 6px; height: 12px; text-align: center;
                color: {T['title']};
            }}
            QProgressBar::chunk {{
                background-color: {T['accent_text']}; border-radius: 5px;
            }}
        """)
        self._progress.setMinimumWidth(400)
        inner.addWidget(self._progress)

        br = QHBoxLayout(); br.setSpacing(8)
        self._start_btn = _make_button("Start Scanning", 12, min_height=40, accent=True)
        self._start_btn.clicked.connect(lambda: (play_menu_click(), self._start_scan()))
        br.addWidget(self._start_btn)
        self._stop_btn = _make_button("Stop", 12, min_height=40)
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(lambda: (play_menu_click(), self._stop_scan()))
        br.addWidget(self._stop_btn)
        inner.addLayout(br)

        inner.addWidget(_separator())
        btn_back = _make_button("Back", 12, min_height=36)
        btn_back.clicked.connect(lambda: (play_menu_click(), self._back()))
        inner.addWidget(btn_back, alignment=Qt.AlignmentFlag.AlignCenter)

        hc.addLayout(inner); hc.addStretch()
        outer.addLayout(hc); outer.addStretch()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_updates)
        self._pending_info = None

    def _refresh_counts(self):
        counts = position_scanner.get_position_counts()
        parts = []
        for i, r in enumerate(position_scanner.RANGES):
            total = counts[i]["w"] + counts[i]["b"]
            parts.append(f"{r['label']}: {total}")
        self._counts_lbl.setText("  |  ".join(parts))

    def _refresh_file_list(self):
        # Clear existing rows (except the trailing stretch)
        while self._file_list_layout.count() > 1:
            item = self._file_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        files = position_scanner.list_pgn_files()
        for fname in files:
            row = self._make_file_row(fname)
            self._file_list_layout.insertWidget(self._file_list_layout.count() - 1, row)
        if files:
            self._clear_all_btn.show()
        else:
            self._clear_all_btn.hide()

    def _make_file_row(self, fname):
        row = QFrame()
        row.setFixedHeight(36)
        row.setStyleSheet("background: transparent; border: none;")
        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 0, 8, 0)
        rl.setSpacing(0)
        lbl = QLabel(fname)
        lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        lbl.setStyleSheet(f"color: {T['title']}; background: transparent; border: none;")
        rl.addWidget(lbl, 1)
        x_btn = QPushButton("\u00d7")
        x_btn.setFixedSize(20, 20)
        x_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        x_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; border-radius: 4px;
                color: {T['toggle_inactive_text']}; font-size: 14px;
                padding: 0; margin: 0;
            }}
            QPushButton:hover {{
                color: rgba(200,80,80,0.85); background: rgba(200,80,80,0.1);
            }}
        """)
        x_btn.hide()
        x_btn.clicked.connect(lambda: self._remove_file(fname))
        rl.addWidget(x_btn)
        row._x_btn = x_btn
        row.enterEvent = lambda e, b=x_btn: b.show()
        row.leaveEvent = lambda e, b=x_btn: b.hide()
        return row

    def _remove_file(self, fname):
        if self._scan_thread and self._scan_thread.is_alive():
            return
        position_scanner.remove_pgn_file(fname)
        self._refresh_file_list()
        self._status_lbl.setText(f"Removed: {fname}")

    def _clear_all_files(self):
        if self._scan_thread and self._scan_thread.is_alive():
            return
        files = position_scanner.list_pgn_files()
        if not files:
            return
        for fname in files:
            position_scanner.remove_pgn_file(fname)
        self._refresh_file_list()
        self._status_lbl.setText("All files removed.")

    def _add_pgn(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select PGN Database", "",
            "PGN files (*.pgn);;All files (*.*)")
        if path:
            fname = position_scanner.add_pgn_file(path)
            self._refresh_file_list()
            self._status_lbl.setText(f"Added: {fname}")

    def _start_scan(self):
        if self._scan_thread and self._scan_thread.is_alive(): return
        self._stop_event.clear()
        self._start_btn.setEnabled(False); self._stop_btn.setEnabled(True)
        self._progress.setValue(0)
        self._status_lbl.setText("Starting...")
        self._scan_thread = threading.Thread(target=self._run_scan, daemon=True)
        self._scan_thread.start()
        self._poll_timer.start(200)

    def _run_scan(self):
        position_scanner.scan_for_gui(self._stop_event, self._on_scan_progress)

    def _on_scan_progress(self, info):
        self._pending_info = info

    def _poll_updates(self):
        info = self._pending_info
        if info is None: return
        self._pending_info = None
        self._status_lbl.setText(info["status"])
        total = info["total_games"]; current = info["game_num"]
        if total > 0:
            self._progress.setMaximum(total); self._progress.setValue(current)
        if "counts" in info and info["counts"]:
            counts = info["counts"]; parts = []
            for i, r in enumerate(position_scanner.RANGES):
                if i in counts:
                    parts.append(f"{r['label']}: {counts[i]['w'] + counts[i]['b']}")
            if parts: self._counts_lbl.setText("  |  ".join(parts))
        if info.get("done"):
            self._start_btn.setEnabled(True); self._stop_btn.setEnabled(False)
            self._poll_timer.stop(); self._refresh_counts()

    def _stop_scan(self):
        self._stop_event.set()
        self._status_lbl.setText("Stopping... (saving progress)")
        self._stop_btn.setEnabled(False)

    def _back(self):
        if self._scan_thread and self._scan_thread.is_alive():
            self._stop_event.set()
            self._status_lbl.setText("Stopping scanner...")
            QTimer.singleShot(100, self._wait_and_close)
            return
        self._poll_timer.stop()
        self.finished.emit("back")

    def _wait_and_close(self):
        if self._scan_thread and self._scan_thread.is_alive():
            QTimer.singleShot(100, self._wait_and_close); return
        self._poll_timer.stop()
        self.finished.emit("back")


# ============================================================================
#  VARIATION WIDGET (for PGN Viewer)
# ============================================================================

class _VarPopup(QDialog):
    """ChessBase-style floating variation chooser dialog."""
    choice_made = pyqtSignal(int)
    dismissed = pyqtSignal()

    def __init__(self, choices, parent_node, parent=None):
        """choices = [(label, node_idx, is_main_line), ...]
        parent_node = the chess.pgn node whose variations we're choosing from"""
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._choices = choices
        self._parent_node = parent_node
        self._picked = False
        self._drag_pos = None

        self.setFixedWidth(360)
        self.setStyleSheet("""
            QDialog {
                background-color: #f5f5f5;
                border: 1px solid #cccccc;
                border-radius: 6px;
            }
        """)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setOffset(0, 4)
        shadow.setColor(QColor(0, 0, 0, 89))
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # Header row with title and close button
        hdr_widget = QWidget()
        hdr_widget.setStyleSheet("background-color: #eeeeee; border: none;")
        hdr_layout = QHBoxLayout(hdr_widget)
        hdr_layout.setContentsMargins(14, 10, 8, 10)
        hdr_layout.setSpacing(0)

        hdr = QLabel("Variations")
        hdr.setFont(QFont(_UI_FONT, 13, QFont.Weight.Medium))
        hdr.setStyleSheet("color: #333333; background: transparent;")
        hdr.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        hdr_layout.addWidget(hdr)
        hdr_layout.addStretch()

        close_btn = QPushButton("\u2715")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #888888;
                border: none; border-radius: 14px;
                font-size: 14px; font-weight: 400;
            }
            QPushButton:hover {
                background-color: #dddddd; color: #333333;
            }
        """)
        close_btn.clicked.connect(self.close)
        hdr_layout.addWidget(close_btn)
        lay.addWidget(hdr_widget)

        # Header bottom border
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background-color: #cccccc;")
        lay.addWidget(sep)

        # List widget
        self._listbox = QListWidget()
        self._listbox.setFont(QFont(_UI_FONT, 14, QFont.Weight.Normal))
        self._listbox.setStyleSheet("""
            QListWidget {
                background-color: #f5f5f5; color: #1a1a1a;
                border: none; outline: none;
            }
            QListWidget::item {
                padding: 0 16px; min-height: 44px;
                background-color: #f5f5f5; color: #1a1a1a;
            }
            QListWidget::item:hover {
                background-color: #e8e8e8; color: #000000;
            }
            QListWidget::item:selected {
                background-color: #3a6fd8; color: #ffffff;
            }
            QScrollBar:vertical {
                background: #f0f0f0; width: 8px; margin: 0;
                border: none;
            }
            QScrollBar::handle:vertical {
                background: #c0c0c0; min-height: 30px;
                border-radius: 4px;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0; border: none;
            }
        """)
        for label, node_idx, is_main in choices:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, node_idx)
            self._listbox.addItem(item)

        item_h = 44
        visible = min(len(choices), 10)
        self._listbox.setFixedHeight(visible * item_h + 4)
        self._listbox.setCurrentRow(0)
        self._listbox.doubleClicked.connect(self._confirm_selection)
        lay.addWidget(self._listbox)

        # Button separator
        btn_sep = QFrame()
        btn_sep.setFixedHeight(1)
        btn_sep.setStyleSheet("background-color: #cccccc;")
        lay.addWidget(btn_sep)

        # Buttons row
        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(8, 8, 8, 8)
        btn_row.setSpacing(6)

        _btn_ss = """
            QPushButton {
                background-color: #ebebeb; color: #333333;
                border: 1px solid #c0c0c0;
                border-radius: 4px; padding: 0 12px; font-size: 13px;
            }
            QPushButton:hover {
                background-color: #dcdcdc;
            }
        """

        btn_up = QPushButton("Move Up")
        btn_up.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn_up.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_up.setFixedHeight(38)
        btn_up.setStyleSheet(_btn_ss)
        btn_up.clicked.connect(self._move_var_up)
        btn_row.addWidget(btn_up)

        btn_down = QPushButton("Move Down")
        btn_down.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn_down.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_down.setFixedHeight(38)
        btn_down.setStyleSheet(_btn_ss)
        btn_down.clicked.connect(self._move_var_down)
        btn_row.addWidget(btn_down)

        lay.addLayout(btn_row)

        self.adjustSize()

    @staticmethod
    def _accent_rgb():
        """Extract r,g,b from accent_border for rgba() usage."""
        # accent_border is like "rgba(147,197,253,0.28)" — extract the rgb part
        s = T['accent_border']
        if s.startswith("rgba("):
            inner = s[5:s.rindex(")")]
            parts = inner.split(",")
            if len(parts) >= 3:
                return ",".join(parts[:3]).strip()
        return "180,215,255"

    def _confirm_selection(self):
        row = self._listbox.currentRow()
        if 0 <= row < len(self._choices):
            _, node_idx, _ = self._choices[row]
            if node_idx is not None:
                self._picked = True
                self.choice_made.emit(node_idx)
                self.close()

    def _move_var_up(self):
        """Swap selected variation with the one above it in the PGN tree."""
        row = self._listbox.currentRow()
        if row <= 0 or not self._parent_node: return
        variations = self._parent_node.variations
        if row < len(variations):
            variations[row - 1], variations[row] = variations[row], variations[row - 1]
            # Update the list display
            label_above = self._choices[row - 1][0]
            label_current = self._choices[row][0]
            self._choices[row - 1], self._choices[row] = self._choices[row], self._choices[row - 1]
            self._listbox.item(row - 1).setText(self._choices[row - 1][0])
            self._listbox.item(row).setText(self._choices[row][0])
            self._listbox.setCurrentRow(row - 1)

    def _move_var_down(self):
        """Swap selected variation with the one below it in the PGN tree."""
        row = self._listbox.currentRow()
        if row < 0 or not self._parent_node: return
        variations = self._parent_node.variations
        if row >= len(variations) - 1: return
        variations[row], variations[row + 1] = variations[row + 1], variations[row]
        self._choices[row], self._choices[row + 1] = self._choices[row + 1], self._choices[row]
        self._listbox.item(row).setText(self._choices[row][0])
        self._listbox.item(row + 1).setText(self._choices[row + 1][0])
        self._listbox.setCurrentRow(row + 1)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._confirm_selection()
        elif key in (Qt.Key.Key_Escape, Qt.Key.Key_Left):
            self.close()
        elif key == Qt.Key.Key_Up:
            row = self._listbox.currentRow()
            if row > 0: self._listbox.setCurrentRow(row - 1)
        elif key == Qt.Key.Key_Down:
            row = self._listbox.currentRow()
            if row < self._listbox.count() - 1: self._listbox.setCurrentRow(row + 1)
        elif key == Qt.Key.Key_Right:
            self._confirm_selection()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton and self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def closeEvent(self, event):
        # Save position to config
        try:
            cfg = _load_config()
            cfg["variation_popup_position"] = {"x": self.x(), "y": self.y()}
            _save_config(cfg)
        except Exception:
            pass
        if not self._picked:
            self.dismissed.emit()
        super().closeEvent(event)



# ============================================================================
#  PGN VIEWER PAGE
# ============================================================================

class PGNViewerPage(QWidget):
    finished = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {T['bg']}; border: none;")
        self.board = chess.Board()
        self.flipped = False
        self.games = []
        self.current_game = None
        self.move_nodes = []
        self.current_idx = -1
        self._start_board = chess.Board()
        self._move_tag_map = {}
        self._var_popup = None
        self._build_ui()

    def _pgn_btn(self, text, height=44):
        """Create a fluffy PGN viewer button matching the design system."""
        btn = QPushButton(text)
        btn.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedHeight(height)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['btn_bg']}; color: {T['btn_text']};
                border: 1px solid {T['btn_border']}; border-radius: 10px;
                padding: 0 16px;
            }}
            QPushButton:hover {{
                background-color: {T['accent_bg']}; border-color: {T['accent_border']};
                color: {T['title']};
            }}
            QPushButton:pressed {{
                background-color: {T['accent_bg']}; color: {T['title']};
            }}
        """)
        _add_press_anim(btn)
        return btn

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.board_widget = BoardWidget()
        self.board_widget.piece_imgs = load_piece_pixmaps(SQ)
        self.board_widget.board = self.board
        layout.addWidget(self.board_widget, 1)

        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {T['bg']};
                border-left: 1px solid {T['section_border']};
            }}
            {_frost_scrollbar_ss()}
        """)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(14, 12, 14, 12)
        pl.setSpacing(8)

        # Load PGN button — full width, accent style like Start Game
        btn_load = QPushButton("Load PGN")
        btn_load.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn_load.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_load.setFixedHeight(52)
        btn_load.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['accent_bg']}; color: {T['accent_text']};
                border: 1px solid {T['accent_border']}; border-radius: 13px;
                padding: 0 20px;
            }}
            QPushButton:hover {{
                background-color: {T['accent_border']}; color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: {T['accent_border']}; }}
        """)
        _add_press_anim(btn_load)
        btn_load.clicked.connect(lambda: (play_menu_click(), self._load_pgn()))
        pl.addWidget(btn_load)

        # Games panel toggle row
        games_hdr_row = QHBoxLayout()
        games_hdr_row.setContentsMargins(0, 0, 0, 0)
        games_hdr_row.addWidget(_section_label("GAMES"))
        self._games_toggle_btn = QPushButton("Hide")
        self._games_toggle_btn.setFont(QFont(_UI_FONT, 10, QFont.Weight.Normal))
        self._games_toggle_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._games_toggle_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: rgba({_hex_to_rgb(T['accent_text'])}, 0.5);
                font-size: 10px; letter-spacing: 1px;
                padding: 0 4px;
            }}
            QPushButton:hover {{
                color: rgba({_hex_to_rgb(T['accent_text'])}, 0.85);
            }}
        """)
        self._games_toggle_btn.clicked.connect(self._toggle_games_panel)
        games_hdr_row.addWidget(self._games_toggle_btn)
        pl.addLayout(games_hdr_row)

        # Game selector (section card style)
        self.game_sel_frame = QFrame()
        self.game_sel_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 13px;
            }}
        """)
        gsl = QVBoxLayout(self.game_sel_frame)
        gsl.setContentsMargins(18, 16, 18, 16)
        gsl.setSpacing(6)
        self.game_listbox = QListWidget()
        self.game_listbox.setStyleSheet(f"""
            QListWidget {{
                background-color: transparent; color: {T['title']};
                border: none;
            }}
            QListWidget::item {{
                padding: 4px 8px; min-height: 24px;
            }}
            QListWidget::item:selected {{
                background-color: {T['accent_bg']}; color: {T['accent_text']};
            }}
            {_frost_scrollbar_ss()}
        """)
        self.game_listbox.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.game_listbox.setMaximumHeight(160)
        self.game_listbox.currentRowChanged.connect(self._on_game_select)
        gsl.addWidget(self.game_listbox)
        self.game_sel_frame.hide()
        pl.addWidget(self.game_sel_frame)

        # Header (section card style)
        self.hdr_frame = QFrame()
        self.hdr_frame.setStyleSheet(f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 13px;
            }}
        """)
        hfl = QVBoxLayout(self.hdr_frame)
        hfl.setContentsMargins(18, 16, 18, 16)
        hfl.setSpacing(4)
        self.hdr_labels = {}
        for key in ["White", "Black", "Event", "Date", "Result"]:
            row = QHBoxLayout()
            klbl = QLabel(f"{key}:")
            klbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
            klbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none;")
            row.addWidget(klbl)
            lbl = QLabel("")
            lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
            lbl.setStyleSheet(f"color: {T['title']}; background: transparent; border: none;")
            row.addWidget(lbl, 1)
            hfl.addLayout(row)
            self.hdr_labels[key] = lbl
        pl.addWidget(self.hdr_frame)

        # Notation (section card style)
        pl.addWidget(_section_label("NOTATION"))

        self.notation_browser = QTextBrowser()
        self.notation_browser.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {T['bg']}; color: {T['text_primary']};
                border: none; padding: 6px;
            }}
            {_frost_scrollbar_ss()}
        """)
        self.notation_browser.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.notation_browser.setReadOnly(True)
        self.notation_browser.setOpenLinks(False)
        self.notation_browser.anchorClicked.connect(self._on_notation_click)
        pl.addWidget(self.notation_browser, 1)

        # Navigation buttons — use text-style glyphs that always respect CSS color
        nav_row = QHBoxLayout(); nav_row.setSpacing(4)
        btn_start = self._pgn_btn("\u25C2\u25C2")
        btn_start.clicked.connect(lambda: (play_menu_click(), self._goto_start()))
        nav_row.addWidget(btn_start)
        btn_prev = self._pgn_btn("\u25C2")
        btn_prev.clicked.connect(lambda: (play_menu_click(), self._on_left()))
        nav_row.addWidget(btn_prev)
        btn_next = self._pgn_btn("\u25B8")
        btn_next.clicked.connect(lambda: (play_menu_click(), self._on_right()))
        nav_row.addWidget(btn_next)
        btn_end = self._pgn_btn("\u25B8\u25B8")
        btn_end.clicked.connect(lambda: (play_menu_click(), self._goto_end()))
        nav_row.addWidget(btn_end)
        pl.addLayout(nav_row)

        r1 = QHBoxLayout(); r1.setSpacing(4)
        btn_flip = self._pgn_btn("Flip Board")
        btn_flip.clicked.connect(lambda: (play_menu_click(), self._flip()))
        r1.addWidget(btn_flip)
        btn_back = self._pgn_btn("Back to Menu")
        btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        r1.addWidget(btn_back)
        pl.addLayout(r1)

        layout.addWidget(panel)

        # Restore games panel hidden state
        cfg = _load_config()
        self._games_panel_hidden = cfg.get("games_panel_hidden", False)
        if self._games_panel_hidden:
            self.game_sel_frame.hide()
            self.hdr_frame.hide()
            self._games_toggle_btn.setText("Show Games")

        QShortcut(QKeySequence(Qt.Key.Key_Left), self).activated.connect(self._on_left)
        QShortcut(QKeySequence(Qt.Key.Key_Right), self).activated.connect(self._on_right)
        QShortcut(QKeySequence(Qt.Key.Key_Home), self).activated.connect(self._goto_start)
        QShortcut(QKeySequence(Qt.Key.Key_End), self).activated.connect(self._goto_end)
        QShortcut(QKeySequence(Qt.Key.Key_Up), self).activated.connect(self._on_up)
        QShortcut(QKeySequence(Qt.Key.Key_Down), self).activated.connect(self._on_down)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self).activated.connect(self._on_enter)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self._on_escape)

    def _toggle_games_panel(self):
        hiding = not self._games_panel_hidden
        self._games_panel_hidden = hiding
        if hiding:
            self.game_sel_frame.hide()
            self.hdr_frame.hide()
            self._games_toggle_btn.setText("Show Games")
        else:
            # Only show game_sel_frame if multiple games loaded
            if len(self.games) > 1:
                self.game_sel_frame.show()
            self.hdr_frame.show()
            self._games_toggle_btn.setText("Hide")
        cfg = _load_config()
        cfg["games_panel_hidden"] = hiding
        _save_config(cfg)

    def _sync_board(self):
        self.board_widget.board = self.board
        self.board_widget.flipped = self.flipped
        self.board_widget.update()

    def _load_pgn(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select PGN File", "",
            "PGN files (*.pgn);;All files (*.*)")
        if not path: return
        self.games = []
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                while True:
                    game = chess.pgn.read_game(f)
                    if game is None: break
                    self.games.append(game)
        except Exception as e:
            _ot_logger.error("PGN load error for %s: %s", path, e)
            print(f"PGN load error: {e}")
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "PGN Error",
                f"Could not read the PGN file.\n\n{e}")
            return
        if not self.games:
            from PyQt6.QtWidgets import QMessageBox
            QMessageBox.information(self, "Empty PGN",
                "The PGN file contains no games.")
            return
        if len(self.games) > 1:
            if not self._games_panel_hidden:
                self.game_sel_frame.show()
            self.game_listbox.clear()
            for i, g in enumerate(self.games):
                h = g.headers
                self.game_listbox.addItem(
                    f"{i+1}. {h.get('White','?')} vs {h.get('Black','?')}  {h.get('Result','*')}")
            self.game_listbox.setCurrentRow(0)
            self.game_listbox.setMaximumHeight(min(6, len(self.games)) * 32 + 8)
        else:
            self.game_sel_frame.hide()
        self._select_game(0)

    def _on_game_select(self, row):
        if row >= 0: self._select_game(row)

    def _select_game(self, idx):
        if idx < 0 or idx >= len(self.games): return
        self.current_game = self.games[idx]
        h = self.current_game.headers
        for key in ["White", "Black", "Event", "Date", "Result"]:
            self.hdr_labels[key].setText(h.get(key, "?"))
        self.current_idx = -1
        self.board = chess.Board()
        if self.current_game.headers.get("FEN"):
            try: self.board = chess.Board(self.current_game.headers["FEN"])
            except: pass
        self._start_board = self.board.copy()
        self.move_nodes = []
        self._flatten_nodes(self.current_game)
        self._render_notation()
        self._sync_board()
        self._dismiss_var_popup()

    def _flatten_nodes(self, game_node):
        self.move_nodes = []
        board = self._start_board.copy()
        self._walk_tree(game_node, board, 0)

    def _walk_tree(self, parent, board, depth):
        if not parent.variations: return
        main_child = parent.variations[0]
        board_before = board.copy()
        self.move_nodes.append((main_child, board_before, depth, False))
        board.push(main_child.move)
        for alt in parent.variations[1:]:
            alt_board = board_before.copy()
            self.move_nodes.append((alt, alt_board, depth + 1, True))
            alt_after = alt_board.copy()
            alt_after.push(alt.move)
            self._walk_tree(alt, alt_after, depth + 1)
        self._walk_tree(main_child, board, depth)

    def _render_notation(self):
        self._move_tag_map = {}
        if not self.current_game:
            self.notation_browser.setHtml(""); return
        parts = [f'<div style="font-family: {_UI_FONT}, sans-serif; font-size: 13pt; '
                 f'color: {T["text_primary"]}; line-height: 1.9;">']
        self._render_node_html(self.current_game, self._start_board.copy(), 0, True, parts)
        result = self.current_game.headers.get("Result", "*")
        if result and result != "*":
            parts.append(f'<span style="color: {T["accent_text"]};"> {result}</span>')
        parts.append('</div>')
        self.notation_browser.setHtml("".join(parts))

    def _render_node_html(self, parent_node, board, depth, need_movenum, parts):
        if not parent_node.variations: return
        main_child = parent_node.variations[0]
        node_idx = self._find_node_idx(main_child)
        if board.turn == chess.WHITE or need_movenum:
            mn = board.fullmove_number
            ms = f"{mn}." if board.turn == chess.WHITE else f"{mn}..."
            parts.append(f'<span style="color: {T["text_muted"]}; font-size: 11pt; font-weight: 300;">{ms}</span>')
        self._insert_move_html(main_child, board, node_idx, depth, parts)
        next_board = board.copy(); next_board.push(main_child.move)
        for alt in parent_node.variations[1:]:
            alt_idx = self._find_node_idx(alt)
            vd = depth + 1
            parts.append(f'<br><span style="color: {T["section_border"]};">[ </span>')
            mn = board.fullmove_number
            ms = f"{mn}." if board.turn == chess.WHITE else f"{mn}..."
            parts.append(f'<span style="color: {T["text_muted"]}; font-size: 11pt; font-weight: 300;">{ms}</span>')
            self._insert_move_html(alt, board, alt_idx, vd, parts)
            ab = board.copy(); ab.push(alt.move)
            self._render_node_html(alt, ab, vd, False, parts)
            parts.append(f'<span style="color: {T["section_border"]};">] </span>')
        self._render_node_html(main_child, next_board, depth, False, parts)

    def _find_node_idx(self, node):
        for i, (mn, mb, md, mv) in enumerate(self.move_nodes):
            if mn is node: return i
        return None

    def _insert_move_html(self, child, board, node_idx, depth, parts):
        san = board.san(child.move)
        nag_str = ""
        nag_symbols = {1:"!",2:"?",3:"!!",4:"??",5:"!?",6:"?!",10:"=",13:"\u221e",
                       14:"+=",15:"=+",16:"+/-",17:"-/+",18:"+-",19:"-+"}
        for nag in child.nags:
            nag_str += nag_symbols.get(nag, f"${nag}")
        if node_idx is not None:
            self._move_tag_map[node_idx] = node_idx
            is_cur = (self.current_idx == node_idx)
            if is_cur:
                color = T['accent_text']; bg = T['accent_bg']; weight = "normal"
            elif depth == 0:
                color = T['text_primary']; bg = "transparent"; weight = "normal"
            else:
                color = T['text_muted']; bg = "transparent"; weight = "normal"
            parts.append(
                f'<a href="move:{node_idx}" style="color: {color}; background-color: {bg}; '
                f'font-weight: {weight}; text-decoration: none;">{san}</a>')
        else:
            mc = T['text_primary'] if depth == 0 else T['text_muted']
            parts.append(f'<span style="color: {mc};">{san}</span>')
        if nag_str:
            parts.append(f'<span style="color: {T["text_primary"]};">{nag_str}</span>')
        parts.append(' ')
        if child.comment:
            parts.append(f'<span style="color: {T["text_muted"]}; font-style: italic;">'
                         f'{{{child.comment}}}</span> ')

    def _on_notation_click(self, url: QUrl):
        text = url.toString()
        if text.startswith("move:"):
            try: self._goto_move(int(text.split(":")[1]))
            except: pass

    def _goto_move(self, idx):
        if idx < 0 or idx >= len(self.move_nodes): return
        self._dismiss_var_popup()
        node, board_before, depth, is_var = self.move_nodes[idx]
        self.board = board_before.copy()
        self.board.push(node.move)
        play_move_sound()
        self.current_idx = idx
        self._render_notation()
        self._sync_board()

    def _goto_start(self):
        self.board = self._start_board.copy()
        self.current_idx = -1
        self._render_notation()
        self._sync_board()
        self._dismiss_var_popup()

    def _goto_end(self):
        last_main = -1
        for i, (node, bb, depth, iv) in enumerate(self.move_nodes):
            if depth == 0: last_main = i
        if last_main >= 0: self._goto_move(last_main)

    def _on_left(self):
        self._dismiss_var_popup()
        if self.current_idx < 0: return

        # Get the move being undone
        node, board_before, depth, is_var = self.move_nodes[self.current_idx]

        # Find target index (parent move, or -1 for start)
        target_idx = -1
        if self.current_idx > 0:
            found = False
            if node.parent is not None:
                for i, (mn, mb, md, mv2) in enumerate(self.move_nodes):
                    if mn is node.parent:
                        target_idx = i
                        found = True
                        break
            if not found:
                target_idx = self.current_idx - 1

        self.board = board_before.copy()
        play_move_sound()
        self.current_idx = target_idx
        self._render_notation()
        self._sync_board()

    def _on_right(self):
        # If popup is open, confirm current selection
        if self._var_popup is not None:
            self._var_popup_confirm()
            return
        if not self.move_nodes: return
        if self.current_idx < 0:
            parent_node = self.current_game if self.current_game else None
        else:
            parent_node = self.move_nodes[self.current_idx][0]
        if parent_node is None or not parent_node.variations: return
        if len(parent_node.variations) == 1:
            # Single continuation — advance directly
            child = parent_node.variations[0]
            idx = self._find_node_idx(child)
            if idx is not None: self._goto_move(idx)
        else:
            # Multiple continuations — show popup
            self._show_var_popup(parent_node)

    # -- Variation popup management --

    def _build_var_choices(self, parent_node):
        """Build choices list for the variation popup."""
        if self.current_idx < 0:
            board = self._start_board.copy()
        else:
            node, board_before, _, _ = self.move_nodes[self.current_idx]
            board = board_before.copy()
            board.push(node.move)
        choices = []
        mn_num = board.fullmove_number
        for i, child in enumerate(parent_node.variations):
            san = board.san(child.move)
            # Add NAG symbols
            nag_symbols = {1:"!",2:"?",3:"!!",4:"??",5:"!?",6:"?!"}
            nag_str = ""
            for nag in child.nags:
                nag_str += nag_symbols.get(nag, "")
            if board.turn == chess.WHITE:
                label = f"{mn_num}. {san}{nag_str}"
            else:
                label = f"{mn_num}...{san}{nag_str}"
            idx = self._find_node_idx(child)
            choices.append((label, idx, i == 0))
        return choices

    def _show_var_popup(self, parent_node):
        self._dismiss_var_popup()
        choices = self._build_var_choices(parent_node)
        if not choices or len(choices) <= 1: return

        popup = _VarPopup(choices, parent_node, self)
        popup.choice_made.connect(self._on_var_popup_choice)
        popup.dismissed.connect(self._on_var_popup_dismissed)
        popup.adjustSize()

        # Restore saved position or center on window
        restored = False
        try:
            cfg = _load_config()
            pos = cfg.get("variation_popup_position")
            if pos and isinstance(pos, dict):
                x, y = pos.get("x", 0), pos.get("y", 0)
                screen = self.screen()
                if screen:
                    sg = screen.availableGeometry()
                    pw, ph = popup.width(), popup.height()
                    if (sg.left() <= x <= sg.right() - pw and
                            sg.top() <= y <= sg.bottom() - ph):
                        popup.move(x, y)
                        restored = True
        except Exception:
            pass

        if not restored:
            center = self.mapToGlobal(QPoint(self.width() // 2, self.height() // 2))
            popup.move(center.x() - popup.width() // 2, center.y() - popup.height() // 2)

        popup.show()
        popup.setFocus()
        self._var_popup = popup

    def _on_var_popup_choice(self, node_idx):
        self._var_popup = None
        if node_idx is not None and node_idx >= 0:
            self._goto_move(node_idx)

    def _on_var_popup_dismissed(self):
        self._var_popup = None

    def _var_popup_confirm(self):
        if self._var_popup is not None:
            self._var_popup._confirm_selection()

    def _dismiss_var_popup(self):
        if self._var_popup is not None:
            self._var_popup.close()
            self._var_popup = None

    def _on_up(self): pass
    def _on_down(self): pass
    def _on_enter(self): pass
    def _on_escape(self): self._dismiss_var_popup()

    def _flip(self):
        self.flipped = not self.flipped
        self._sync_board()


# ============================================================================
#  ERROR PAGE
# ============================================================================

class ErrorPage(FrostBackground):
    finished = pyqtSignal(str)

    def __init__(self, message, detail="", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch()
        hc = QHBoxLayout(); hc.addStretch()
        inner = QVBoxLayout()
        inner.setSpacing(8)
        inner.addWidget(_make_label(message, 14, ERROR_CLR))
        if detail:
            inner.addWidget(_make_label(detail, 11, T['title']))
        inner.addWidget(_make_label("Download: stockfishchess.org/download", 11, T['accent_text']))
        btn = _make_button("Back to Menu", 12, min_height=36)
        btn.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        inner.addSpacing(10)
        inner.addWidget(btn)
        hc.addLayout(inner); hc.addStretch()
        outer.addLayout(hc); outer.addStretch()


# ============================================================================
#  OPENING TRAINER SETUP PAGE
# ============================================================================

class OpeningTrainerSetupPage(FrostBackground):
    finished = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._color = "white"
        self._pgn_path = None
        self._pgn_games = []        # list of game header dicts
        self._selected_game = None  # index into _pgn_games (or None)
        self._game_row_widgets = [] # list of row QFrames for selection
        self._build_ui()

    def _make_section_card(self):
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {T['section_bg']};
                border: 1px solid {T['section_border']};
                border-radius: 13px;
            }}
        """)
        return card

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        hc = QHBoxLayout(); hc.addStretch()

        inner = QVBoxLayout()
        inner.setSpacing(10)
        inner.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = _make_label("ChessGym", 28, T['title'])
        title.setFont(QFont(_UI_FONT, 28, QFont.Weight.Light))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(title)

        sec = _section_label("OPENING TRAINER")
        sec.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(sec)
        inner.addSpacing(8)

        # Resume banner (if paused session exists)
        self._resume_banner = None
        saved = _load_config().get("opening_trainer_session")
        if saved and saved.get("paused_at") and saved.get("pgn_path"):
            pgn_path = saved["pgn_path"]
            if os.path.isfile(pgn_path):
                banner = QFrame()
                banner.setStyleSheet(f"""
                    QFrame {{
                        background-color: {T['section_bg']};
                        border: 1px solid {T['section_border']};
                        border-radius: 10px;
                    }}
                """)
                bl = QVBoxLayout(banner)
                bl.setContentsMargins(16, 12, 16, 12)
                bl.setSpacing(4)

                b_title = QLabel("Unfinished session found")
                b_title.setFont(QFont(_UI_FONT, 12, QFont.Weight.Normal))
                b_title.setStyleSheet(f"color: {T['title']}; background: transparent; border: none;")
                bl.addWidget(b_title)

                mc = saved.get("moves_completed", 0)
                tu = saved.get("total_user_moves", 0)
                sc = saved.get("score_correct", 0)
                sw = saved.get("score_wrong", 0)
                _sl = T['section_label']
                _tm = T['text_muted']
                b_sub = QLabel(
                    f"<span style='color:{_tm}'>Move {mc} / {tu}  \u00b7  </span>"
                    f"<span style='color:{_sl}'>CORRECT: {sc}</span>"
                    f"<span style='color:{_tm}'> \u00b7 </span>"
                    f"<span style='color:{_sl}'>WRONG: {sw}</span>"
                )
                b_sub.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
                b_sub.setStyleSheet("background: transparent; border: none;")
                bl.addWidget(b_sub)
                bl.addSpacing(6)

                btn_row = QHBoxLayout()
                btn_row.setSpacing(8)
                btn_resume = _make_button("Resume  \u2192", 12, min_height=36, accent=True)
                _add_press_anim(btn_resume)
                btn_resume.clicked.connect(lambda: self._resume_session(saved))
                btn_row.addWidget(btn_resume)
                btn_discard = _make_button("Discard", 12, min_height=36)
                _add_press_anim(btn_discard)
                btn_discard.clicked.connect(self._discard_session)
                btn_row.addWidget(btn_discard)
                bl.addLayout(btn_row)

                inner.addWidget(banner)
                inner.addSpacing(4)
                self._resume_banner = banner
                self._saved_session = saved

        # 1. REPERTOIRE FILE
        card1 = self._make_section_card()
        cl1 = QVBoxLayout(card1)
        cl1.setContentsMargins(18, 16, 18, 16)
        cl1.setSpacing(10)
        cl1.addWidget(_section_label("REPERTOIRE FILE"))
        file_row = QHBoxLayout(); file_row.setSpacing(8)
        self._file_lbl = QLabel("(none)")
        self._file_lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Light))
        self._file_lbl.setFixedHeight(40)
        self._file_lbl.setMinimumWidth(140)
        self._file_lbl.setStyleSheet(f"""
            QLabel {{
                background-color: {T['book_bg']}; color: {T['book_text']};
                border: 1px solid {T['book_border']}; border-radius: 10px;
                padding: 0 12px; font-size: 13px;
            }}
        """)
        file_row.addWidget(self._file_lbl, 1)
        btn_browse = QPushButton("Browse")
        btn_browse.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn_browse.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_browse.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['book_btn_bg']}; color: {T['book_btn_text']};
                border: 1px solid {T['book_btn_border']}; border-radius: 10px;
                padding: 0 14px; min-height: 40px; max-height: 40px; font-size: 13px;
            }}
            QPushButton:hover {{
                background-color: {T['accent_bg']}; border-color: {T['accent_border']};
                color: {T['title']};
            }}
        """)
        _add_press_anim(btn_browse)
        btn_browse.clicked.connect(lambda: (play_menu_click(), self._browse()))
        file_row.addWidget(btn_browse)
        btn_clear = QPushButton("Clear")
        btn_clear.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn_clear.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_clear.setStyleSheet(btn_browse.styleSheet())
        _add_press_anim(btn_clear)
        btn_clear.clicked.connect(lambda: (play_menu_click(), self._clear()))
        file_row.addWidget(btn_clear)
        cl1.addLayout(file_row)

        self._ot_empty_hint = QLabel("Load a PGN file to begin training")
        self._ot_empty_hint.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
        self._ot_empty_hint.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
        self._ot_empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl1.addWidget(self._ot_empty_hint)

        inner.addWidget(card1)

        # --- GAME SELECTOR (hidden until a multi-game PGN is loaded) ---
        self._game_selector_card = QFrame()
        self._game_selector_card.setVisible(False)
        gs_lay = QVBoxLayout(self._game_selector_card)
        gs_lay.setContentsMargins(18, 16, 18, 16)
        gs_lay.setSpacing(0)

        gs_label = QLabel("SELECT GAME")
        gs_label.setFont(QFont(_UI_FONT, 9, QFont.Weight.Normal))
        gs_label.setStyleSheet(
            f"color: {T['section_label']}; background: transparent; "
            "letter-spacing: 2px;"
        )
        gs_lay.addWidget(gs_label)
        gs_lay.addSpacing(10)

        # Search field (shown only when >= 10 games)
        self._game_search = QLineEdit()
        self._game_search.setPlaceholderText("Search by player or opening...")
        self._game_search.setFont(QFont(_UI_FONT, 13))
        self._game_search.setFixedHeight(38)
        self._game_search.setVisible(False)
        self._game_search.textChanged.connect(self._filter_games)
        gs_lay.addWidget(self._game_search)

        # Spacer below search (only visible when search is visible)
        self._search_spacer = QWidget()
        self._search_spacer.setFixedHeight(10)
        self._search_spacer.setVisible(False)
        gs_lay.addWidget(self._search_spacer)

        # Scrollable game list
        self._game_scroll = QScrollArea()
        self._game_scroll.setWidgetResizable(True)
        self._game_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._game_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._game_scroll.setMinimumHeight(220)
        self._game_scroll.setMaximumHeight(320)

        self._game_list_widget = QWidget()
        self._game_list_layout = QVBoxLayout(self._game_list_widget)
        self._game_list_layout.setContentsMargins(0, 0, 0, 0)
        self._game_list_layout.setSpacing(0)
        self._game_scroll.setWidget(self._game_list_widget)
        gs_lay.addWidget(self._game_scroll)

        inner.addWidget(self._game_selector_card)

        # 2. PLAY AS
        card2 = self._make_section_card()
        cl2 = QVBoxLayout(card2)
        cl2.setContentsMargins(18, 16, 18, 16)
        cl2.setSpacing(12)
        cl2.addWidget(_section_label("PLAY AS"))
        cr = QHBoxLayout(); cr.setSpacing(12)
        self._btn_white = ToggleButton("WHITE", active=True)
        self._btn_white.setMinimumWidth(180)
        self._btn_white.clicked.connect(lambda: (play_menu_click(), self._pick_color("white")))
        _add_press_anim(self._btn_white)
        cr.addWidget(self._btn_white)
        self._btn_black = ToggleButton("BLACK", active=False)
        self._btn_black.setMinimumWidth(180)
        self._btn_black.clicked.connect(lambda: (play_menu_click(), self._pick_color("black")))
        _add_press_anim(self._btn_black)
        cr.addWidget(self._btn_black)
        cl2.addLayout(cr)
        inner.addWidget(card2)

        inner.addSpacing(12)
        self._btn_start = _make_button("Start Training  \u2192", 14, min_height=52, min_width=320, accent=True)
        self._btn_start.setStyleSheet(self._btn_start.styleSheet().replace("border-radius: 12px", "border-radius: 13px"))
        self._btn_start.clicked.connect(lambda: (play_menu_click(), self._start()))
        _add_press_anim(self._btn_start)
        inner.addWidget(self._btn_start, alignment=Qt.AlignmentFlag.AlignCenter)

        # Selected game info label (below button)
        self._sel_info_lbl = QLabel("")
        self._sel_info_lbl.setFont(QFont(_UI_FONT, 10))
        self._sel_info_lbl.setStyleSheet(
            f"color: {T['text_muted']}; background: transparent;")
        self._sel_info_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._sel_info_lbl.setVisible(False)
        inner.addWidget(self._sel_info_lbl, alignment=Qt.AlignmentFlag.AlignCenter)

        btn_back = QPushButton("Back to Menu")
        btn_back.setFont(QFont(_UI_FONT, 12, QFont.Weight.Light))
        btn_back.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn_back.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {T['section_label']};
                border: none; padding: 8px 20px; min-height: 36px;
            }}
            QPushButton:hover {{ color: {T['text_primary']}; }}
        """)
        btn_back.clicked.connect(lambda: (play_menu_click(), self.finished.emit("back")))
        _add_press_anim(btn_back)
        inner.addWidget(btn_back, alignment=Qt.AlignmentFlag.AlignCenter)

        hc.addLayout(inner); hc.addStretch()
        outer.addLayout(hc); outer.addStretch(2)

    # ---- theming helpers for game selector ----

    def _gs_card_ss(self):
        rgb = _accent_rgb()
        return f"""
            QFrame {{
                background-color: rgba({rgb},0.05);
                border: 1px solid rgba({rgb},0.12);
                border-radius: 13px;
            }}
        """

    def _gs_search_ss(self):
        rgb = _accent_rgb()
        return f"""
            QLineEdit {{
                background-color: {T['book_bg']}; color: {T['text_primary']};
                border: 1px solid rgba({rgb},0.12); border-radius: 9px;
                padding: 0 12px; font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {T['accent_border']};
            }}
        """

    def _gs_scroll_ss(self):
        rgb = _accent_rgb()
        sb = T.get('scrollbar', 'rgba(255,255,255,0.08)')
        sbh = T.get('scrollbar_hover', 'rgba(255,255,255,0.15)')
        return f"""
            QScrollArea {{ background: transparent; border: none; }}
            QWidget {{ background: transparent; }}
            QScrollBar:vertical {{
                background: transparent; width: 6px; margin: 0; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {sb}; min-height: 24px; border-radius: 3px;
            }}
            QScrollBar::handle:vertical:hover {{ background: {sbh}; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; background: none;
            }}
        """

    def _apply_game_selector_styles(self):
        """Apply / refresh styles on the game selector card."""
        self._game_selector_card.setStyleSheet(self._gs_card_ss())
        self._game_search.setStyleSheet(self._gs_search_ss())
        self._game_scroll.setStyleSheet(self._gs_scroll_ss())

    # ---- start button state ----

    def _set_start_enabled(self, enabled):
        """Toggle start button between active and muted state."""
        if enabled:
            # Restore accent styling
            ss = self._btn_start.styleSheet()
            # just ensure opacity is full
            self._btn_start.setEnabled(True)
            self._btn_start.setStyleSheet(ss.replace("opacity: 0.4;", ""))
        else:
            self._btn_start.setEnabled(False)

    # ---- populate game list ----

    def _populate_games(self):
        """Build game rows from self._pgn_games."""
        # Clear old rows
        for w in self._game_row_widgets:
            w.setParent(None)
            w.deleteLater()
        self._game_row_widgets.clear()
        self._selected_game = None
        self._sel_info_lbl.setVisible(False)

        rgb = _accent_rgb()

        for g in self._pgn_games:
            idx = g["index"]
            white = g["white"]
            black = g["black"]
            opening = g["opening"]
            num = idx + 1

            row = QFrame()
            row.setFixedHeight(46)
            row.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            row.setProperty("game_index", idx)

            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(14, 0, 14, 0)
            row_lay.setSpacing(8)

            left_text = f"{num}. {white} vs {black}"
            left_lbl = QLabel(left_text)
            left_lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
            left_lbl.setStyleSheet(f"color: {T['text_primary']}; background: transparent;")
            row_lay.addWidget(left_lbl, 1)

            if opening:
                right_lbl = QLabel(opening)
                right_lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
                right_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
                right_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                row_lay.addWidget(right_lbl, 0)

            # Normal row style
            normal_ss = f"""
                QFrame {{
                    background-color: rgba({rgb},0.05);
                    border: none;
                    border-bottom: 1px solid rgba({rgb},0.08);
                    border-radius: 0px;
                }}
                QFrame:hover {{
                    background-color: rgba({rgb},0.1);
                }}
            """
            row.setStyleSheet(normal_ss)
            row.setProperty("normal_ss", normal_ss)

            # store refs for label recoloring on selection
            row.setProperty("left_lbl", left_lbl)
            row.setProperty("opening", opening)
            row.setProperty("white", white)
            row.setProperty("black", black)

            row.mousePressEvent = lambda e, r=row: self._select_game_row(r)
            self._game_list_layout.addWidget(row)
            self._game_row_widgets.append(row)

        self._game_list_layout.addStretch()

        # Show search if >= 10 games
        show_search = len(self._pgn_games) >= 10
        self._game_search.setVisible(show_search)
        self._search_spacer.setVisible(show_search)
        self._game_search.clear()

        self._apply_game_selector_styles()

        # Disable start until a game is selected
        if len(self._pgn_games) > 1:
            self._set_start_enabled(False)

    def _select_game_row(self, row):
        """Handle click on a game row."""
        play_menu_click()
        idx = row.property("game_index")
        self._selected_game = idx

        rgb = _accent_rgb()
        accent_border = T['accent_border']

        for r in self._game_row_widgets:
            if not r.isVisible():
                continue
            if r.property("game_index") == idx:
                # Selected style
                r.setStyleSheet(f"""
                    QFrame {{
                        background-color: rgba({rgb},0.2);
                        border: none;
                        border-left: 3px solid {accent_border};
                        border-bottom: 1px solid rgba({rgb},0.08);
                        border-radius: 0px;
                    }}
                """)
                lbl = r.property("left_lbl")
                if lbl:
                    lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Medium))
            else:
                normal = r.property("normal_ss")
                if normal:
                    r.setStyleSheet(normal)
                lbl = r.property("left_lbl")
                if lbl:
                    lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))

        # Update info label
        w = row.property("white") or "?"
        b = row.property("black") or "?"
        op = row.property("opening") or ""
        # Shorten player names to last names
        w_short = w.split(",")[0].strip()
        b_short = b.split(",")[0].strip()
        info = f"Training: {w_short} vs {b_short}"
        if op:
            info += f" \u00b7 {op}"
        self._sel_info_lbl.setText(info)
        self._sel_info_lbl.setVisible(True)

        self._set_start_enabled(True)

    def _filter_games(self, text):
        """Filter game rows based on search text."""
        query = text.lower().strip()
        for row in self._game_row_widgets:
            if not query:
                row.setVisible(True)
                continue
            w = (row.property("white") or "").lower()
            b = (row.property("black") or "").lower()
            op = (row.property("opening") or "").lower()
            row.setVisible(query in w or query in b or query in op)

    def _pick_color(self, color):
        self._color = color
        self._btn_white.set_active(color == "white")
        self._btn_black.set_active(color == "black")

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Repertoire PGN", "",
            "PGN files (*.pgn);;All files (*.*)")
        if path:
            self._pgn_path = path
            self._file_lbl.setText(os.path.basename(path))
            if hasattr(self, '_ot_empty_hint'):
                self._ot_empty_hint.hide()

            # Scan games
            try:
                self._pgn_games = _scan_pgn_games(path)
            except Exception as e:
                _ot_logger.error("Failed to scan PGN file %s: %s", path, e)
                self._pgn_games = []
                try:
                    from PyQt6.QtWidgets import QMessageBox
                    QMessageBox.warning(self, "PGN Error",
                        f"Could not read the PGN file:\n{os.path.basename(path)}\n\n"
                        "The file may be malformed or unreadable.")
                except Exception:
                    pass

            if len(self._pgn_games) <= 1:
                # Single game (or empty) — hide selector, keep start enabled
                self._game_selector_card.setVisible(False)
                self._selected_game = 0 if self._pgn_games else None
                self._sel_info_lbl.setVisible(False)
                self._set_start_enabled(True)
            else:
                # Multiple games — show selector
                self._game_selector_card.setVisible(True)
                self._populate_games()

    def _clear(self):
        self._pgn_path = None
        self._pgn_games = []
        self._selected_game = None
        self._file_lbl.setText("(none)")
        self._game_selector_card.setVisible(False)
        self._sel_info_lbl.setVisible(False)
        self._set_start_enabled(True)
        if hasattr(self, '_ot_empty_hint'):
            self._ot_empty_hint.show()

    def _start(self):
        if not self._pgn_path:
            return
        # If multi-game PGN and nothing selected, block
        if len(self._pgn_games) > 1 and self._selected_game is None:
            return
        cfg = {
            "pgn_path": self._pgn_path,
            "player_color": chess.WHITE if self._color == "white" else chess.BLACK,
        }
        # Pass game_index only when a specific game was chosen from multi-game PGN
        if len(self._pgn_games) > 1 and self._selected_game is not None:
            cfg["game_index"] = self._selected_game
        self.finished.emit(cfg)

    def _resume_session(self, saved):
        """Resume a previously paused training session."""
        player_color = chess.WHITE if saved.get("player_color") == "white" else chess.BLACK
        cfg = {
            "pgn_path": saved["pgn_path"],
            "player_color": player_color,
            "game_index": saved.get("game_index"),
            "__resume__": saved,
        }
        self.finished.emit(cfg)

    def _discard_session(self):
        """Discard the saved session and hide the banner."""
        cfg = _load_config()
        cfg.pop("opening_trainer_session", None)
        _save_config(cfg)
        if self._resume_banner:
            self._resume_banner.hide()
            self._resume_banner.deleteLater()
            self._resume_banner = None


# ============================================================================
#  OPENING TRAINER PAGE
# ============================================================================


def _scan_pgn_games(pgn_path):
    """Scan a PGN file and return a list of game header dicts.

    Each entry: {"white": str, "black": str, "opening": str, "index": int}
    """
    games = []
    try:
        with open(pgn_path, "r", encoding="utf-8", errors="replace") as f:
            idx = 0
            while True:
                try:
                    game = chess.pgn.read_game(f)
                except Exception as e:
                    _ot_logger.error("Error parsing game #%d in PGN file %s: %s",
                                     idx, pgn_path, e)
                    break
                if game is None:
                    break
                h = game.headers
                white = h.get("White", "?") or "?"
                black = h.get("Black", "?") or "?"
                opening = h.get("Opening", "") or h.get("ECO", "") or ""
                games.append({"white": white, "black": black,
                              "opening": opening, "index": idx})
                idx += 1
    except Exception as e:
        _ot_logger.error("Failed to open PGN file %s: %s", pgn_path, e)
    return games


def _accent_rgb():
    """Extract the RGB triplet from the current theme's accent_border value."""
    import re
    m = re.search(r'rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)', T.get('accent_border', ''))
    if m:
        return f"{m.group(1)},{m.group(2)},{m.group(3)}"
    return "147,197,253"


class _MoveTree:
    """A node in a PGN move tree for the opening trainer."""
    __slots__ = ('move', 'children', 'is_end')

    def __init__(self, move=None):
        self.move = move          # chess.Move or None for root
        self.children = {}        # {move_uci: _MoveTree}
        self.is_end = False

    def add_child(self, move):
        uci = move.uci()
        if uci not in self.children:
            self.children[uci] = _MoveTree(move)
        return self.children[uci]


def _build_move_tree(pgn_path, game_index=None):
    """Parse PGN file and build a move tree from all games and variations.

    If *game_index* is given, only the game at that 0-based index is loaded.
    Otherwise all games are merged into a single tree (original behaviour).
    """
    root = _MoveTree()

    def _walk_node(pgn_node, tree_node, board):
        for variation in pgn_node.variations:
            move = variation.move
            if move not in board.legal_moves:
                continue
            child = tree_node.add_child(move)
            board.push(move)
            if not variation.variations:
                child.is_end = True
            _walk_node(variation, child, board)
            board.pop()

    start_fen = None
    try:
        with open(pgn_path, "r", encoding="utf-8", errors="replace") as f:
            idx = 0
            while True:
                try:
                    game = chess.pgn.read_game(f)
                except Exception as e:
                    _ot_logger.error("Error reading game #%d from PGN %s: %s",
                                     idx, pgn_path, e)
                    break
                if game is None:
                    break
                if game_index is not None and idx != game_index:
                    idx += 1
                    continue
                try:
                    fen = game.headers.get("FEN")
                    if fen and fen != chess.STARTING_FEN:
                        start_fen = fen
                        board = chess.Board(fen)
                    else:
                        board = chess.Board()
                    _walk_node(game, root, board)
                except Exception as e:
                    _ot_logger.error("Error building tree for game #%d in %s: %s",
                                     idx, pgn_path, e)
                if game_index is not None:
                    break
                idx += 1
    except Exception as e:
        _ot_logger.error("Failed to open PGN file for tree building %s: %s",
                         pgn_path, e)

    return root, start_fen


def _collect_lines(tree_node, prefix=None):
    """Collect all complete lines (root-to-leaf paths) as lists of UCI strings."""
    if prefix is None:
        prefix = []
    lines = []
    if not tree_node.children or tree_node.is_end:
        if prefix:
            lines.append(list(prefix))
    for uci, child in tree_node.children.items():
        prefix.append(uci)
        lines.extend(_collect_lines(child, prefix))
        prefix.pop()
    return lines


class OpeningTrainerPage(QWidget):
    finished = pyqtSignal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"background-color: {T['bg']}; border: none;")
        self.player_color = cfg["player_color"]
        self.flipped = (self.player_color == chess.BLACK)

        # Build move tree from PGN
        try:
            self._tree_root, self._start_fen = _build_move_tree(
                cfg["pgn_path"], game_index=cfg.get("game_index"))
        except Exception as e:
            _ot_logger.error("Failed to build move tree from PGN: %s\n%s",
                             e, traceback.format_exc())
            self._tree_root = _MoveTree()
            self._start_fen = None
        self._all_lines = _collect_lines(self._tree_root)
        self._total_lines = max(1, len(self._all_lines))
        self._completed_line_ids = set()   # indices into _all_lines
        self._show_move_count = 0

        # Current training state
        self._current_node = self._tree_root
        self._current_line_idx = 0
        self._history = []       # SAN strings for display
        self._waiting = False    # True while opponent reply or animation is pending
        self._training_done = False

        # Score tracker state
        self._score_decisions = 0   # total scored attempts (CORRECT + WRONG)
        self._score_correct = 0     # moves correct on first try
        self._score_wrong = 0       # every wrong attempt counts
        self._score_hints = 0       # times Show Move was clicked
        self._current_pos_wrongs = 0  # wrong attempts at current position
        self._current_pos_hinted = False  # whether current position used Show Move
        self._moves_completed = 0   # user moves successfully completed
        self._total_user_moves = self._count_total_user_moves()
        self._mistake_log = []      # list of mistake dicts for gallery
        self._cfg = cfg             # keep config for pause/save

        # Board
        if self._start_fen:
            self.board = chess.Board(self._start_fen)
        else:
            self.board = chess.Board()

        self.selected = None
        self.legal_tgt = []
        self.drag_sq = None
        self.drag_pos = None
        self.last_move = None

        # Square flash overlay state
        self._flash_sq = None
        self._flash_color = None
        self._flash_opacity = 0.0
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(20)
        self._flash_timer.timeout.connect(self._flash_tick)
        self._flash_start_time = 0
        self._flash_duration = 0

        self._pause_overlay = None
        self._mistake_modal = None
        self._build_ui()

        # Check for resume state
        resume = cfg.get("__resume__")
        if resume:
            self._restore_session(resume)
        else:
            self._sync_board_widget()
            self._start_line()

    def _restore_session(self, state):
        """Restore a paused session from saved state."""
        try:
            self._completed_line_ids = set(state.get("completed_line_ids", []))
            self._current_line_idx = state.get("current_line_idx", 0)
            self._score_decisions = state.get("score_decisions", 0)
            self._score_correct = state.get("score_correct", 0)
            self._score_wrong = state.get("score_wrong", 0)
            self._score_hints = state.get("score_hints", 0)
            self._show_move_count = state.get("show_move_count", 0)
            self._moves_completed = state.get("moves_completed", 0)
            self._mistake_log = state.get("mistake_log", [])

            # Replay move stack through the tree
            move_ucis = state.get("move_stack_uci", [])
            self._current_node = self._tree_root
            for uci in move_ucis:
                try:
                    move = chess.Move.from_uci(uci)
                    if move in self.board.legal_moves:
                        self.board.push(move)
                        if uci in self._current_node.children:
                            self._current_node = self._current_node.children[uci]
                    else:
                        break
                except Exception:
                    _ot_logger.error("Invalid UCI in saved session: %s", uci)
                    break

            self._history = state.get("history", [])
            self._current_pos_wrongs = 0
            self._current_pos_hinted = False

            self._update_history()
            self._update_score_display()
            self._update_progress()
            self._sync_board_widget()

            # Clear saved session from config
            OpeningTrainerPage._clear_saved_session()

            # Determine if it's user's turn or opponent's
            if self.board.turn != self.player_color and self._current_node.children:
                self._play_opponent_move()
            else:
                self._set_status("Your move")
        except Exception as e:
            _ot_logger.error("Failed to restore session: %s\n%s",
                             e, traceback.format_exc())
            # Fall back to starting fresh
            self._sync_board_widget()
            self._start_line()

    def _game_btn(self, text):
        btn = QPushButton(text)
        btn.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedHeight(44)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['btn_bg']};
                border: 1px solid {T['btn_border']};
                border-radius: 10px; padding: 0 12px;
                color: {T['btn_text']};
            }}
            QPushButton:hover {{
                background-color: {T['accent_bg']}; border-color: {T['accent_border']};
                color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: {T['accent_bg']}; }}
        """)
        _add_press_anim(btn)
        return btn

    def _count_total_user_moves(self):
        """Count total user moves across all training lines."""
        # Determine who moves first from the starting position
        if self._start_fen:
            first_is_white = chess.Board(self._start_fen).turn == chess.WHITE
        else:
            first_is_white = True
        total = 0
        for line in self._all_lines:
            for i in range(len(line)):
                # Determine which color makes move at index i
                if first_is_white:
                    is_player = (i % 2 == 0) == (self.player_color == chess.WHITE)
                else:
                    is_player = (i % 2 == 0) == (self.player_color == chess.BLACK)
                if is_player:
                    total += 1
        return total

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # --- Left side: board (68%) ---
        left = QVBoxLayout()
        left.setContentsMargins(10, 8, 4, 8)
        left.setSpacing(4)

        self.board_widget = BoardWidget()
        self.board_widget.piece_imgs = load_piece_pixmaps(SQ)
        self.board_widget.flipped = self.flipped
        self.board_widget.board = self.board
        self.board_widget.mousePressEvent = self._on_press
        self.board_widget.mouseMoveEvent = self._on_drag
        self.board_widget.mouseReleaseEvent = self._on_release
        left.addWidget(self.board_widget, 1)

        root.addLayout(left, 68)

        # --- Right side: panel (32%) ---
        panel = QFrame()
        panel.setStyleSheet(f"""
            QFrame {{
                background-color: {T['bg']};
                border-left: 1px solid {T['section_border']};
            }}
            {_frost_scrollbar_ss()}
        """)
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(10, 10, 10, 10)
        pl.setSpacing(6)

        # Score tracker card
        _ar = _accent_rgb()
        score_card = QFrame()
        score_card.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({_ar},0.06);
                border: 1px solid rgba({_ar},0.12);
                border-radius: 10px;
                padding: 10px 16px;
            }}
        """)
        sc_layout = QHBoxLayout(score_card)
        sc_layout.setContentsMargins(0, 0, 0, 0)
        sc_layout.setSpacing(0)

        def _make_stat(number_text, label_text, number_color):
            block = QVBoxLayout()
            block.setSpacing(1)
            block.setAlignment(Qt.AlignmentFlag.AlignCenter)
            num = QLabel(number_text)
            num.setFont(QFont(_UI_FONT, 18, QFont.Weight.Light))
            num.setStyleSheet(f"color: {number_color}; background: transparent; border: none;")
            num.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl = QLabel(label_text)
            lbl.setFont(QFont(_UI_FONT, 9, QFont.Weight.Normal))
            lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none; letter-spacing: 2px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            block.addWidget(num)
            block.addWidget(lbl)
            return block, num

        def _make_divider():
            d = QFrame()
            d.setFixedWidth(1)
            d.setStyleSheet(f"background-color: rgba({_ar},0.1); border: none;")
            return d

        blk_dec, self._score_decisions_lbl = _make_stat("0", "DECISIONS", T['accent_text'])
        blk_correct, self._score_correct_lbl = _make_stat("0", "CORRECT", _stat_green())
        blk_wrong, self._score_wrong_lbl = _make_stat("0", "WRONG", _stat_red())
        blk_hints, self._score_hints_lbl = _make_stat("0", "HINTS", _stat_blue())

        sc_layout.addLayout(blk_dec, 1)
        sc_layout.addWidget(_make_divider())
        sc_layout.addLayout(blk_correct, 1)
        sc_layout.addWidget(_make_divider())
        sc_layout.addLayout(blk_wrong, 1)
        sc_layout.addWidget(_make_divider())
        sc_layout.addLayout(blk_hints, 1)

        # Move progress label below stats
        self._move_progress_lbl = QLabel(f"Move 0 / {self._total_user_moves}")
        self._move_progress_lbl.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
        self._move_progress_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none;")
        self._move_progress_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._move_progress_lbl.setContentsMargins(0, 2, 0, 0)

        score_wrapper = QVBoxLayout()
        score_wrapper.setSpacing(0)
        score_wrapper.addWidget(score_card)
        score_wrapper.addWidget(self._move_progress_lbl)
        pl.addLayout(score_wrapper)

        # Status label
        self.status_lbl = QLabel("Your move")
        self.status_lbl.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.status_lbl.setStyleSheet(f"color: {T['text_muted']}; background: transparent;")
        self.status_lbl.setWordWrap(True)
        self.status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_lbl.setContentsMargins(0, 6, 0, 6)
        pl.addWidget(self.status_lbl)

        # Move history
        self.hist_text = QTextBrowser()
        self.hist_text.setStyleSheet(f"""
            QTextBrowser {{
                background-color: {T['bg']}; color: {T['text_primary']};
                border: none; padding: 2px 0px;
            }}
            {_frost_scrollbar_ss()}
        """)
        self.hist_text.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.hist_text.setReadOnly(True)
        self.hist_text.setOpenLinks(False)
        pl.addWidget(self.hist_text, 1)

        # Show Move button
        self.btn_show = QPushButton("Show Move")
        self.btn_show.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.btn_show.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_show.setFixedHeight(48)
        self.btn_show.setStyleSheet(f"""
            QPushButton {{
                background-color: {T['accent_bg']};
                border: 1px solid {T['accent_border']};
                border-radius: 10px; padding: 0 12px;
                color: {T['accent_text']};
            }}
            QPushButton:hover {{
                background-color: {T['accent_border']};
                border-color: {T['accent_text']};
                color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: {T['accent_border']}; }}
        """)
        _add_press_anim(self.btn_show)
        self.btn_show.clicked.connect(self._show_move)
        pl.addWidget(self.btn_show)

        # Pause button
        _ar = _accent_rgb()
        self.btn_pause = QPushButton("\u23f8  Pause")
        self.btn_pause.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
        self.btn_pause.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_pause.setFixedHeight(44)
        self.btn_pause.setStyleSheet(f"""
            QPushButton {{
                background-color: rgba({_ar},0.07);
                border: 1px solid rgba({_ar},0.14);
                border-radius: 10px; padding: 0 12px;
                color: {T['accent_text']};
            }}
            QPushButton:hover {{
                background-color: rgba({_ar},0.14);
                border-color: rgba({_ar},0.28);
                color: {T['title']};
            }}
            QPushButton:pressed {{ background-color: rgba({_ar},0.14); }}
        """)
        _add_press_anim(self.btn_pause)
        self.btn_pause.clicked.connect(self._on_pause)
        pl.addWidget(self.btn_pause)

        # Back to Menu button (saves session so user can resume later)
        btn_menu = self._game_btn("Back to Menu")
        btn_menu.clicked.connect(self._back_to_menu)
        pl.addWidget(btn_menu)

        root.addWidget(panel, 32)

        # Completion overlay (hidden)
        self._completion_overlay = None

    def _sync_board_widget(self):
        bw = self.board_widget
        bw.board = self.board
        bw.flipped = self.flipped
        bw.selected = None
        bw.legal_tgt = []
        bw.last_move = None
        bw.drag_sq = self.drag_sq
        bw.drag_pos = self.drag_pos
        bw.game_over = self._training_done
        bw.update()

    def _set_status(self, text, color=None):
        if color is None:
            color = T['text_muted']
        self.status_lbl.setText(text)
        self.status_lbl.setStyleSheet(f"color: {color}; background: transparent;")

    def _update_progress(self):
        self._move_progress_lbl.setText(f"Move {self._moves_completed} / {self._total_user_moves}")

    def _update_score_display(self):
        self._score_decisions_lbl.setText(str(self._score_decisions))
        self._score_correct_lbl.setText(str(self._score_correct))
        self._score_wrong_lbl.setText(str(self._score_wrong))
        self._score_hints_lbl.setText(str(self._score_hints))

    # -- Move history rendering (same pattern as ChessGamePage) --
    def _update_history(self):
        if not self._history:
            self.hist_text.setHtml(""); return
        last_idx = len(self._history) - 1
        rows = []
        for i in range(0, len(self._history), 2):
            mn = i // 2 + 1
            rbg = T['section_bg'] if mn % 2 == 0 else "transparent"
            m1 = self._history[i] if i < len(self._history) else ""
            m2 = self._history[i + 1] if i + 1 < len(self._history) else ""
            if i == last_idx:
                m1_html = (f'<span style="background-color:{T["accent_bg"]};'
                           f'color:{T["accent_text"]};padding:2px 4px;border-radius:3px;">{m1}</span>')
            else:
                m1_html = f'<span style="color:{T["text_primary"]};">{m1}</span>'
            if i + 1 == last_idx and m2:
                m2_html = (f'<span style="background-color:{T["accent_bg"]};'
                           f'color:{T["accent_text"]};padding:2px 4px;border-radius:3px;">{m2}</span>')
            elif m2:
                m2_html = f'<span style="color:{T["text_primary"]};">{m2}</span>'
            else:
                m2_html = ""
            rows.append(
                f'<tr style="background:{rbg};height:28px;">'
                f'<td style="color:{T["text_muted"]};padding:3px 6px 3px 4px;'
                f'text-align:right;white-space:nowrap;font-size:11pt;font-weight:300;">{mn}.</td>'
                f'<td style="padding:3px 8px;white-space:nowrap;font-size:13pt;font-weight:400;">{m1_html}</td>'
                f'<td style="padding:3px 8px;white-space:nowrap;font-size:13pt;font-weight:400;">{m2_html}</td>'
                f'</tr>')
        html = (f'<table cellspacing="0" cellpadding="0" '
                f'style="font-family:{_UI_FONT},sans-serif;font-size:13pt;width:100%;">'
                + "".join(rows) + '</table>')
        self.hist_text.setHtml(html)
        self._smooth_scroll_history()

    def _smooth_scroll_history(self):
        sb = self.hist_text.verticalScrollBar()
        target = sb.maximum()
        if target <= 0 or sb.value() >= target - 2:
            sb.setValue(target); return
        anim = QPropertyAnimation(sb, b"value", self.hist_text)
        anim.setStartValue(sb.value())
        anim.setEndValue(target)
        anim.setDuration(180)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.hist_text._scroll_anim = anim
        anim.start()

    # -- Training flow --
    def _reset_board(self):
        if self._start_fen:
            self.board = chess.Board(self._start_fen)
        else:
            self.board = chess.Board()
        self._current_node = self._tree_root
        self._history = []
        self.selected = None
        self.legal_tgt = []
        self.drag_sq = None
        self.drag_pos = None
        self.last_move = None
        self._waiting = False

    def _start_line(self):
        """Start the next unfinished line."""
        self._current_pos_wrongs = 0
        self._current_pos_hinted = False
        self._reset_board()
        self._update_history()
        self._update_progress()
        self._sync_board_widget()

        # If user plays Black, auto-play White's moves from the tree
        if self.board.turn != self.player_color:
            self._play_opponent_move()
        else:
            self._set_status("Your move")

    def _pick_opponent_child(self):
        """Pick the opponent's move, preferring branches with uncompleted lines."""
        node = self._current_node
        if not node.children:
            return None, None

        # Build the current move path as UCI list
        # to figure out which lines are still reachable
        current_path = [m.uci() for m in self.board.move_stack]

        # For each child, check if it leads to any uncompleted line
        best_uci = None
        for uci, child in node.children.items():
            test_path = current_path + [uci]
            # Check if any uncompleted line starts with this path
            for idx, line in enumerate(self._all_lines):
                if idx in self._completed_line_ids:
                    continue
                if len(line) >= len(test_path) and line[:len(test_path)] == test_path:
                    best_uci = uci
                    break
            if best_uci:
                break

        # Fallback to first child if all reachable lines are completed
        if best_uci is None:
            best_uci = next(iter(node.children))

        return best_uci, node.children[best_uci]

    def _play_opponent_move(self):
        """Auto-play the opponent's next move from the PGN tree."""
        self._waiting = True
        if not self._current_node.children:
            self._line_complete()
            return

        uci, child = self._pick_opponent_child()
        if child is None:
            self._line_complete()
            return
        move = child.move
        if move not in self.board.legal_moves:
            self._line_complete()
            return

        san = self.board.san(move)
        self.board.push(move)
        play_move_sound()
        self._history.append(san)
        self._current_node = child
        self._update_history()
        self._sync_board_widget()

        # Check if line ended after opponent move
        if not self._current_node.children:
            self._safe_singleshot(400, self._line_complete)
            return

        self._waiting = False
        self._set_status("Your move")

    def _mark_completed_lines(self):
        """Mark all lines that match the current board move stack as completed."""
        current_path = [m.uci() for m in self.board.move_stack]
        for idx, line in enumerate(self._all_lines):
            if line == current_path:
                self._completed_line_ids.add(idx)

    def _line_complete(self):
        """Current line completed successfully."""
        self._waiting = True
        self._mark_completed_lines()
        self._update_progress()

        if len(self._completed_line_ids) >= self._total_lines:
            self._safe_singleshot(800, self._show_completion)
            return

        # Find next unfinished line
        found = False
        for idx in range(self._total_lines):
            if idx not in self._completed_line_ids:
                self._current_line_idx = idx
                found = True
                break
        if not found:
            self._safe_singleshot(800, self._show_completion)
            return

        self._set_status("Correct!", _stat_green())
        self._safe_singleshot(800, self._start_line)

    # -- Safe timer helper --
    def _safe_singleshot(self, ms, callback):
        """QTimer.singleShot that checks if the widget still exists."""
        def _guarded():
            try:
                if self.isVisible() and not self._training_done:
                    callback()
            except RuntimeError:
                pass  # Widget was already deleted
            except Exception as e:
                _ot_logger.error("Timer callback error: %s\n%s",
                                 e, traceback.format_exc())
        QTimer.singleShot(ms, _guarded)

    # -- Square flash effects --
    def _flash_square(self, sq, color, duration_ms):
        self._flash_sq = sq
        self._flash_color = color
        self._flash_duration = duration_ms
        self._flash_start_time = time.time() * 1000
        self._flash_opacity = 1.0
        self._flash_timer.start()
        self.board_widget.update()

    def _flash_tick(self):
        try:
            if not self.isVisible():
                self._flash_timer.stop()
                return
            elapsed = time.time() * 1000 - self._flash_start_time
            if elapsed >= self._flash_duration:
                self._flash_timer.stop()
                self._flash_sq = None
                self._flash_color = None
                self._flash_opacity = 0.0
                self.board_widget.update()
                return
            self._flash_opacity = max(0.0, 1.0 - elapsed / self._flash_duration)
            self.board_widget.update()
        except RuntimeError:
            self._flash_timer.stop()
        except Exception as e:
            self._flash_timer.stop()
            _ot_logger.error("Flash tick error: %s", e)

    def _draw_flash_overlay(self, painter):
        """Called from board_widget's paint to draw flash overlay."""
        if self._flash_sq is None or self._flash_opacity <= 0:
            return
        sq = self._flash_sq
        bw = self.board_widget
        px, py = bw._sq_to_pixel(sq)
        S = bw._sq
        c = QColor(self._flash_color)
        c.setAlphaF(c.alphaF() * self._flash_opacity)
        painter.fillRect(px, py, S, S, c)

    # -- Input handling (same pattern as ChessGamePage) --
    def _on_press(self, event):
        if self._training_done or self._waiting or self.board.turn != self.player_color:
            return
        pos = event.position()
        x, y = int(pos.x()), int(pos.y())
        sq = self.board_widget.sq_from_pixel(x, y)
        if sq is None:
            self.selected = None; self.legal_tgt = []
            self._sync_board_widget(); return
        if self.selected is not None:
            p = self.board.piece_at(self.selected)
            promo = chess.QUEEN if p and p.piece_type == chess.PAWN and chess.square_rank(sq) in (0, 7) else None
            move = chess.Move(self.selected, sq, promotion=promo)
            if move in self.board.legal_moves:
                self._try_move(move); return
        p = self.board.piece_at(sq)
        if p and p.color == self.player_color:
            self.selected = sq
            self.legal_tgt = [m.to_square for m in self.board.legal_moves if m.from_square == sq]
            self.drag_sq = sq; self.drag_pos = (x, y)
        else:
            self.selected = None; self.legal_tgt = []
            self.drag_sq = None; self.drag_pos = None
        self._sync_board_widget()

    def _on_drag(self, event):
        if self.drag_sq is None: return
        pos = event.position()
        self.drag_pos = (int(pos.x()), int(pos.y()))
        self._sync_board_widget()

    def _on_release(self, event):
        if self.drag_sq is None: return
        from_sq = self.drag_sq
        self.drag_sq = None; self.drag_pos = None
        pos = event.position()
        to_sq = self.board_widget.sq_from_pixel(int(pos.x()), int(pos.y()))
        if to_sq is not None and to_sq != from_sq:
            p = self.board.piece_at(from_sq)
            promo = chess.QUEEN if p and p.piece_type == chess.PAWN and chess.square_rank(to_sq) in (0, 7) else None
            move = chess.Move(from_sq, to_sq, promotion=promo)
            if move in self.board.legal_moves:
                self._try_move(move, animate=False); return
        self._sync_board_widget()

    def _try_move(self, move, animate=True):
        """Check if the user's move matches any branch in the PGN tree."""
        uci = move.uci()
        self.selected = None
        self.legal_tgt = []
        self.drag_sq = None
        self.drag_pos = None

        if uci in self._current_node.children:
            # Correct move — pick the branch that leads to uncompleted lines
            child = self._current_node.children[uci]
            san = self.board.san(move)
            self.board.push(move)
            play_move_sound()
            self._history.append(san)
            self._current_node = child
            self._update_history()
            self._sync_board_widget()

            # Score tracking — only count if position was not hinted
            self._moves_completed += 1
            if not self._current_pos_hinted:
                self._score_decisions += 1
                self._score_correct += 1
            self._current_pos_wrongs = 0
            self._current_pos_hinted = False
            self._update_score_display()
            self._update_progress()

            self._set_status("Correct!", _stat_green())

            # Check if line ended
            if not self._current_node.children:
                self._safe_singleshot(500, self._line_complete)
                return

            # Play opponent response after delay
            self._waiting = True
            self._safe_singleshot(400, self._play_opponent_move)
        else:
            # Wrong move — snap back
            self._current_pos_wrongs += 1
            # Log or update mistake entry for this position
            cur_fen = self.board.fen()
            user_san = self.board.san(move)
            existing = next((e for e in self._mistake_log if e["fen"] == cur_fen), None)
            if existing:
                existing["wrong_count"] = self._current_pos_wrongs
                if existing["type"] == "hint":
                    existing["type"] = "wrong_and_hint"
                elif existing["type"] != "wrong_and_hint":
                    existing["type"] = "wrong"
                if existing.get("user_san") is None:
                    existing["user_san"] = user_san
            else:
                # Get the first correct move SAN
                first_uci = next(iter(self._current_node.children))
                correct_move = chess.Move.from_uci(first_uci)
                correct_san = self.board.san(correct_move)
                self._mistake_log.append({
                    "fen": cur_fen,
                    "correct_san": correct_san,
                    "user_san": user_san,
                    "correct_ucis": list(self._current_node.children.keys()),
                    "history": list(self._history),
                    "type": "wrong",
                    "wrong_count": 1,
                })
            if not self._current_pos_hinted:
                self._score_wrong += 1
                self._score_decisions += 1
            self._update_score_display()
            self._set_status("Wrong move \u2014 try again", _stat_red_bright())
            self._sync_board_widget()

    # -- Show Move --
    def _show_move(self):
        if self._training_done or self._waiting:
            return
        if not self._current_node.children:
            return

        # Undo any wrong counts already recorded for this position
        if self._current_pos_wrongs > 0 and not self._current_pos_hinted:
            self._score_wrong -= self._current_pos_wrongs
            self._score_decisions -= self._current_pos_wrongs

        self._score_hints += 1
        self._show_move_count += 1
        self._current_pos_hinted = True
        self._current_pos_wrongs = 0

        # Log hint for mistake gallery
        cur_fen = self.board.fen()
        existing = next((e for e in self._mistake_log if e["fen"] == cur_fen), None)
        if existing:
            if existing["type"] == "wrong":
                existing["type"] = "wrong_and_hint"
        else:
            # Get the first correct move SAN
            first_uci = next(iter(self._current_node.children))
            correct_move_obj = chess.Move.from_uci(first_uci)
            correct_san = self.board.san(correct_move_obj)
            self._mistake_log.append({
                "fen": cur_fen,
                "correct_san": correct_san,
                "user_san": None,
                "correct_ucis": list(self._current_node.children.keys()),
                "history": list(self._history),
                "type": "hint",
                "wrong_count": 0,
            })

        self._update_score_display()

        # Get the first correct move
        uci = next(iter(self._current_node.children))
        child = self._current_node.children[uci]
        move = child.move
        if move not in self.board.legal_moves:
            return

        self._waiting = True
        self._set_status("Showing correct move...", T['text_muted'])

        self.board.push(move)
        play_move_sound()
        self._sync_board_widget()

        def _take_back():
            try:
                self.board.pop()
                self._waiting = False
                self._sync_board_widget()
                self._set_status("Your move")
            except Exception as e:
                _ot_logger.error("Take-back error: %s", e)

        self._safe_singleshot(1200, _take_back)

    # -- Completion screen --
    def _show_completion(self, all_complete=True):
        self._training_done = True
        self._sync_board_widget()
        OpeningTrainerPage._clear_saved_session()

        overlay = QWidget(self)
        overlay.setGeometry(0, 0, self.width(), self.height())
        overlay.setStyleSheet(f"background-color: {T['bg']};")

        main_lay = QHBoxLayout(overlay)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ── LEFT SIDE (68%) — Mistake gallery ──
        left_panel = QFrame()
        left_panel.setStyleSheet(f"background-color: {T['bg']}; border: none;")
        lp_lay = QVBoxLayout(left_panel)
        lp_lay.setContentsMargins(24, 24, 24, 24)
        lp_lay.setSpacing(0)

        gallery_layout = self._build_mistake_gallery(left_panel, columns=3,
                                                      section_label_text="POSITIONS TO REVIEW",
                                                      empty_text="\u2713 Perfect session \u2014 no mistakes!")
        lp_lay.addLayout(gallery_layout, 1)
        main_lay.addWidget(left_panel, 68)

        # ── RIGHT SIDE (32%) — Title + Stats + Buttons ──
        right_panel = QFrame()
        right_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {T['bg']};
                border-left: 1px solid {T['section_border']};
            }}
        """)
        rp_lay = QVBoxLayout(right_panel)
        rp_lay.setContentsMargins(16, 20, 16, 16)
        rp_lay.setSpacing(8)

        rp_lay.addStretch(1)

        # Title
        if all_complete:
            title = QLabel("Memory Check Complete")
            title.setFont(QFont(_UI_FONT, 24, QFont.Weight.Light))
            title.setStyleSheet(f"color: {T['title']}; background: transparent; border: none;")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rp_lay.addWidget(title)
            rp_lay.addSpacing(6)

            check = QLabel("\u2713 All lines memorized")
            check.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
            check.setStyleSheet(f"color: {_stat_green()}; background: transparent; border: none;")
            check.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rp_lay.addWidget(check)
        else:
            title = QLabel("Session Ended")
            title.setFont(QFont(_UI_FONT, 24, QFont.Weight.Light))
            title.setStyleSheet(f"color: {T['title']}; background: transparent; border: none;")
            title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rp_lay.addWidget(title)
            rp_lay.addSpacing(4)

            prog = QLabel(f"Move {self._moves_completed} / {self._total_user_moves} completed")
            prog.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
            prog.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none;")
            prog.setAlignment(Qt.AlignmentFlag.AlignCenter)
            rp_lay.addWidget(prog)

        rp_lay.addSpacing(8)

        # Stats card (4-block)
        _ar = _accent_rgb()
        stats_card = QFrame()
        stats_card.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({_ar},0.06);
                border: 1px solid rgba({_ar},0.12);
                border-radius: 10px;
                padding: 8px 10px;
            }}
        """)
        sc_lay = QHBoxLayout(stats_card)
        sc_lay.setContentsMargins(0, 0, 0, 0)
        sc_lay.setSpacing(0)

        def _stat(val, label, color):
            bl = QVBoxLayout()
            bl.setSpacing(0)
            bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n = QLabel(str(val))
            n.setFont(QFont(_UI_FONT, 15, QFont.Weight.Light))
            n.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l = QLabel(label)
            l.setFont(QFont(_UI_FONT, 8, QFont.Weight.Normal))
            l.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none; letter-spacing: 1px;")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl.addWidget(n); bl.addWidget(l)
            return bl

        def _div():
            d = QFrame()
            d.setFixedWidth(1)
            d.setStyleSheet(f"background-color: rgba({_ar},0.1); border: none;")
            return d

        sc_lay.addLayout(_stat(self._score_decisions, "DECISIONS", T['accent_text']), 1)
        sc_lay.addWidget(_div())
        sc_lay.addLayout(_stat(self._score_correct, "CORRECT", _stat_green()), 1)
        sc_lay.addWidget(_div())
        sc_lay.addLayout(_stat(self._score_wrong, "WRONG", _stat_red()), 1)
        sc_lay.addWidget(_div())
        sc_lay.addLayout(_stat(self._score_hints, "HINTS", _stat_blue()), 1)
        rp_lay.addWidget(stats_card)

        rp_lay.addStretch(1)

        # Buttons
        btn_again = _make_button("Train Again", 13, min_height=52, accent=True)
        _add_press_anim(btn_again)
        btn_again.clicked.connect(lambda: self._restart_training(overlay))
        rp_lay.addWidget(btn_again)

        btn_back = self._game_btn("Back to Menu")
        btn_back.clicked.connect(lambda: self.finished.emit("back"))
        rp_lay.addWidget(btn_back)

        main_lay.addWidget(right_panel, 32)
        overlay.show()

        # Fade in
        opacity = QGraphicsOpacityEffect(overlay)
        overlay.setGraphicsEffect(opacity)
        anim = QPropertyAnimation(opacity, b"opacity", overlay)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(300)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(lambda: overlay.setGraphicsEffect(None))
        anim.start()
        self._completion_overlay = overlay
        overlay._fade_anim = anim  # prevent GC

    def _restart_training(self, overlay):
        if overlay:
            overlay.hide()
            overlay.deleteLater()
        self._completion_overlay = None
        self._training_done = False
        self._completed_line_ids.clear()
        self._show_move_count = 0
        self._current_line_idx = 0
        self._score_decisions = 0
        self._score_correct = 0
        self._score_wrong = 0
        self._score_hints = 0
        self._moves_completed = 0
        self._current_pos_wrongs = 0
        self._current_pos_hinted = False
        self._mistake_log = []
        self._update_score_display()
        OpeningTrainerPage._clear_saved_session()
        self._start_line()

    def _on_pause(self):
        if self._training_done or self._waiting:
            return
        self._waiting = True
        self._save_session_to_config()
        self._show_pause_overlay()

    def _back_to_menu(self):
        """Save session and return to launcher."""
        if not self._training_done:
            self._save_session_to_config()
        self.finished.emit("back")

    def _build_pause_state(self):
        try:
            return {
                "pgn_path": self._cfg.get("pgn_path"),
                "game_index": self._cfg.get("game_index"),
                "player_color": "white" if self.player_color == chess.WHITE else "black",
                "completed_line_ids": list(self._completed_line_ids),
                "current_line_idx": self._current_line_idx,
                "move_stack_uci": [m.uci() for m in self.board.move_stack],
                "history": list(self._history),
                "score_decisions": self._score_decisions,
                "score_correct": self._score_correct,
                "score_wrong": self._score_wrong,
                "score_hints": self._score_hints,
                "show_move_count": self._show_move_count,
                "moves_completed": self._moves_completed,
                "total_user_moves": self._total_user_moves,
                "total_lines": self._total_lines,
                "mistake_log": list(self._mistake_log),
                "paused_at": time.time(),
            }
        except Exception as e:
            _ot_logger.error("Failed to build pause state: %s", e)
            return {}

    def _save_session_to_config(self):
        try:
            cfg = _load_config()
            cfg["opening_trainer_session"] = self._build_pause_state()
            _save_config(cfg)
        except Exception as e:
            _ot_logger.error("Failed to save session to config: %s", e)

    @staticmethod
    def _clear_saved_session():
        try:
            cfg = _load_config()
            cfg.pop("opening_trainer_session", None)
            _save_config(cfg)
        except Exception as e:
            _ot_logger.error("Failed to clear saved session: %s", e)

    def _build_mistake_gallery(self, parent_widget, columns=2, section_label_text="POSITIONS TO REVIEW",
                               empty_text="\u2713 No mistakes so far!"):
        """Build a scrollable thumbnail grid of mistake/hint positions.
        Returns a QVBoxLayout that can be added to a parent layout.
        """
        container = QVBoxLayout()
        container.setSpacing(4)

        lbl = QLabel(section_label_text)
        lbl.setFont(QFont(_UI_FONT, 9, QFont.Weight.Normal))
        lbl.setStyleSheet(f"color: {T['section_label']}; background: transparent; border: none; letter-spacing: 2px;")
        container.addWidget(lbl)

        if not self._mistake_log:
            no_m = QLabel(empty_text)
            no_m.setFont(QFont(_UI_FONT, 13, QFont.Weight.Normal))
            no_m.setStyleSheet(f"color: {_stat_green()}; background: transparent; border: none;")
            no_m.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_m.setContentsMargins(0, 12, 0, 12)
            container.addWidget(no_m)
            return container

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            {_frost_scrollbar_ss()}
        """)

        scroll_w = QWidget()
        scroll_w.setStyleSheet("background: transparent;")
        grid = QGridLayout(scroll_w)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(16)

        _ar = _accent_rgb()
        for idx, entry in enumerate(self._mistake_log):
          try:
            card = QFrame()
            card.setFixedSize(240, 276)
            card.setStyleSheet(f"""
                QFrame {{
                    background-color: rgba({_ar},0.06);
                    border: 1px solid rgba({_ar},0.12);
                    border-radius: 10px;
                }}
            """)
            card.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)

            # Mini board pixmap — flush at top of card
            fen = entry.get("fen", chess.STARTING_FEN)
            pixmap = _render_mini_board_pixmap(fen, 216, flipped=self.flipped)
            board_lbl = QLabel()
            board_lbl.setPixmap(pixmap)
            board_lbl.setFixedSize(240, 216)
            board_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            board_lbl.setStyleSheet("border: none; background: transparent; padding: 0px;")
            cl.addWidget(board_lbl)

            # 8px gap between board and text
            cl.addSpacing(8)

            # Text section below the board
            text_w = QWidget()
            text_w.setStyleSheet(f"background-color: rgba({_ar},0.06); border: none;")
            text_lay = QVBoxLayout(text_w)
            text_lay.setContentsMargins(10, 0, 10, 8)
            text_lay.setSpacing(2)

            # Line 1: Correct move
            correct_san = entry.get("correct_san", "")
            if not correct_san:
                try:
                    b = chess.Board(fen)
                    cuci = entry.get("correct_ucis", [""])[0]
                    correct_san = b.san(chess.Move.from_uci(cuci)) if cuci else "?"
                except Exception:
                    correct_san = "?"
            cor_lbl = QLabel(f"Correct move: {correct_san}")
            cor_lbl.setFont(QFont(_UI_FONT, 12, QFont.Weight.Normal))
            cor_lbl.setStyleSheet(f"color: {T['accent_text']}; background: transparent; border: none;")
            cor_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_lay.addWidget(cor_lbl)

            # Line 2: User's move
            user_san = entry.get("user_san")
            if user_san is None:
                wrong_uci = entry.get("wrong_uci")
                if wrong_uci:
                    try:
                        user_san = chess.Board(fen).san(chess.Move.from_uci(wrong_uci))
                    except Exception:
                        user_san = wrong_uci
            if user_san:
                usr_lbl = QLabel(f"Your move: {user_san}")
                usr_lbl.setFont(QFont(_UI_FONT, 12, QFont.Weight.Normal))
                usr_lbl.setStyleSheet(f"color: {_stat_red_bright()}; background: transparent; border: none;")
            else:
                usr_lbl = QLabel("Your move: \u2014")
                usr_lbl.setFont(QFont(_UI_FONT, 12, QFont.Weight.Normal))
                usr_lbl.setStyleSheet(f"color: {_stat_blue()}; background: transparent; border: none;")
            usr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            text_lay.addWidget(usr_lbl)

            cl.addWidget(text_w)

            # Click handler
            card.mousePressEvent = lambda ev, e=entry: self._show_mistake_modal(e)

            row = idx // columns
            col = idx % columns
            grid.addWidget(card, row, col, Qt.AlignmentFlag.AlignTop)
          except Exception as e:
            _ot_logger.error("Failed to render mistake card #%d: %s", idx, e)

        # Fill remaining cols in last row with spacers
        remainder = len(self._mistake_log) % columns
        if remainder != 0:
            for c in range(remainder, columns):
                spacer = QWidget()
                spacer.setFixedWidth(240)
                grid.addWidget(spacer, len(self._mistake_log) // columns, c)

        scroll.setWidget(scroll_w)
        container.addWidget(scroll, 1)
        return container

    _MM_BOARD_MAX = 646   # ideal board size (capped by screen)
    # Fixed-height layout chrome around the board:
    #   close-row 40 + gap 16 + cor 22 + gap 10 + usr 22 + bot-pad 20 = 130
    _MM_CHROME_H = 130
    _MM_PAD_SIDE = 40     # horizontal padding inside card (32*2 minus border budget)

    def _ensure_mistake_modal(self):
        """Create the reusable mistake modal once, or return the existing one."""
        if getattr(self, '_mistake_modal', None) is not None:
            return
        modal_bg = QWidget(self)
        modal_bg.setStyleSheet("background-color: rgba(0,0,0,0.55);")
        modal_bg.hide()

        # Card — direct child of modal_bg, no scroll area
        card = QFrame(modal_bg)
        card.setStyleSheet(f"""
            QFrame {{
                background-color: #1a1a2e;
                border: 1px solid rgba(255,255,255,0.15);
                border-radius: 12px;
            }}
        """)

        cl = QVBoxLayout(card)
        cl.setContentsMargins(32, 12, 32, 20)
        cl.setSpacing(0)

        # Close button row (fixed 40px)
        close_btn = QPushButton("\u2715")
        close_btn.setFont(QFont(_UI_FONT, 16))
        close_btn.setFixedSize(36, 36)
        close_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        close_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: rgba(255,255,255,0.5);
                border: none; border-radius: 18px;
            }
            QPushButton:hover { color: #fff; background: rgba(255,255,255,0.1); }
        """)
        close_btn.clicked.connect(lambda: modal_bg.hide())
        close_row = QHBoxLayout()
        close_row.setContentsMargins(0, 0, 0, 0)
        close_row.addStretch()
        close_row.addWidget(close_btn)
        close_w = QWidget()
        close_w.setFixedHeight(40)
        close_w.setLayout(close_row)
        close_w.setStyleSheet("background: transparent; border: none;")
        cl.addWidget(close_w)

        # Large board label (size set dynamically)
        big_lbl = QLabel()
        big_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        big_lbl.setStyleSheet("border: none; background: transparent;")
        cl.addWidget(big_lbl, 0, Qt.AlignmentFlag.AlignCenter)

        # 16px gap between board and text
        cl.addSpacing(16)

        # Correct move label (fixed 22px)
        cor_lbl = QLabel()
        cor_lbl.setFont(QFont(_UI_FONT, 16, QFont.Weight.Normal))
        cor_lbl.setFixedHeight(22)
        cor_lbl.setStyleSheet(f"color: {T['accent_text']}; background: transparent; border: none;")
        cor_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(cor_lbl)

        # 10px gap between the two lines
        cl.addSpacing(10)

        # User move label (fixed 22px)
        usr_lbl = QLabel()
        usr_lbl.setFont(QFont(_UI_FONT, 16, QFont.Weight.Normal))
        usr_lbl.setFixedHeight(22)
        usr_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cl.addWidget(usr_lbl)

        # Click outside card to close; clicks on card stay
        modal_bg.mousePressEvent = lambda ev: modal_bg.hide()
        card.mousePressEvent = lambda ev: None  # prevent click-through

        # Store references
        self._mistake_modal = modal_bg
        self._mm_card = card
        self._mm_big_lbl = big_lbl
        self._mm_cor_lbl = cor_lbl
        self._mm_usr_lbl = usr_lbl
        self._mm_last_board_sz = 0  # track to avoid redundant pixmap redraws

    def _calc_modal_board_size(self):
        """Return the board pixel size that fits the current window."""
        avail_h = self.height() - 80   # 40px margin top + bottom
        avail_w = self.width() - 80
        board_sz = min(avail_h - self._MM_CHROME_H,
                       avail_w - self._MM_PAD_SIDE,
                       self._MM_BOARD_MAX)
        return max(200, board_sz)       # sensible minimum

    def _position_mistake_modal(self):
        """Compute sizes, apply fixedSize, and centre the card."""
        w, h = self.width(), self.height()
        self._mistake_modal.setGeometry(0, 0, w, h)

        bsz = self._calc_modal_board_size()
        card_w = bsz + self._MM_PAD_SIDE + 64     # board + side padding (32*2)
        card_h = bsz + self._MM_CHROME_H

        # Update board label size
        self._mm_big_lbl.setFixedSize(bsz, bsz)

        # Fix card size — no scrolling possible
        self._mm_card.setFixedSize(int(card_w), int(card_h))
        cx = max(0, (w - int(card_w)) // 2)
        cy = max(0, (h - int(card_h)) // 2)
        self._mm_card.move(cx, cy)
        return bsz

    def _show_mistake_modal(self, entry):
        """Show expanded view of a mistake position using the reusable modal."""
        try:
            self._ensure_mistake_modal()
            bsz = self._position_mistake_modal()

            # Update board pixmap
            fen = entry.get("fen", chess.STARTING_FEN)
            big_pm = _render_mini_board_pixmap(fen, bsz, flipped=self.flipped)
            self._mm_big_lbl.setPixmap(big_pm)
            self._mm_last_board_sz = bsz
            self._mm_last_entry = entry

            # Update correct move text
            correct_san = entry.get("correct_san", "")
            if not correct_san:
                try:
                    b = chess.Board(fen)
                    cuci = entry.get("correct_ucis", [""])[0]
                    correct_san = b.san(chess.Move.from_uci(cuci)) if cuci else "?"
                except Exception:
                    correct_san = "?"
            self._mm_cor_lbl.setText(f"Correct move: {correct_san}")

            # Update user move text
            user_san = entry.get("user_san")
            if user_san is None:
                wrong_uci = entry.get("wrong_uci")
                if wrong_uci:
                    try:
                        user_san = chess.Board(fen).san(chess.Move.from_uci(wrong_uci))
                    except Exception:
                        user_san = wrong_uci
            if user_san:
                self._mm_usr_lbl.setText(f"Your move: {user_san}")
                self._mm_usr_lbl.setStyleSheet(
                    f"color: {_stat_red_bright()}; background: transparent; border: none;")
            else:
                self._mm_usr_lbl.setText("Your move: \u2014")
                self._mm_usr_lbl.setStyleSheet(
                    f"color: {_stat_blue()}; background: transparent; border: none;")

            self._mistake_modal.show()
            self._mistake_modal.raise_()
        except Exception as e:
            _ot_logger.error("Failed to show mistake modal: %s\n%s",
                             e, traceback.format_exc())

    def _show_pause_overlay(self):
        self._pause_overlay = QWidget(self)
        self._pause_overlay.setGeometry(0, 0, self.width(), self.height())
        self._pause_overlay.setStyleSheet(f"background-color: {T['bg']};")

        main_lay = QHBoxLayout(self._pause_overlay)
        main_lay.setContentsMargins(0, 0, 0, 0)
        main_lay.setSpacing(0)

        # ── LEFT SIDE (68%) — Mistake gallery ──
        left_panel = QFrame()
        left_panel.setStyleSheet(f"background-color: {T['bg']}; border: none;")
        lp_lay = QVBoxLayout(left_panel)
        lp_lay.setContentsMargins(24, 24, 24, 24)
        lp_lay.setSpacing(0)

        gallery_layout = self._build_mistake_gallery(left_panel, columns=3,
                                                      section_label_text="MISTAKES SO FAR")
        lp_lay.addLayout(gallery_layout, 1)
        main_lay.addWidget(left_panel, 68)

        # ── RIGHT SIDE (32%) — Stats + Buttons ──
        right_panel = QFrame()
        right_panel.setStyleSheet(f"""
            QFrame {{
                background-color: {T['bg']};
                border-left: 1px solid {T['section_border']};
            }}
        """)
        rp_lay = QVBoxLayout(right_panel)
        rp_lay.setContentsMargins(16, 20, 16, 16)
        rp_lay.setSpacing(8)

        rp_lay.addStretch(1)

        # Title
        pause_title = QLabel("Session Paused")
        pause_title.setFont(QFont(_UI_FONT, 24, QFont.Weight.Light))
        pause_title.setStyleSheet(f"color: {T['title']}; background: transparent; border: none;")
        pause_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rp_lay.addWidget(pause_title)
        rp_lay.addSpacing(6)

        # Progress
        prog = QLabel(f"Move {self._moves_completed} / {self._total_user_moves}")
        prog.setFont(QFont(_UI_FONT, 11, QFont.Weight.Normal))
        prog.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none;")
        prog.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rp_lay.addWidget(prog)
        rp_lay.addSpacing(8)

        # Mini score card
        _ar = _accent_rgb()
        mini_card = QFrame()
        mini_card.setStyleSheet(f"""
            QFrame {{
                background-color: rgba({_ar},0.06);
                border: 1px solid rgba({_ar},0.12);
                border-radius: 10px;
                padding: 8px 10px;
            }}
        """)
        mc_lay = QHBoxLayout(mini_card)
        mc_lay.setContentsMargins(0, 0, 0, 0)
        mc_lay.setSpacing(0)

        def _mini_stat(val, label, color):
            bl = QVBoxLayout()
            bl.setSpacing(0)
            bl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            n = QLabel(str(val))
            n.setFont(QFont(_UI_FONT, 15, QFont.Weight.Light))
            n.setStyleSheet(f"color: {color}; background: transparent; border: none;")
            n.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l = QLabel(label)
            l.setFont(QFont(_UI_FONT, 8, QFont.Weight.Normal))
            l.setStyleSheet(f"color: {T['text_muted']}; background: transparent; border: none; letter-spacing: 1px;")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            bl.addWidget(n); bl.addWidget(l)
            return bl

        def _mini_div():
            d = QFrame()
            d.setFixedWidth(1)
            d.setStyleSheet(f"background-color: rgba({_ar},0.1); border: none;")
            return d

        mc_lay.addLayout(_mini_stat(self._score_decisions, "DECISIONS", T['accent_text']), 1)
        mc_lay.addWidget(_mini_div())
        mc_lay.addLayout(_mini_stat(self._score_correct, "CORRECT", _stat_green()), 1)
        mc_lay.addWidget(_mini_div())
        mc_lay.addLayout(_mini_stat(self._score_wrong, "WRONG", _stat_red()), 1)
        mc_lay.addWidget(_mini_div())
        mc_lay.addLayout(_mini_stat(self._score_hints, "HINTS", _stat_blue()), 1)
        rp_lay.addWidget(mini_card)

        rp_lay.addStretch(1)

        # Buttons
        btn_continue = _make_button("Continue Training  \u2192", 13, min_height=52, accent=True)
        _add_press_anim(btn_continue)
        btn_continue.clicked.connect(self._resume_from_pause)
        rp_lay.addWidget(btn_continue)

        btn_end = self._game_btn("End Session")
        btn_end.clicked.connect(self._end_session_from_pause)
        rp_lay.addWidget(btn_end)

        btn_menu = self._game_btn("Back to Menu")
        btn_menu.clicked.connect(self._back_to_menu)
        rp_lay.addWidget(btn_menu)

        main_lay.addWidget(right_panel, 32)
        self._pause_overlay.show()

        # Fade in
        opacity = QGraphicsOpacityEffect(self._pause_overlay)
        self._pause_overlay.setGraphicsEffect(opacity)
        fade = QPropertyAnimation(opacity, b"opacity", self._pause_overlay)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setDuration(250)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.finished.connect(lambda: self._pause_overlay.setGraphicsEffect(None))
        fade.start()
        self._pause_overlay._fade_anim = fade

    def _resume_from_pause(self):
        if self._pause_overlay:
            self._pause_overlay.hide()
            self._pause_overlay.deleteLater()
            self._pause_overlay = None
        self._waiting = False
        self._set_status("Your move")
        OpeningTrainerPage._clear_saved_session()

    def _end_session_from_pause(self):
        if self._pause_overlay:
            self._pause_overlay.hide()
            self._pause_overlay.deleteLater()
            self._pause_overlay = None
        self._waiting = False
        OpeningTrainerPage._clear_saved_session()
        self._show_completion(all_complete=False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._completion_overlay:
            self._completion_overlay.setGeometry(0, 0, self.width(), self.height())
        if hasattr(self, '_pause_overlay') and self._pause_overlay:
            self._pause_overlay.setGeometry(0, 0, self.width(), self.height())
        if getattr(self, '_mistake_modal', None) and self._mistake_modal.isVisible():
            bsz = self._position_mistake_modal()
            # Re-render board pixmap if size changed
            if bsz != getattr(self, '_mm_last_board_sz', 0) and hasattr(self, '_mm_last_entry'):
                fen = self._mm_last_entry.get("fen", chess.STARTING_FEN)
                self._mm_big_lbl.setPixmap(
                    _render_mini_board_pixmap(fen, bsz, flipped=self.flipped))
                self._mm_last_board_sz = bsz

    def cleanup(self):
        self._flash_timer.stop()
        try:
            self._flash_timer.timeout.disconnect(self._flash_tick)
        except Exception:
            pass
        if getattr(self, '_hint_anim_timer', None):
            self._hint_anim_timer.stop()
            self._hint_anim_timer = None
        self._training_done = True
        # Destroy the reusable modal
        if getattr(self, '_mistake_modal', None):
            try:
                self._mistake_modal.hide()
                self._mistake_modal.deleteLater()
            except Exception:
                pass
            self._mistake_modal = None

    # -- Override board paint to add flash overlay --
    def _install_flash_paint(self):
        """Monkey-patch the board widget's paintEvent to add flash overlay."""
        original_paint = self.board_widget.paintEvent
        trainer = self

        def _patched_paint(event):
            original_paint(event)
            if trainer._flash_sq is not None and trainer._flash_opacity > 0:
                p = QPainter(trainer.board_widget)
                trainer._draw_flash_overlay(p)
                p.end()

        self.board_widget.paintEvent = _patched_paint


# ============================================================================
#  MAIN WINDOW
# ============================================================================

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChessGym")
        self.setWindowIcon(get_app_icon())
        self.setMinimumSize(560, 600)
        self.setStyleSheet(f"QMainWindow {{ background-color: {T['bg']}; }}")
        self._current_page = None
        self._theme_fade_label = None
        self._show_launcher()
        self.showMaximized()

    def _apply_theme_style(self):
        self.setStyleSheet(f"QMainWindow {{ background-color: {T['bg']}; }}")
        # Update app palette
        palette = QApplication.instance().palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(T['bg']))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(T['title']))
        palette.setColor(QPalette.ColorRole.Base, QColor(T['bg']))
        palette.setColor(QPalette.ColorRole.Text, QColor(T['title']))
        palette.setColor(QPalette.ColorRole.Button, QColor(T['bg']))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(T['title']))
        palette.setColor(QPalette.ColorRole.BrightText, QColor(T['accent_text']))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(T['accent_bg']))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor(T['accent_text']))
        QApplication.instance().setPalette(palette)

    def _on_theme_changed(self, name):
        # --- Smooth crossfade: snapshot current frame, rebuild underneath, fade out ---
        try:
            # 1. Capture the current window contents as a pixmap
            snapshot = self.grab()

            # 2. Create a QLabel overlay pinned on top of everything
            fade_lbl = QLabel(self)
            fade_lbl.setPixmap(snapshot)
            fade_lbl.setGeometry(0, 0, self.width(), self.height())
            fade_lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            fade_lbl.show()
            fade_lbl.raise_()
            self._theme_fade_label = fade_lbl

            # 3. Set window bg immediately to prevent flash, then suppress repaints
            self.setStyleSheet(f"QMainWindow {{ background-color: {T['bg']}; }}")
            QApplication.instance().processEvents()
            self.setUpdatesEnabled(False)

            # 4. Apply the new theme + rebuild the page underneath the snapshot
            self._apply_theme_style()
            self._show_launcher()

            # 5. Re-enable updates
            self.setUpdatesEnabled(True)
            self.update()

            # 6. Fade the snapshot out so the new theme is revealed smoothly
            opacity_effect = QGraphicsOpacityEffect(fade_lbl)
            fade_lbl.setGraphicsEffect(opacity_effect)
            fade_anim = QPropertyAnimation(opacity_effect, b"opacity", fade_lbl)
            fade_anim.setStartValue(1.0)
            fade_anim.setEndValue(0.0)
            fade_anim.setDuration(180)
            fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

            def _cleanup():
                fade_lbl.hide()
                fade_lbl.deleteLater()
                if self._theme_fade_label is fade_lbl:
                    self._theme_fade_label = None

            fade_anim.finished.connect(_cleanup)
            fade_anim.start()
            fade_lbl._fade_anim = fade_anim  # prevent GC
        except Exception:
            # Fallback: just apply instantly if anything goes wrong
            self.setUpdatesEnabled(True)
            self._apply_theme_style()
            self._show_launcher()

    def _set_page(self, page):
        old_page = self._current_page
        if old_page is not None:
            if hasattr(old_page, 'cleanup'):
                old_page.cleanup()
            old_page.deleteLater()
        self._current_page = page
        self.setCentralWidget(page)

    def _show_launcher(self):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(560, 600)
        page = LauncherPage()
        page.finished.connect(self._on_launcher_choice)
        page.theme_changed.connect(self._on_theme_changed)
        self._set_page(page)

    def _on_launcher_choice(self, choice):
        if choice == "play":
            sf_path = find_stockfish()
            if sf_path is None:
                self._show_error_no_stockfish(); return
            self._show_game_mode(sf_path)
        elif choice == "winpos":
            sf_path = find_stockfish()
            if sf_path is None:
                self._show_error_no_stockfish(); return
            self._sf_path = sf_path
            self._show_winpos_setup()
        elif choice == "trainer":
            self._show_trainer_setup()
        elif choice == "pgn":
            self._show_pgn_viewer()

    def _show_error_no_stockfish(self):
        page = ErrorPage("Stockfish engine not found.",
                         "Please make sure stockfish.exe is in the stockfish folder.")
        page.finished.connect(lambda: self._show_launcher())
        self._set_page(page)

    def _show_game_mode(self, sf_path):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(560, 420)
        page = GameModePage()
        def on_mode(mode):
            if mode == "back": self._show_launcher()
            elif mode == "fen": self._show_fen_setup(sf_path)
            else: self._show_setup(sf_path, mode == "chess960")
        page.finished.connect(on_mode)
        self._set_page(page)

    def _show_setup(self, sf_path, chess960):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(520, 640)
        page = SetupPage(chess960=chess960)
        def on_setup(result):
            if result == "back": self._show_launcher()
            elif isinstance(result, dict): self._show_game(result, sf_path)
        page.finished.connect(on_setup)
        self._set_page(page)

    def _show_fen_setup(self, sf_path, initial_fen=""):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(520, 700)
        page = FenSetupPage(initial_fen=initial_fen)
        def on_fen_result(result):
            if result == "back": self._show_launcher()
            elif result == "builder": self._show_fen_builder(sf_path)
            elif isinstance(result, dict): self._show_game(result, sf_path)
        page.finished.connect(on_fen_result)
        self._set_page(page)

    def _show_fen_builder(self, sf_path):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(700, 600)
        page = FenBuilderPage()
        def on_builder_done(result):
            if result == "back":
                self._show_launcher()
            else:
                self._show_fen_setup(sf_path, initial_fen=result)
        page.finished.connect(on_builder_done)
        self._set_page(page)

    def _show_game(self, cfg, sf_path):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(1000, 700)
        try:
            page = ChessGamePage(cfg, sf_path)
        except Exception as e:
            _ot_logger.error("Failed to start game: %s", e)
            print(f"Failed to start game: {e}")
            page = ErrorPage("Could not start game.",
                             f"The chess engine failed to initialize.\n{e}")
            page.finished.connect(lambda: self._show_launcher())
            self._set_page(page); return
        page.finished.connect(lambda r: self._show_launcher())
        self._set_page(page)

    def _show_winpos_setup(self):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(520, 700)
        page = WinPosSetupPage()
        def on_winpos(result):
            if result == "back": self._show_launcher()
            elif result == "scanner": self._show_scanner()
            elif isinstance(result, dict): self._show_game(result, self._sf_path)
        page.finished.connect(on_winpos)
        self._set_page(page)

    def _show_scanner(self):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(520, 500)
        page = ScannerPage()
        page.finished.connect(lambda r: self._show_winpos_setup())
        self._set_page(page)

    def _show_trainer_setup(self):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(520, 680)
        page = OpeningTrainerSetupPage()
        def on_setup(result):
            if result == "back":
                self._show_launcher()
            elif isinstance(result, dict):
                self._show_trainer(result)
        page.finished.connect(on_setup)
        self._set_page(page)

    def _show_trainer(self, cfg):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(1000, 700)
        try:
            page = OpeningTrainerPage(cfg)
        except Exception as e:
            _ot_logger.error("Failed to start trainer: %s", e)
            print(f"Failed to start trainer: {e}")
            page = ErrorPage("Could not start Opening Trainer.",
                             f"Failed to load the PGN file.\n{e}")
            page.finished.connect(lambda: self._show_launcher())
            self._set_page(page); return
        page.finished.connect(lambda r: self._show_launcher())
        self._set_page(page)

    def _show_pgn_viewer(self):
        self.setWindowTitle("ChessGym")
        self.setMinimumSize(900, 650)
        page = PGNViewerPage()
        page.finished.connect(lambda r: self._show_launcher())
        self._set_page(page)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_M:
            global _sound_muted
            _sound_muted = not _sound_muted
            try:
                cfg = _load_config()
                cfg["sound_muted"] = _sound_muted
                _save_config(cfg)
            except Exception:
                pass
            # Refresh the mute button if the current page has one
            if self._current_page and hasattr(self._current_page, '_mute_btn'):
                self._current_page._mute_btn.refresh()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event):
        if self._current_page and hasattr(self._current_page, 'cleanup'):
            self._current_page.cleanup()
        event.accept()




# -- Entry point -------------------------------------------------------------
def _run_startup_diagnostics():
    """Log diagnostic info on every launch for remote debugging."""
    cfg = _load_config()
    sf = find_stockfish()
    # Check one positions file as a representative
    pos_sample = os.path.join(_WPOS_RANGES[0]["w_dir"], "positions.pgn")
    pos_found = os.path.isfile(pos_sample)
    cfg_found = os.path.isfile(_CONFIG_PATH)

    try:
        screen_info = "unknown"
        app = QApplication.instance()
        if app:
            screen = app.primaryScreen()
            if screen:
                g = screen.geometry()
                screen_info = f"{g.width()}x{g.height()}"
    except Exception:
        screen_info = "unavailable"

    lines = [
        f"App version:      {cfg.get('version', 'unknown')}",
        f"Python version:   {sys.version.split()[0]}",
        f"Operating system: {sys.platform} ({os.name})",
        f"Frozen:           {getattr(sys, 'frozen', False)}",
        f"BASE_DIR:         {BASE_DIR}",
        f"RESOURCE_DIR:     {RESOURCE_DIR}",
        f"Stockfish found:  {'yes — ' + sf if sf else 'NO'}",
        f"Positions found:  {'yes' if pos_found else 'no'} ({pos_sample})",
        f"Config found:     {'yes' if cfg_found else 'no'}",
        f"Screen:           {screen_info}",
    ]
    header = "=" * 50
    diag = "\n".join([header, "ChessGym Startup Diagnostics", header] + lines + [header])
    print(diag)
    _ot_logger.info("Startup diagnostics:\n%s", diag)


def main():
    os.chdir(BASE_DIR)
    os.makedirs(_BOOK_DIR_W, exist_ok=True)
    os.makedirs(_BOOK_DIR_B, exist_ok=True)

    # Ensure winning positions directories exist
    for r in _WPOS_RANGES:
        os.makedirs(r["w_dir"], exist_ok=True)
        os.makedirs(r["b_dir"], exist_ok=True)

    # Load saved theme and mute state before creating any widgets
    try:
        cfg = _load_config()
        saved_theme = cfg.get("theme", "soft_light")
        if saved_theme in THEMES:
            set_theme(saved_theme)
        global _sound_muted
        _sound_muted = cfg.get("sound_muted", False)
        # Ensure version field exists in config
        if "version" not in cfg:
            cfg["version"] = "2.3"
            _save_config(cfg)
            print("[Update] No version in config — set to 3.2")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setWindowIcon(get_app_icon())
    _detect_fonts()
    app.setFont(QFont(_UI_FONT, 13))

    # Themed palette for system dialogs
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(T['bg']))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(T['title']))
    palette.setColor(QPalette.ColorRole.Base, QColor(T['bg']))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(T['section_bg']))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(T['bg']))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(T['title']))
    palette.setColor(QPalette.ColorRole.Text, QColor(T['title']))
    palette.setColor(QPalette.ColorRole.Button, QColor(T['bg']))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(T['title']))
    palette.setColor(QPalette.ColorRole.BrightText, QColor(T['accent_text']))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(T['accent_bg']))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(T['accent_text']))
    app.setPalette(palette)

    _run_startup_diagnostics()

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    # ── Bootstrapper ──────────────────────────────────────────────────
    # When running as a frozen EXE, check if an updated main.py exists
    # next to the EXE.  If so, exec() it instead of the bundled version.
    # The env-var guard prevents infinite recursion (the external file
    # contains this same bootstrapper).
    if getattr(sys, 'frozen', False) and not os.environ.get('_CHESSGYM_EXTERNAL'):
        _ext_main = os.path.join(os.path.dirname(sys.executable), "main.py")
        if os.path.isfile(_ext_main):
            os.environ['_CHESSGYM_EXTERNAL'] = '1'
            _ns = {"__name__": "__main__", "__file__": _ext_main}
            with open(_ext_main, "r", encoding="utf-8") as _f:
                _code = compile(_f.read(), _ext_main, "exec")
            exec(_code, _ns)
            sys.exit(0)
    # ──────────────────────────────────────────────────────────────────
    main()
