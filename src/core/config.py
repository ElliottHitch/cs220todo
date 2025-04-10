import calendar
import os

# Set first day of the week to Sunday
calendar.setfirstweekday(6)

# API Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
TOKEN_FILE = os.path.join('config', 'token.json')
CREDENTIALS_FILE = os.path.join('config', 'credentials.json')
DEFAULT_CALENDAR_ID = 'primary'
API_MAX_RESULTS = 50

# Color Theme
BACKGROUND_COLOR = "#1E1E2F"
NAV_BG_COLOR = "#2A2A3B"
DROPDOWN_BG_COLOR = "#252639"
CARD_COLOR = "#1F6AA5"
TEXT_COLOR = "#E0E0E0"
HIGHLIGHT_COLOR = "#6060A0"

# Fonts
FONT_HEADER = "Segoe UI Semibold"
FONT_HEADER_SIZE = 18
FONT_LABEL = "Segoe UI"
FONT_LABEL_SIZE = 14
FONT_SMALL = "Segoe UI"
FONT_SMALL_SIZE = 12
FONT_DAY = "Segoe UI Semibold"
FONT_DAY_SIZE = 12
FONT_DATE = "Segoe UI Semibold"
FONT_DATE_SIZE = 18
PADDING = 10

# UI Constants
DEFAULT_DIALOG_WIDTH = 400
DEFAULT_DIALOG_HEIGHT = 500
DEFAULT_WINDOW_SIZE = (1400, 1000)
MAX_TASKS_PER_CELL = 5

# StyleSheets
MAIN_STYLE = f"""
QMainWindow, QDialog {{
    background-color: {BACKGROUND_COLOR};
}}
QScrollArea {{
    background-color: {BACKGROUND_COLOR};
    border: none;
}}
QLabel {{
    color: {TEXT_COLOR};
}}
QPushButton {{
    background-color: {CARD_COLOR};
    color: white;
    border: none;
    border-radius: 4px;
    padding: 8px 16px;
    font-weight: bold;
}}
QPushButton:hover {{
    background-color: #2980b9;
}}
QLineEdit {{
    background-color: {DROPDOWN_BG_COLOR};
    color: {TEXT_COLOR};
    border: 1px solid #3D3D5C;
    border-radius: 4px;
    padding: 6px;
}}
QFrame[frameShape="4"] {{
    color: #3D3D5C;
}}
QCalendarWidget {{
    background-color: {DROPDOWN_BG_COLOR};
}}
QCalendarWidget QWidget {{
    alternate-background-color: {DROPDOWN_BG_COLOR};
}}
QTimeEdit {{
    background-color: {DROPDOWN_BG_COLOR};
    color: {TEXT_COLOR};
    border: 1px solid #3D3D5C;
    border-radius: 4px;
    padding: 6px;
}}
QComboBox {{
    background-color: {DROPDOWN_BG_COLOR};
    color: {TEXT_COLOR};
    border: 1px solid #3D3D5C;
    border-radius: 4px;
    padding: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {DROPDOWN_BG_COLOR};
    color: {TEXT_COLOR};
    selection-background-color: {HIGHLIGHT_COLOR};
}}
""" 