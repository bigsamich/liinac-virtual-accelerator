"""Control-room dark theme."""

ACCENT = "#4fc3f7"
OK = "#43a047"
WARN = "#fbc02d"
ALARM = "#e53935"
BG = "#14171c"
PANEL = "#1c2128"
FG = "#d7dde5"

SECTION_COLORS = {
    "LEBT": "#6d4c41", "RFQ": "#5e35b1", "MEBT": "#00838f",
    "HWR": "#2e7d32", "SSR1": "#558b2f", "SSR2": "#9e9d24",
    "LB650": "#ef6c00", "HB650": "#d84315", "BTL": "#455a64",
}

STYLESHEET = f"""
QMainWindow, QWidget {{ background: {BG}; color: {FG};
    font-family: 'DejaVu Sans', sans-serif; font-size: 12px; }}
QFrame#panel {{ background: {PANEL}; border-radius: 6px; }}
QListWidget {{ background: {PANEL}; border: none; font-size: 13px;
    outline: none; }}
QListWidget::item {{ padding: 9px 14px; }}
QListWidget::item:selected {{ background: #263140; color: {ACCENT};
    border-left: 3px solid {ACCENT}; }}
QLabel#pageTitle {{ font-size: 17px; font-weight: bold; color: {ACCENT};
    padding: 4px; }}
QLabel#bigNumber {{ font-size: 26px; font-weight: bold; }}
QStatusBar {{ background: {PANEL}; }}
QPushButton {{ background: #2a323d; border: 1px solid #3a4553;
    border-radius: 4px; padding: 5px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton#danger {{ background: #4a1f1f; border-color: {ALARM}; }}
QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{ background: #10131a;
    border: 1px solid #3a4553; border-radius: 3px; padding: 3px; }}
QTableWidget {{ background: {PANEL}; gridline-color: #2a323d; }}
QHeaderView::section {{ background: #232a33; border: none; padding: 4px; }}
QTabWidget::pane {{ border: 1px solid #2a323d; }}
QTabBar::tab {{ background: {PANEL}; padding: 6px 14px; }}
QTabBar::tab:selected {{ background: #263140; color: {ACCENT}; }}
"""
