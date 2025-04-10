import os
import calendar
import sys
from datetime import datetime, timezone, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QPushButton, QFrame, QScrollArea, 
    QCalendarWidget, QComboBox, QSpinBox, QDialog, QGridLayout,
    QSplitter, QStackedWidget, QTabWidget, QMessageBox, QTimeEdit
)
from PyQt6.QtCore import Qt, QTimer, QDate, QTime, QDateTime, pyqtSignal, QThread, QSize, QObject, QPoint
from PyQt6.QtGui import QColor, QPalette, QFont, QIcon
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import threading
import queue


calendar.setfirstweekday(6)

# API Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'
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
DEFAULT_WINDOW_SIZE = (1200, 1000)
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

# HELPER FUNCTIONS
def convert_to_24(hour_str, period):
    """Convert 12-hour time format to 24-hour format."""
    hour = int(hour_str)
    return 0 if hour == 12 and period == "AM" else (hour if period == "AM" or hour == 12 else hour + 12)

def convert_from_24(hour_24_str):
    """Convert 24-hour time format to 12-hour format with AM/PM."""
    hour_24 = int(hour_24_str)
    if hour_24 == 0: return 12, "AM"
    elif hour_24 < 12: return hour_24, "AM"
    elif hour_24 == 12: return 12, "PM"
    else: return hour_24 - 12, "PM"

def local_to_utc(local_dt):
    """Convert local datetime object to UTC datetime object."""
    return local_dt.astimezone(timezone.utc)

def format_datetime(dt, format_type='time', include_minutes=True):
    """Format datetime according to specified format type.
    
    Args:
        dt: The datetime object to format
        format_type: One of 'time', 'weekday', 'day', 'month_year'
        include_minutes: For 'time' format, whether to include minutes
    """
    if format_type == 'time':
        if include_minutes:
            return dt.strftime('%I:%M%p').lstrip('0').replace(':00', '').lower()
        else:
            return dt.strftime('%I%p').lstrip('0').lower()
    elif format_type == 'weekday':
        return dt.strftime("%a").upper()
    elif format_type == 'day':
        return dt.strftime("%d")
    elif format_type == 'month_year':
        return f"{calendar.month_name[dt.month]} {dt.year}"
    else:
        return str(dt)

def format_task_time(start_dt, end_dt):
    """Format task start and end time consistently."""
    start_str = format_datetime(start_dt.astimezone(), 'time')
    end_str = format_datetime(end_dt.astimezone(), 'time')
    return f"{start_str}-{end_str}"

def format_iso_for_api(dt):
    """Format datetime as ISO format for Google API."""
    return dt.isoformat().replace('+00:00', 'Z')

def parse_iso_from_api(iso_str):
    """Parse ISO datetime string from Google API."""
    return datetime.fromisoformat(iso_str.replace('Z', '+00:00'))

def parse_event_datetime(event, field='start', as_date=False):
    """Parse datetime from a Google Calendar event field."""
    if field not in event:
        return datetime.now(timezone.utc)
        
    if 'dateTime' in event[field]:
        dt = parse_iso_from_api(event[field]['dateTime'])
        return dt.date() if as_date else dt
    elif 'date' in event[field]:
        local_date = datetime.fromisoformat(event[field]['date']).date()
        if as_date:
            return local_date
            
        local_tz = datetime.now().astimezone().tzinfo

        if field == 'start':
            local_dt = datetime.combine(local_date, datetime.min.time()).replace(tzinfo=local_tz)
        else:
            local_dt = datetime.combine(local_date, datetime.max.time()).replace(tzinfo=local_tz)
        
        return local_dt.astimezone(timezone.utc)
        
    return datetime.now(timezone.utc)

# TASK AND REMINDER CLASSES
class Task:
    """Represents a task/event with start and end times."""
    def __init__(self, summary, start_dt, end_dt, task_id=None, reminder_minutes=10, status='Pending'):
        self.summary = summary
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.task_id = task_id
        self.reminder_minutes = reminder_minutes
        self.status = status

# GOOGLE API CLASSES
class CacheManager:
    """Centralized cache manager for all calendar data."""
    def __init__(self):
        self.events_by_month = {}
        self.tasks_by_date = {}
        self.holidays_by_month = {}
        self.cache_lock = threading.Lock()
        self.fetched_ranges = set()
        self.event_ids = set()
        
    def add_event(self, event):
        """Add or update an event in the cache."""
        with self.cache_lock:
            self._add_event_no_lock(event)
    
    def _add_event_no_lock(self, event):
        """Add an event to the cache without acquiring the lock."""
        event_start = parse_event_datetime(event, field='start')
        month_key = (event_start.year, event_start.month)
        
        if month_key not in self.events_by_month:
            self.events_by_month[month_key] = []
            
        event_id = event.get('id')
        if event_id:
            self.events_by_month[month_key] = [e for e in self.events_by_month[month_key] 
                                              if e.get('id') != event_id]
            self.event_ids.add(event_id)
            
        self.events_by_month[month_key].append(event)
        
        task = self._convert_event_to_task(event)
        if task:
            if 'date' in event.get('start', {}):
                local_date = datetime.fromisoformat(event['start']['date']).date()
            else:
                local_date = task.start_dt.astimezone().date()
                
            if local_date not in self.tasks_by_date:
                self.tasks_by_date[local_date] = []
                
            self.tasks_by_date[local_date] = [t for t in self.tasks_by_date[local_date] 
                                            if getattr(t, 'task_id', None) != event_id]
            
            self.tasks_by_date[local_date].append(task)
    
    def add_events(self, events):
        """Add multiple events to the cache at once."""
        if not events:
            return
            
        with self.cache_lock:
            for event in events:
                self._add_event_no_lock(event)
    
    def delete_event(self, event_id):
        """Delete an event from all caches."""
        with self.cache_lock:
            for month_key, events_list in list(self.events_by_month.items()):
                self.events_by_month[month_key] = [e for e in events_list if e.get('id') != event_id]
            
            for date, tasks_list in list(self.tasks_by_date.items()):
                self.tasks_by_date[date] = [t for t in tasks_list if getattr(t, 'task_id', None) != event_id]
            
            self.event_ids.discard(event_id)
    
    def clear_month(self, year, month):
        """Clear the cache for a specific month."""
        month_key = (year, month)
        with self.cache_lock:
            if month_key in self.events_by_month:
                for event in self.events_by_month[month_key]:
                    self.event_ids.discard(event.get('id'))
                del self.events_by_month[month_key]
                
            if month_key in self.holidays_by_month:
                del self.holidays_by_month[month_key]
                
            self.tasks_by_date = {date: tasks for date, tasks in self.tasks_by_date.items() 
                                 if date.year != year or date.month != month}
                
            self.fetched_ranges.discard(month_key)
            
    def has_event_id(self, event_id):
        """Check if an event ID exists in the cache."""
        with self.cache_lock:
            return event_id in self.event_ids
    
    def get_events_for_month(self, year, month):
        """Get all events for a specific month."""
        month_key = (year, month)
        with self.cache_lock:
            return self.events_by_month.get(month_key, [])[:]
    
    def get_tasks_for_date(self, date):
        """Get all tasks for a specific date."""
        with self.cache_lock:
            return self.tasks_by_date.get(date, [])[:]
    
    def get_tasks_for_month(self, year, month):
        """Get all tasks for a specific month, organized by date."""
        result = {}
        with self.cache_lock:
            for date, tasks in self.tasks_by_date.items():
                if date.year == year and date.month == month:
                    result[date] = tasks[:]
        return result
    
    def get_all_tasks(self):
        """Get all tasks in the cache, as a list."""
        all_tasks = []
        with self.cache_lock:
            for tasks in self.tasks_by_date.values():
                all_tasks.extend(tasks)
        return all_tasks
    
    def get_holidays_for_month(self, year, month):
        """Get holidays for a specific month."""
        month_key = (year, month)
        with self.cache_lock:
            return self.holidays_by_month.get(month_key, {}).copy()
    
    def add_holidays(self, year, month, holidays):
        """Add holidays for a month to the cache."""
        month_key = (year, month)
        with self.cache_lock:
            self.holidays_by_month[month_key] = holidays
    
    def month_is_cached(self, year, month):
        """Check if a month's data is already cached."""
        month_key = (year, month)
        with self.cache_lock:
            return month_key in self.events_by_month
    
    def mark_range_fetched(self, year, month):
        """Mark a date range as having been fetched."""
        month_key = (year, month)
        with self.cache_lock:
            self.fetched_ranges.add(month_key)
    
    def _convert_event_to_task(self, event):
        """Convert a Google Calendar event to a Task object."""
        try:
            start_dt = parse_event_datetime(event, field='start')
            end_dt = parse_event_datetime(event, field='end')
            return Task(event['summary'], start_dt, end_dt, task_id=event.get('id'))
        except Exception as e:
            print(f"Error converting event to task: {str(e)}")
            return None

class GoogleAuthService:
    """Handles authentication with Google API."""
    def __init__(self, scopes, token_file=TOKEN_FILE, credentials_file=CREDENTIALS_FILE):
        self.scopes = scopes
        self.token_file = token_file
        self.credentials_file = credentials_file
        self.creds = None
        self.refresh_buffer = 300
        self.service = None

    def get_calendar_service(self):
        """Get an authenticated Google Calendar service."""
        if self.service is not None:
            return self.service
        self.service = build('calendar', 'v3', credentials=self._get_credentials())
        return self.service

    def _get_credentials(self):
        """Get valid credentials, refreshing or creating them if necessary."""
        creds = None
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.scopes)
        if not creds or not creds.valid:
            creds = self._refresh_credentials(creds)
        self.creds = creds
        return creds

    def _refresh_credentials(self, creds):
        """Refresh or create new credentials."""
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(self.credentials_file, self.scopes)
            creds = flow.run_local_server(port=0)
        with open(self.token_file, 'w') as token_file:
            token_file.write(creds.to_json())
        self.service = None
        return creds
        
    def auto_refresh_token(self):
        """Check if token is about to expire and refresh it proactively."""
        if not self.creds:
            self.creds = self._get_credentials()
            self.service = None
            return True
            
        if self.creds and hasattr(self.creds, 'expiry'):
            now = datetime.now(timezone.utc)
            if self.creds.expiry and self.creds.expiry.tzinfo is None:
                expiry = self.creds.expiry.replace(tzinfo=timezone.utc)
            else:
                expiry = self.creds.expiry
                
            time_until_expiry = (expiry - now).total_seconds() if expiry else 0
            
            if time_until_expiry < self.refresh_buffer:
                print(f"Token will expire soon ({time_until_expiry:.1f} seconds). Refreshing...")
                try:
                    self.creds = self._refresh_credentials(self.creds)
                    self.service = None
                    return True
                except Exception as e:
                    print(f"Error refreshing token: {str(e)}")
                    return False
        
        return False 

class CalendarManager:
    """Manages interactions with Google Calendar API."""
    def __init__(self, auth_service):
        self.auth_service = auth_service
        self.service = self.auth_service.get_calendar_service()
        self.cache = CacheManager()
        self.fetch_lock = threading.Lock()
        self.fetching_ranges = set()
    
    def _ensure_valid_token(self):
        """Ensure the token is valid before making API calls."""
        try:
            refreshed = self.auth_service.auto_refresh_token()
            if refreshed:
                self.service = self.auth_service.get_calendar_service()
        except Exception as e:
            print(f"Error ensuring valid token: {str(e)}")

    def fetch_events(self, calendar_id=DEFAULT_CALENDAR_ID, max_results=API_MAX_RESULTS, page_token=None, 
                     start_date=None, end_date=None):
        """Fetch events from Google Calendar with pagination support."""
        self._ensure_valid_token()
        
        if not start_date:
            start_date = datetime.now(timezone.utc)
        
        time_min = format_iso_for_api(start_date)
        time_max = None
        if end_date:
            time_max = format_iso_for_api(end_date)
        
        params = {
            'calendarId': calendar_id,
            'maxResults': max_results,
            'singleEvents': True,
            'orderBy': 'startTime',
            'timeMin': time_min
        }
        
        if time_max:
            params['timeMax'] = time_max
        
        if page_token:
            params['pageToken'] = page_token
        
        try:
            events_result = self.service.events().list(**params).execute()
            
            events = events_result.get('items', [])
            next_token = events_result.get('nextPageToken')
            
            return events, next_token
        except Exception as e:
            print(f"Error fetching events: {str(e)}")
            return [], None
    
    def fetch_events_for_range(self, start_date, end_date, calendar_id=DEFAULT_CALENDAR_ID):
        """Fetch all events within a date range, using the cache if available."""
        if isinstance(start_date, str):
            start_date = parse_iso_from_api(start_date)
        if isinstance(end_date, str):
            end_date = parse_iso_from_api(end_date)
        
        range_id = (calendar_id, start_date.isoformat(), end_date.isoformat())
        
        with self.fetch_lock:
            if range_id in self.fetching_ranges:
                return []
            self.fetching_ranges.add(range_id)
        
        try:
            self._ensure_valid_token()
            month_keys = self._get_month_keys_in_range(start_date, end_date)
            
            all_cached = all(self.cache.month_is_cached(*month_key) for month_key in month_keys)
            if all_cached:
                return [event for month_key in month_keys 
                       for event in self.cache.get_events_for_month(*month_key) 
                       if start_date <= parse_event_datetime(event, field='start') <= end_date]
            
            cached_events = [event for month_key in month_keys 
                            if self.cache.month_is_cached(*month_key)
                            for event in self.cache.get_events_for_month(*month_key)
                            if start_date <= parse_event_datetime(event, field='start') <= end_date]
            
            uncached_months = [m for m in month_keys if not self.cache.month_is_cached(*m)]
            new_events = []
            
            for month_key in uncached_months:
                year, month = month_key
                month_start = datetime(year, month, 1, tzinfo=timezone.utc)
                month_end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12 
                            else datetime(year, month + 1, 1, tzinfo=timezone.utc)) - timedelta(seconds=1)
                
                fetch_start = max(month_start, start_date)
                fetch_end = min(month_end, end_date)
                
                month_events = []
                next_token = None
                
                while True:
                    batch, next_token = self.fetch_events(
                        calendar_id=calendar_id,
                        max_results=API_MAX_RESULTS,
                        page_token=next_token,
                        start_date=fetch_start,
                        end_date=fetch_end
                    )
                    if not batch:
                        break
                    month_events.extend(batch)
                    if not next_token:
                        break
                
                self.cache.add_events(month_events)
                self.cache.mark_range_fetched(year, month)
                new_events.extend(month_events)
            
            existing_ids = set(event.get('id') for event in cached_events if event.get('id'))
            return cached_events + [event for event in new_events 
                                  if event.get('id') and event.get('id') not in existing_ids]
            
        except Exception as e:
            print(f"Error fetching events for range: {str(e)}")
            return []
        finally:
            with self.fetch_lock:
                self.fetching_ranges.discard(range_id)
    
    def _get_month_keys_in_range(self, start_date, end_date):
        """Generate all month keys (year, month) in a date range."""
        month_keys = []
        current = (start_date.year, start_date.month)
        end = (end_date.year, end_date.month)
        
        while True:
            month_keys.append(current)
            if current == end:
                break
            year, month = current
            current = (year + 1, 1) if month == 12 else (year, month + 1)
        
        return month_keys
    
    def clear_cache_for_month(self, year, month):
        """Clear the cache for a specific month to force refresh."""
        self.cache.clear_month(year, month)

    def add_event(self, calendar_id, event):
        """Add a new event to Google Calendar."""
        self._ensure_valid_token()
        
        try:
            result = self.service.events().insert(
                calendarId=calendar_id,
                body=event
            ).execute()
            
            self.cache.add_event(result)
            return result
        except Exception as e:
            print(f"Error adding event: {str(e)}")
            raise

    def update_event(self, calendar_id, event_id, updated_event):
        """Update an existing event in Google Calendar."""
        self._ensure_valid_token()
        
        try:
            result = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=updated_event
            ).execute()
            
            self.cache.add_event(result)
            return result
        except Exception as e:
            print(f"Error updating event: {str(e)}")
            raise

    def delete_event(self, calendar_id, event_id):
        """Delete an event from Google Calendar."""
        self._ensure_valid_token()
        
        try:
            result = self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            self.cache.delete_event(event_id)
            return result
        except Exception as e:
            print(f"Error deleting event: {str(e)}")
            raise

    def fetch_holidays(self, year, month):
        """Fetch holidays for a specific month from Google Calendar."""
        self._ensure_valid_token()
        
        month_key = (year, month)
        holidays = self.cache.get_holidays_for_month(year, month)
        if holidays:
            return holidays
            
        try:
            holiday_calendar_id = 'en.usa#holiday@group.v.calendar.google.com'
            
            start_date = datetime(year, month, 1, tzinfo=timezone.utc)
            if month == 12:
                end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
            end_date = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
            
            time_min = format_iso_for_api(start_date)
            time_max = format_iso_for_api(end_date)
            
            holidays_result = self.service.events().list(
                calendarId=holiday_calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            holidays = {}
            for item in holidays_result.get('items', []):
                if 'date' in item['start']:
                    event_date = datetime.fromisoformat(item['start']['date']).date()
                    holidays[event_date] = item['summary']
                    
            self.cache.add_holidays(year, month, holidays)
            return holidays
            
        except Exception as e:
            print(f"Error fetching holidays: {str(e)}")
            return {} 

# API WORKER THREAD
class APIWorker(QThread):
    """Worker thread for handling API calls without blocking the UI."""
    taskCompleted = pyqtSignal(object, object)
    taskError = pyqtSignal(Exception, object)
    loadingChanged = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = queue.Queue()
        self.running = True
        
    def add_task(self, task_type, func, **kwargs):
        """Add a task to the queue."""
        self.queue.put((task_type, func, kwargs))
            
        if not self.isRunning():
            self.start()
    
    def run(self):
        """Main worker loop that processes queued tasks."""
        while self.running:
            try:
                try:
                    task_type, func, kwargs = self.queue.get(block=True, timeout=0.5)
                except queue.Empty:
                    continue
                
                try:
                    if task_type not in ['background_fetch', 'preload']:
                        self.loadingChanged.emit(True)
                    
                    result = func(**kwargs)
                    
                    self.taskCompleted.emit(result, task_type)
                    
                except Exception as e:
                    print(f"Error in worker thread ({task_type}): {str(e)}")
                    self.taskError.emit(e, task_type)
                
                finally:
                    if task_type not in ['background_fetch', 'preload']:
                        self.loadingChanged.emit(False)
                    self.queue.task_done()
                    
            except Exception as e:
                print(f"Unexpected error in worker thread: {str(e)}")
                
        print("Worker thread stopped")
                
    def stop(self):
        """Stop the worker thread."""
        self.running = False
        self.wait(1000)

class TaskDialog(QDialog):
    """Dialog for creating and editing tasks."""
    def __init__(self, parent=None, on_confirm=None, task=None):
        super().__init__(parent)
        self.on_confirm = on_confirm
        self.task = task
        
        self.setWindowTitle("Task Dialog")
        self.setFixedSize(DEFAULT_DIALOG_WIDTH, DEFAULT_DIALOG_HEIGHT)
        
        if parent:
            parent_rect = parent.geometry()
            x = parent_rect.x() + (parent_rect.width() - DEFAULT_DIALOG_WIDTH) // 2
            y = parent_rect.y() + (parent_rect.height() - DEFAULT_DIALOG_HEIGHT) // 2
            self.setGeometry(x, y, DEFAULT_DIALOG_WIDTH, DEFAULT_DIALOG_HEIGHT)
        
        self.setup_initial_time()
        
        self.init_ui()
        
    def setup_initial_time(self):
        """Set up initial time values."""
        self.initial_hour = 9
        self.initial_min = 0
        self.initial_period = "AM"
        
        if self.task:
            local_start = self.task.start_dt.astimezone()
            local_end = self.task.end_dt.astimezone()
            
            self.initial_hour, self.initial_period = convert_from_24(str(local_start.hour))
            self.initial_min = local_start.minute
            
            self.initial_date = local_start.date()
        else:
            now = datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            hour_12, period = convert_from_24(str(next_hour.hour))
            self.initial_hour = hour_12
            self.initial_min = 0
            self.initial_period = period
            
            self.initial_date = now.date()
            
    def init_ui(self):
        """Create and arrange all dialog widgets."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        header_text = "Edit Task" if self.task else "Add New Task"
        header_label = QLabel(header_text)
        header_font = QFont(FONT_HEADER, FONT_HEADER_SIZE)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)
        
        summary_label = QLabel("Task Summary:")
        summary_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        main_layout.addWidget(summary_label)
        
        self.summary_edit = QLineEdit()
        self.summary_edit.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        if self.task:
            self.summary_edit.setText(self.task.summary)
        main_layout.addWidget(self.summary_edit)
        
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        if hasattr(self, 'initial_date'):
            self.calendar.setSelectedDate(QDate(
                self.initial_date.year,
                self.initial_date.month,
                self.initial_date.day
            ))
        main_layout.addWidget(self.calendar)
        
        time_frame = QFrame()
        time_layout = QGridLayout(time_frame)
        time_layout.setSpacing(5)
        
        start_label = QLabel("Start Time:")
        start_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        time_layout.addWidget(start_label, 0, 0)
        
        start_time_layout = QHBoxLayout()
        
        self.start_hour = QSpinBox()
        self.start_hour.setRange(1, 12)
        self.start_hour.setValue(self.initial_hour)
        self.start_hour.setFixedWidth(60)
        self.start_hour.valueChanged.connect(self.update_end_time)
        start_time_layout.addWidget(self.start_hour)
        
        time_layout.addWidget(QLabel(":"), 0, 1)
        
        self.start_min = QSpinBox()
        self.start_min.setRange(0, 59)
        self.start_min.setValue(self.initial_min)
        self.start_min.setFixedWidth(60)
        self.start_min.setSingleStep(5)
        self.start_min.valueChanged.connect(self.update_end_time)
        start_time_layout.addWidget(self.start_min)
        
        self.start_period = QComboBox()
        self.start_period.addItems(["AM", "PM"])
        self.start_period.setCurrentText(self.initial_period)
        self.start_period.currentTextChanged.connect(self.update_end_time)
        start_time_layout.addWidget(self.start_period)
        
        time_layout.addLayout(start_time_layout, 0, 2)
        
        end_label = QLabel("End Time:")
        end_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        time_layout.addWidget(end_label, 1, 0)
        
        end_time_layout = QHBoxLayout()
        
        self.end_hour = QSpinBox()
        self.end_hour.setRange(1, 12)
        self.end_hour.setFixedWidth(60)
        end_time_layout.addWidget(self.end_hour)
        
        time_layout.addWidget(QLabel(":"), 1, 1)
        
        self.end_min = QSpinBox()
        self.end_min.setRange(0, 59)
        self.end_min.setFixedWidth(60)
        self.end_min.setSingleStep(5)
        end_time_layout.addWidget(self.end_min)
        
        self.end_period = QComboBox()
        self.end_period.addItems(["AM", "PM"])
        end_time_layout.addWidget(self.end_period)
        
        time_layout.addLayout(end_time_layout, 1, 2)
        
        main_layout.addWidget(time_frame)
        
        button_layout = QHBoxLayout()
        
        if self.task and self.task.task_id:
            delete_btn = QPushButton("Delete")
            delete_btn.setStyleSheet("background-color: #AA3333; color: white;")
            delete_btn.clicked.connect(self.delete_task)
            button_layout.addWidget(delete_btn)
            
            confirm_btn = QPushButton("Save")
            confirm_btn.clicked.connect(self.confirm)
            button_layout.addWidget(confirm_btn)
        else:
            confirm_btn = QPushButton("Create")
            confirm_btn.clicked.connect(self.confirm)
            button_layout.addWidget(confirm_btn)
        
        main_layout.addLayout(button_layout)
        
        if self.task:
            self.init_time_fields()
        else:
            self.update_end_time()
            
    def init_time_fields(self):
        """Initialize time fields when editing an existing task."""
        local_start = self.task.start_dt.astimezone()
        local_end = self.task.end_dt.astimezone()
        
        self.calendar.setSelectedDate(QDate(
            local_start.year,
            local_start.month, 
            local_start.day
        ))
        
        start_hour, start_period = convert_from_24(str(local_start.hour))
        self.start_hour.setValue(start_hour)
        self.start_min.setValue(local_start.minute)
        self.start_period.setCurrentText(start_period)
        
        end_hour, end_period = convert_from_24(str(local_end.hour))
        self.end_hour.setValue(end_hour)
        self.end_min.setValue(local_end.minute)
        self.end_period.setCurrentText(end_period)
            
    def update_end_time(self):
        """Update end time to be 1 hour after start time."""
        try:
            start_hour = self.start_hour.value()
            start_min = self.start_min.value()
            start_period = self.start_period.currentText()
            
            start_hour_24 = convert_to_24(str(start_hour), start_period)
            
            end_hour_24 = (start_hour_24 + 1) % 24
            
            end_hour_12, end_period = convert_from_24(str(end_hour_24))
            
            self.end_hour.setValue(end_hour_12)
            self.end_min.setValue(start_min)
            self.end_period.setCurrentText(end_period)
        except (ValueError, TypeError) as e:
            print(f"Error updating end time: {str(e)}")
            
    def delete_task(self):
        """Delete the current task."""
        if self.task and self.task.task_id:
            parent = self.parent()
            if parent and hasattr(parent, 'delete_task'):
                parent.delete_task(self.task)
            self.accept()
            
    def confirm(self):
        """Validate input and create/update task."""
        summary = self.summary_edit.text().strip()
        if not summary:
            QMessageBox.warning(self, "Warning", "Task summary cannot be empty.")
            return
            
        selected_date = self.calendar.selectedDate()
        date_str = f"{selected_date.year()}-{selected_date.month():02d}-{selected_date.day():02d}"
        
        try:
            start_hour_24 = convert_to_24(str(self.start_hour.value()), self.start_period.currentText())
            end_hour_24 = convert_to_24(str(self.end_hour.value()), self.end_period.currentText())
            
            local_tz = datetime.now().astimezone().tzinfo
            start_dt_local = datetime.strptime(
                f"{date_str} {start_hour_24:02d}:{self.start_min.value():02d}", 
                "%Y-%m-%d %H:%M"
            )
            start_dt_local = start_dt_local.replace(tzinfo=local_tz)
            start_dt = local_to_utc(start_dt_local)
            
            end_dt_local = datetime.strptime(
                f"{date_str} {end_hour_24:02d}:{self.end_min.value():02d}", 
                "%Y-%m-%d %H:%M"
            )
            end_dt_local = end_dt_local.replace(tzinfo=local_tz)
            end_dt = local_to_utc(end_dt_local)
            
            if end_dt <= start_dt:
                QMessageBox.warning(self, "Warning", "End time must be after start time.")
                return
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Invalid date or time: {str(e)}")
            return
            
        if self.task:
            self.task.summary = summary
            self.task.start_dt = start_dt
            self.task.end_dt = end_dt
        else:
            self.task = Task(summary, start_dt, end_dt)
            
        if self.on_confirm:
            self.on_confirm(self.task)
            
        self.accept() 

class ReminderManager(QObject):
    """Manages task reminders and notifications."""
    reminderReady = pyqtSignal(Task)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.reminders = []
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_reminders)
        self.timer.start(60000)
        
    def add_reminder(self, task):
        """Add a task to the reminder list."""
        self.reminders.append(task)
        
    def check_reminders(self):
        """Check if any reminders need to be shown."""
        now = datetime.now(timezone.utc)
        for task in self.reminders:
            if task.status == 'Pending' and (task.start_dt - now) <= timedelta(minutes=task.reminder_minutes) and (task.start_dt - now) > timedelta(0):
                self.reminderReady.emit(task)

class TodoApp(QMainWindow):
    """Main application window."""
    def __init__(self, calendar_manager):
        super().__init__()
        self.calendar_manager = calendar_manager
        
        self.setWindowTitle("To-Do List")
        self.resize(*DEFAULT_WINDOW_SIZE)
        
        self.setStyleSheet(MAIN_STYLE)
        
        self.current_view = "daily"
        today = datetime.now().date()
        self.displayed_year, self.displayed_month = today.year, today.month
        
        self.loading = False
        
        self.init_ui()
        
        self.worker = APIWorker(self)
        self.worker.taskCompleted.connect(self.on_task_completed)
        self.worker.taskError.connect(self.on_task_error)
        self.worker.loadingChanged.connect(self.on_loading_changed)
        
        self.reminder_manager = ReminderManager(self)
        self.reminder_manager.reminderReady.connect(self.show_reminder)
        
        self.refresh_events()
        
    def init_ui(self):
        """Initialize the main UI components."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.init_navbar(main_layout)
        
        self.init_main_content(main_layout)
        
    def init_navbar(self, parent_layout):
        """Initialize the navigation bar."""
        navbar = QFrame()
        navbar.setStyleSheet(f"background-color: {NAV_BG_COLOR};")
        navbar.setMinimumHeight(60)
        
        nav_layout = QHBoxLayout(navbar)
        nav_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        
        title_label = QLabel("CS 220 To-Do List")
        title_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE, QFont.Weight.Bold))
        nav_layout.addWidget(title_label)
        
        search_frame = QFrame()
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search tasks...")
        self.search_entry.textChanged.connect(self.filter_content)
        search_layout.addWidget(self.search_entry)
        
        nav_layout.addWidget(search_frame, 1)
        
        today_button = QPushButton("Today")
        today_button.clicked.connect(self.scroll_to_today)
        nav_layout.addWidget(today_button)
        
        view_selector = QComboBox()
        view_selector.addItems(["Daily View", "Monthly View"])
        view_selector.currentTextChanged.connect(self.switch_view)
        nav_layout.addWidget(view_selector)
        
        add_button = QPushButton("Add Task")
        add_button.clicked.connect(lambda: self.open_task_dialog())
        nav_layout.addWidget(add_button)
        
        parent_layout.addWidget(navbar)
        
    def init_main_content(self, parent_layout):
        """Initialize the main content area with stacked views."""
        self.views_stack = QStackedWidget()
        
        self.daily_view = QScrollArea()
        self.daily_view.setWidgetResizable(True)
        self.daily_content = QWidget()
        self.daily_layout = QVBoxLayout(self.daily_content)
        self.daily_layout.setSpacing(PADDING//2)
        self.daily_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        self.daily_view.setWidget(self.daily_content)
        
        self.monthly_view = QWidget()
        self.monthly_layout = QVBoxLayout(self.monthly_view)
        self.monthly_layout.setSpacing(0)
        self.monthly_layout.setContentsMargins(0, 0, 0, 0)
        
        self.views_stack.addWidget(self.daily_view)
        self.views_stack.addWidget(self.monthly_view)
        
        parent_layout.addWidget(self.views_stack, 1)
        
    def on_task_completed(self, result, task_type):
        """Handle completed tasks from worker thread."""
        if task_type == "fetch_events":
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            if next_token:
                self._fetch_next_page(next_token)
            else:
                self._update_current_view()
                
        elif task_type == "background_fetch":
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            if next_token:
                self._fetch_next_page(next_token)
            else:
                self._update_current_view()
                
        elif task_type == "fetch_month":
            if self.current_view == "monthly":
                search_term = self.search_entry.text() if hasattr(self, 'search_entry') else ""
                tasks_by_date = self.calendar_manager.cache.get_tasks_for_month(self.displayed_year, self.displayed_month)
                
                self._update_calendar_cells(tasks_by_date, search_term)
            else:
                self._update_current_view()
            
        elif task_type == "fetch_holidays":
            self._update_holidays(result)
            
        elif task_type == "create_task" or task_type == "update_task":
            action = "created" if task_type == "create_task" else "updated"
            self.show_alert(f"Task {action}: {result['summary']}", duration=3000)
            
            self._update_current_view()
            
        elif task_type == "delete_task":
            self.show_alert(f"Task deleted", duration=3000)
            
            self._update_current_view()
        
    def on_task_error(self, error, task_type):
        """Handle errors from worker thread."""
        if task_type == "fetch_events":
            self.show_alert(f"Error fetching events: {str(error)}", duration=4000)
            self._update_current_view()
            
        elif task_type in ["create_task", "update_task"]:
            action = "create" if task_type == "create_task" else "update"
            self.show_alert(f"Failed to {action} task: {str(error)}", duration=4000)
            
        elif task_type == "delete_task":
            self.show_alert(f"Failed to delete task: {str(error)}", duration=4000)
            
        else:
            self.show_alert(f"Error in {task_type}: {str(error)}", duration=4000)
            
    def on_loading_changed(self, is_loading):
        """Handle loading state changes."""
        self.loading = is_loading
        if is_loading:
            print("Loading started")
        else:
            print("Loading finished")
            
    def show_alert(self, message, duration=3000):
        """Log alerts to console."""
        print(f"INFO: {message}")
        
    def show_reminder(self, task):
        """Show a reminder notification for a task."""
        time_str = format_task_time(task.start_dt, task.end_dt)
        self.show_alert(f"Reminder: {task.summary} at {time_str}", duration=5000)
        
    def refresh_events(self):
        """Refresh events from Google Calendar."""
        now = datetime.now()
        start_date = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        
        self.worker.add_task(
            "fetch_events",
            self.calendar_manager.fetch_events,
            calendar_id='primary',
            max_results=50,
            start_date=start_date
        )

    def _fetch_next_page(self, page_token):
        """Fetch the next page of events."""
        self.worker.add_task(
            "background_fetch",
            self.calendar_manager.fetch_events,
            calendar_id='primary',
            max_results=50,
            page_token=page_token
        )
        
    def _update_current_view(self):
        """Update the current view after data has been loaded."""
        if self.current_view == "daily":
            self.build_daily_view(self.search_entry.text() if hasattr(self, 'search_entry') else "")
        elif self.current_view == "monthly":
            self._update_monthly_view_data(self.search_entry.text() if hasattr(self, 'search_entry') else "")
        
    def _process_loaded_events(self, events):
        """Process loaded events and update the cache."""
        added_count = 0
        
        for event in events:
            event_id = event.get('id')
            
            if event_id and self.calendar_manager.cache.has_event_id(event_id):
                continue
                
            self.calendar_manager.cache.add_event(event)
            added_count += 1
            
            task = self.calendar_manager.cache._convert_event_to_task(event)
            if task:
                self.reminder_manager.add_reminder(task)
        
        if added_count > 0:
            self._update_current_view()
            
    def get_filtered_tasks_by_date(self, search_term=""):
        """Get tasks filtered by search term, organized by date."""
        tasks_by_date = self._get_tasks_by_date_dict()

        if not search_term:
            return tasks_by_date
        
        search_term = search_term.lower()
        return {date: [task for task in tasks if search_term in task.summary.lower()] 
                for date, tasks in tasks_by_date.items() 
                if any(search_term in task.summary.lower() for task in tasks)}
    
    def _get_tasks_by_date_dict(self):
        """Get tasks organized by date from the cache."""
        return self.calendar_manager.cache.tasks_by_date.copy()
            
    def build_daily_view(self, search_term=""):
        """Build the daily view with all tasks organized by date."""
        self.clear_widget(self.daily_content)
        
        tasks_by_date = self.get_filtered_tasks_by_date(search_term)
        
        sorted_dates = sorted(tasks_by_date.keys())
        
        if not sorted_dates:
            no_tasks_label = QLabel("No tasks found for this period")
            no_tasks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_tasks_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE))
            self.daily_layout.addWidget(no_tasks_label)
            self.daily_layout.addStretch(1)
            return
            
        tasks_by_month = {}
        for day, tasks in tasks_by_date.items():
            month_key = (day.year, day.month)
            if month_key not in tasks_by_month:
                tasks_by_month[month_key] = []
            tasks_by_month[month_key].extend(tasks)
            
        self.month_containers = {}
        
        current_month = None
        current_year = None
        
        for day in sorted_dates:
            if current_year != day.year or current_month != day.month:
                month_key = (day.year, day.month)
                task_count = len(tasks_by_month.get(month_key, []))
                
                self.create_month_separator(day, task_count)
                
                current_month = day.month
                current_year = day.year
                
            month_key = (day.year, day.month)
            if month_key in self.month_containers:
                self.create_day_content(day, tasks_by_date[day], self.month_containers[month_key]['container'])
                
    def create_month_separator(self, day, task_count):
        """Create a month/year separator with a simple text header."""
        month_key = (day.year, day.month)
        
        separator_frame = QFrame()
        separator_frame.setStyleSheet("background-color: #262640;")
        separator_frame.setMinimumHeight(40)
        self.daily_layout.addWidget(separator_frame)
        
        separator_layout = QVBoxLayout(separator_frame)
        separator_layout.setContentsMargins(PADDING, PADDING//2, PADDING, PADDING//2)
        separator_layout.setSpacing(0)
        
        header_layout = QHBoxLayout()
        
        month_year_text = format_datetime(day, 'month_year')
        task_count_text = f"({task_count} task{'s' if task_count != 1 else ''})"
        
        month_label = QLabel(f"📅  {month_year_text}")
        month_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE, QFont.Weight.Bold))
        header_layout.addWidget(month_label, 1)
        
        count_label = QLabel(task_count_text)
        count_label.setStyleSheet("color: #AAAAFF;")
        count_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        header_layout.addWidget(count_label)
        
        separator_layout.addLayout(header_layout)
        
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background-color: #3A3A5C;")
        divider.setFixedHeight(2)
        separator_layout.addWidget(divider)
        
        month_container = QWidget()
        month_layout = QVBoxLayout(month_container)
        month_layout.setContentsMargins(0, 0, 0, 0)
        month_layout.setSpacing(PADDING//2)
        
        self.daily_layout.addWidget(month_container)
        
        self.month_containers[month_key] = {
            'frame': separator_frame,
            'header_label': month_label,
            'container': month_container,
            'expanded': True
        }
            
    def create_day_content(self, day, tasks, parent_container):
        """Create the content for a single day."""
        day_frame = QFrame()
        day_frame.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")
        
        day_layout = QHBoxLayout(day_frame)
        day_layout.setContentsMargins(PADDING, PADDING//2, PADDING, PADDING//2)
        
        date_strip = self.create_date_strip(day)
        day_layout.addWidget(date_strip)
        
        tasks_container = QWidget()
        tasks_layout = QVBoxLayout(tasks_container)
        tasks_layout.setContentsMargins(PADDING, 0, 0, 0)
        tasks_layout.setSpacing(PADDING//2)
        
        for task in tasks:
            task_card = self.create_task_card(task, False)
            tasks_layout.addWidget(task_card)
            
        day_layout.addWidget(tasks_container, 1)
        
        parent_layout = parent_container.layout()
        parent_layout.addWidget(day_frame)
        
    def create_date_strip(self, day):
        """Create the date strip showing weekday and date."""
        date_strip = QWidget()
        date_strip.setMinimumWidth(50)
        
        strip_layout = QVBoxLayout(date_strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(0)
        
        weekday_label = QLabel(format_datetime(day, 'weekday'))
        weekday_label.setFont(QFont(FONT_DAY, FONT_DAY_SIZE, QFont.Weight.Bold))
        weekday_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        strip_layout.addWidget(weekday_label)
        
        day_label = QLabel(format_datetime(day, 'day'))
        day_label.setFont(QFont(FONT_DATE, FONT_DATE_SIZE, QFont.Weight.Bold))
        day_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        strip_layout.addWidget(day_label)
        
        strip_layout.addStretch(1)
        
        return date_strip
        
    def create_task_card(self, task, is_monthly_view=False):
        """Create a card for displaying a task."""
        task_card = QFrame()
        
        if is_monthly_view:
            task_card.setStyleSheet("background-color: transparent; border: none;")
            task_card.setFixedHeight(18)
            task_card.setMaximumWidth(170)
        else:
            task_card.setStyleSheet(f"background-color: {CARD_COLOR}; border-radius: 6px;")
        
        task_card.mousePressEvent = lambda e, t=task: self.open_task_dialog(t)
        
        card_layout = QHBoxLayout(task_card) if is_monthly_view else QVBoxLayout(task_card)
        
        if is_monthly_view:
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(2)
        else:
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(4)
        
        time_str = format_task_time(task.start_dt, task.end_dt)
        
        summary = task.summary
        if is_monthly_view and len(summary) > 15:
            display_summary = f"{summary[:15]}..."
        else:
            display_summary = summary
            
        if is_monthly_view:
            local_start = task.start_dt.astimezone()
            bullet_color = "#50A0FF"
            
            if local_start.hour < 12:
                bullet_color = "#60C060"
            elif local_start.hour >= 17:
                bullet_color = "#FF8050"
                
            bullet_label = QLabel("•")
            bullet_label.setStyleSheet(f"color: {bullet_color}; font-weight: bold; font-size: 14px; background: transparent; border: none;")
            bullet_label.setFixedWidth(15)
            card_layout.addWidget(bullet_label)
            
            start_time = format_datetime(local_start, 'time', include_minutes=False)
            time_label = QLabel(start_time)
            time_label.setStyleSheet(f"color: {bullet_color}; background: transparent; border: none;")
            time_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 2))
            time_label.setFixedWidth(45)
            card_layout.addWidget(time_label)
            
            task_label = QLabel(display_summary)
            task_label.setStyleSheet("color: white; background: transparent; border: none;")
            task_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 1))
            task_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            task_label.setWordWrap(False)
            card_layout.addWidget(task_label, 1)
        else:
            summary_label = QLabel(display_summary)
            summary_label.setStyleSheet("color: white;")
            summary_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
            summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(summary_label)
            
            time_label = QLabel(time_str)
            time_label.setStyleSheet("color: white;")
            time_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE))
            time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(time_label)
            
        return task_card
        
    def clear_widget(self, widget):
        """Clear all child widgets from a container."""
        if widget is None:
            return
            
        layout = widget.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    self.clear_widget(item.widget())
    
    def filter_content(self):
        """Filter view content based on search term."""
        search_term = self.search_entry.text()
        if self.current_view == "daily":
            self.build_daily_view(search_term)
        elif self.current_view == "monthly":
            self._update_monthly_view_data(search_term)
            
    def switch_view(self, view):
        """Switch between different views."""
        if view == "Daily View":
            self.current_view = "daily"
            self.views_stack.setCurrentIndex(0)
            self.build_daily_view(self.search_entry.text())
            QTimer.singleShot(100, self.scroll_to_today)
        elif view == "Monthly View":
            self.current_view = "monthly"
            self.views_stack.setCurrentIndex(1)
            if not self.monthly_view.layout().count():
                self._create_monthly_view_structure()
            self._update_monthly_view_data(self.search_entry.text())
            QTimer.singleShot(100, self.scroll_to_today)
            
    def open_task_dialog(self, task=None):
        """Open dialog to create or edit a task."""
        dialog = TaskDialog(self, self.on_task_dialog_confirm, task)
        dialog.exec()
        
    def open_task_dialog_for_date(self, date):
        """Open task dialog pre-set for a specific date."""
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime.now()
        
        if now.minute > 0 or now.second > 0:
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_hour = now
            
        start_dt = datetime.combine(date, next_hour.time())
        start_dt = start_dt.replace(tzinfo=local_tz)
        start_dt_utc = local_to_utc(start_dt)
        
        end_dt_utc = start_dt_utc + timedelta(hours=1)

        temp_task = Task("", start_dt_utc, end_dt_utc)
        self.open_task_dialog(temp_task)
        
    def on_task_dialog_confirm(self, task):
        """Handle confirmed task from dialog."""
        event = {
            'summary': task.summary,
            'start': {'dateTime': format_iso_for_api(task.start_dt), 'timeZone': 'UTC'},
            'end': {'dateTime': format_iso_for_api(task.end_dt), 'timeZone': 'UTC'}
        }
        
        if task.task_id:
            self.worker.add_task(
                "update_task",
                self.calendar_manager.update_event,
                calendar_id='primary',
                event_id=task.task_id,
                updated_event=event
            )
        else:
            self.worker.add_task(
                "create_task",
                self.calendar_manager.add_event,
                calendar_id='primary',
                event=event
            )
            
    def delete_task(self, task):
        """Delete a task from the calendar."""
        if not task or not task.task_id:
            self.show_alert("Cannot delete task: no task ID", duration=3000)
            return
            
        self.worker.add_task(
            "delete_task",
            self.calendar_manager.delete_event,
            calendar_id='primary',
            event_id=task.task_id
        )

    def _create_monthly_view_structure(self):
        """Create the static widgets for the monthly view."""
        self.clear_widget(self.monthly_view)
        self._create_month_header()
        self._create_calendar_grid()
        
    def _create_month_header(self):
        """Create the month navigation header."""
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background-color: {NAV_BG_COLOR};")
        header_frame.setMinimumHeight(50)
        
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        
        prev_button = QPushButton("<")
        prev_button.setFixedWidth(40)
        prev_button.clicked.connect(self.prev_month)
        header_layout.addWidget(prev_button)
        
        month_date = datetime(self.displayed_year, self.displayed_month, 1)
        self.month_year_label = QLabel(format_datetime(month_date, 'month_year'))
        self.month_year_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE, QFont.Weight.Bold))
        self.month_year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.month_year_label, 1)
        
        next_button = QPushButton(">")
        next_button.setFixedWidth(40)
        next_button.clicked.connect(self.next_month)
        header_layout.addWidget(next_button)
        
        self.monthly_layout.addWidget(header_frame)
        
    def _create_calendar_grid(self):
        """Create the calendar grid for monthly view."""
        grid_container = QFrame()
        grid_container.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")
        
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(1)
        
        days_of_week = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        for col, day_name in enumerate(days_of_week):
            day_header = QFrame()
            day_header.setStyleSheet("background-color: #1A1A2E;")
            day_header.setMinimumHeight(25)
            day_header.setMaximumHeight(25)
            
            header_layout = QVBoxLayout(day_header)
            header_layout.setContentsMargins(5, 2, 5, 2)
            
            label = QLabel(day_name)
            label.setFont(QFont(FONT_DAY, FONT_DAY_SIZE, QFont.Weight.Bold))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(label)
            
            grid_layout.addWidget(day_header, 0, col)
        
        self.calendar_cells = {}
        
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        num_weeks = len(month_calendar)
        
        for row_idx in range(num_weeks):
            for col_idx in range(7):
                cell = self._create_calendar_cell(row_idx, col_idx)
                grid_layout.addWidget(cell, row_idx + 1, col_idx)
                
        for col in range(7):
            grid_layout.setColumnStretch(col, 1)
        for row in range(num_weeks):
            grid_layout.setRowStretch(row + 1, 1)
            
        self.monthly_layout.addWidget(grid_container, 1)
        
    def _create_calendar_cell(self, row, col):
        """Create a single calendar cell."""
        cell = QFrame()
        cell.setStyleSheet(f"background-color: {BACKGROUND_COLOR}; border: 1px solid #333344;")
        cell.setMinimumSize(180, 120)
        
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(2, 2, 2, 2)
        cell_layout.setSpacing(1)
        
        day_label = QLabel("")
        day_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        day_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        day_label.setFixedHeight(35)
        cell_layout.addWidget(day_label)
        
        tasks_container = QFrame()
        tasks_container.setStyleSheet("background: transparent; border: none;")
        tasks_layout = QVBoxLayout(tasks_container)
        tasks_layout.setContentsMargins(2, 0, 2, 0)
        tasks_layout.setSpacing(1)
        cell_layout.addWidget(tasks_container, 1) 
        
        self.calendar_cells[(row, col)] = {
            'frame': cell,
            'day_label': day_label,
            'tasks_container': tasks_container,
            'current_state': {
                'date': None,
                'tasks': [],
                'holiday': None,
                'is_current_month': False,
                'is_today': False
            }
        }
        
        cell.mousePressEvent = lambda e, r=row, c=col: self._on_cell_clicked(r, c)
        return cell
        
    def _on_cell_clicked(self, row, col):
        """Handle calendar cell click to create a new task."""
        cell_data = self.calendar_cells.get((row, col))
        if cell_data and cell_data['current_state']['date']:
            self.open_task_dialog_for_date(cell_data['current_state']['date'])
            
    def _update_monthly_view_data(self, search_term="", force_refresh=False):
        """Update the monthly view with current month's data."""
        if hasattr(self, 'month_year_label'):
            month_date = datetime(self.displayed_year, self.displayed_month, 1)
            self.month_year_label.setText(format_datetime(month_date, 'month_year'))
            
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        
        self._setup_calendar_cell_dates(month_calendar)
        
        start_date, end_date = self._get_month_date_range(self.displayed_year, self.displayed_month)
        
        tasks_by_date = self.calendar_manager.cache.get_tasks_for_month(self.displayed_year, self.displayed_month)
        
        if tasks_by_date and not force_refresh:
            self._update_calendar_cells(tasks_by_date, search_term)
        else:
            if force_refresh:
                self.calendar_manager.clear_cache_for_month(self.displayed_year, self.displayed_month)
            
            self.worker.add_task(
                "fetch_month",
                self.calendar_manager.fetch_events_for_range,
                start_date=start_date,
                end_date=end_date
            )
        
        holidays = self.calendar_manager.cache.get_holidays_for_month(self.displayed_year, self.displayed_month)
        if not holidays or force_refresh:
            self.worker.add_task(
                "fetch_holidays",
                self.calendar_manager.fetch_holidays,
                year=self.displayed_year,
                month=self.displayed_month
            )
         
    def _setup_calendar_cell_dates(self, month_calendar):
        """Set up date numbers in calendar cells."""
        today = datetime.now().date()
        
        row_idx = 0
        for week in month_calendar:
            for col_idx, day_num in enumerate(week):
                cell_data = self.calendar_cells.get((row_idx, col_idx))
                if not cell_data:
                    continue
                    
                if day_num == 0:
                    cell_data['frame'].setStyleSheet("background-color: #1E1E2F; border: 1px solid #333344;")
                    cell_data['day_label'].setText("")
                    cell_data['current_state']['is_current_month'] = False
                    cell_data['current_state']['date'] = None
                    continue
                    
                current_date = datetime(self.displayed_year, self.displayed_month, day_num).date()
                
                date_changed = cell_data['current_state']['date'] != current_date
                today_changed = (current_date == today) != cell_data['current_state']['is_today']
                
                cell_data['current_state']['date'] = current_date
                cell_data['current_state']['is_current_month'] = True
                cell_data['current_state']['is_today'] = (current_date == today)
                
                if date_changed or today_changed:
                    self.clear_widget(cell_data['tasks_container'])
                    cell_data['current_state']['tasks'] = []
                    cell_data['current_state']['holiday'] = None
                
                self._configure_cell_appearance(cell_data, current_date, day_num, today)
                
            row_idx += 1
            
    def _configure_cell_appearance(self, cell_data, current_date, day_num, today):
        """Configure the appearance of a calendar cell."""
        if current_date == today:
            cell_data['frame'].setStyleSheet(f"background-color: #2D2D4D; border: 2px solid {HIGHLIGHT_COLOR};")
            cell_data['day_label'].setStyleSheet("color: white; font-weight: bold;")
        else:
            cell_data['frame'].setStyleSheet(f"background-color: {BACKGROUND_COLOR}; border: 1px solid #333344;")
            cell_data['day_label'].setStyleSheet("")
            
        cell_data['day_label'].setText(str(day_num))
        
    def _update_holidays(self, holidays):
        """Update cells with holiday information."""
        if not holidays:
            return
            
        for date, holiday_name in holidays.items():
            for cell_key, cell_data in self.calendar_cells.items():
                if cell_data['current_state']['date'] == date:
                    if cell_data['current_state']['holiday'] != holiday_name:
                        cell_data['current_state']['holiday'] = holiday_name
                        self._add_holiday_to_cell(cell_data['tasks_container'], holiday_name)
                        
    def _add_holiday_to_cell(self, container, holiday_name):
        """Add a holiday indicator to a cell."""
        holiday_frame = QFrame()
        holiday_frame.setStyleSheet("background-color: transparent; border: none;")
        holiday_frame.setMaximumHeight(18)
        
        holiday_layout = QHBoxLayout(holiday_frame)
        holiday_layout.setContentsMargins(0, 0, 0, 0) 
        holiday_layout.setSpacing(1)
        
        if len(holiday_name) > 20:
            holiday_name = holiday_name[:17] + "..."
            
        holiday_label = QLabel(f"🎉 {holiday_name}")
        holiday_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 1))
        holiday_label.setStyleSheet("color: #CCCCFF; background: transparent; border: none;")
        holiday_layout.addWidget(holiday_label)
        
        container_layout = container.layout()
        
        for i in range(container_layout.count()):
            widget = container_layout.itemAt(i).widget()
            if widget and isinstance(widget, QFrame) and widget.layout() and widget.layout().count() > 0:
                label = widget.layout().itemAt(0).widget()
                if isinstance(label, QLabel) and label.text().startswith("🎉"):
                    widget.deleteLater()
                    break
                
        container_layout.insertWidget(0, holiday_frame)
        
    def _update_calendar_cells(self, tasks_by_date, search_term=""):
        """Update calendar cells with task data."""
        for cell_key, cell_data in self.calendar_cells.items():
            date = cell_data['current_state']['date']
            if not date or not cell_data['current_state']['is_current_month']:
                continue
                
            tasks = tasks_by_date.get(date, [])
            if search_term:
                tasks = [t for t in tasks if search_term.lower() in t.summary.lower()]

            container = cell_data['tasks_container']
            layout = container.layout()
            
            holiday_frames = []
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()

                if widget and isinstance(widget, QFrame) and widget.layout() and widget.layout().count() > 0:
                    first_child = widget.layout().itemAt(0).widget()
                    if isinstance(first_child, QLabel) and first_child.text().startswith("🎉"):
                        holiday_frames.append(widget)
                    else:
                        widget.deleteLater()
                else:
                    if widget:
                        widget.deleteLater()
                    
            while layout.count():
                item = layout.takeAt(0)
                if item.widget() not in holiday_frames:
                    if item.widget():
                        item.widget().deleteLater()
                        

            for frame in holiday_frames:
                layout.addWidget(frame)
                
            if tasks:
                sorted_tasks = sorted(tasks, key=lambda t: t.start_dt)
            
                layout.setSpacing(1)
                
                for i, task in enumerate(sorted_tasks[:MAX_TASKS_PER_CELL]):
                    task_card = self.create_task_card(task, True)
                    layout.addWidget(task_card)
                    
                if len(tasks) > MAX_TASKS_PER_CELL:
                    more_label = QLabel(f"+ {len(tasks) - MAX_TASKS_PER_CELL} more")
                    more_label.setStyleSheet("color: #CCCCFF; font-size: 9px; background: transparent; border: none;")
                    more_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 2))
                    more_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    more_label.setFixedHeight(15)
                    layout.addWidget(more_label)
            elif not holiday_frames:
                no_tasks_label = QLabel("No tasks")
                no_tasks_label.setStyleSheet("color: #888888; font-style: italic; background: transparent; border: none;")
                no_tasks_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE))
                no_tasks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(no_tasks_label)
                
            cell_data['current_state']['tasks'] = tasks
            
    def _get_month_date_range(self, year, month):
        """Calculate the start and end dates for a month."""
        start_date = datetime(year, month, 1, tzinfo=timezone.utc)
        
        if month == 12:
            end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
            
        return start_date, end_date
        
    def _get_prev_month(self, year, month):
        """Get the previous month's year and month values."""
        return (year - 1, 12) if month == 1 else (year, month - 1)
    
    def _get_next_month(self, year, month):
        """Get the next month's year and month values."""
        return (year + 1, 1) if month == 12 else (year, month + 1)
        
    def prev_month(self):
        """Navigate to the previous month."""
        self.displayed_year, self.displayed_month = self._get_prev_month(self.displayed_year, self.displayed_month)
        self._update_monthly_view_data(self.search_entry.text())
        
    def next_month(self):
        """Navigate to the next month."""
        self.displayed_year, self.displayed_month = self._get_next_month(self.displayed_year, self.displayed_month)
        self._update_monthly_view_data(self.search_entry.text())
        
    def closeEvent(self, event):
        """Handle window close event."""
        if hasattr(self, 'worker'):
            self.worker.stop()
        event.accept()
        
    def scroll_to_today(self):
        """Scroll to the current day in either daily or monthly view."""
        today = datetime.now().date()
        
        if self.current_view == "daily":
            month_key = (today.year, today.month)

            if month_key in self.month_containers:
                month_container = self.month_containers[month_key]['container']
                
                pos = month_container.pos().y()
                self.daily_view.verticalScrollBar().setValue(pos)
                
                for widget in month_container.findChildren(QFrame):
                    for child in widget.findChildren(QLabel):
                        if child.text() == format_datetime(today, 'day') and pos > 0:
                            day_pos = widget.pos().y() + pos
                            self.daily_view.verticalScrollBar().setValue(day_pos)
                            return
        
        elif self.current_view == "monthly":
            if today.year != self.displayed_year or today.month != self.displayed_month:
                self.displayed_year = today.year
                self.displayed_month = today.month
                self._update_monthly_view_data(self.search_entry.text())

# APPLICATION ENTRY POINT
if __name__ == "__main__":
    # Initialize services
    auth_service = GoogleAuthService(SCOPES)
    calendar_manager = CalendarManager(auth_service)
    
    # Create and start the application
    app = QApplication(sys.argv)
    
    # Set style to fusion for better cross-platform appearance
    app.setStyle("Fusion")
    
    # Create and show main window
    main_window = TodoApp(calendar_manager)
    main_window.show()
    
    # Start the event loop
    sys.exit(app.exec()) 