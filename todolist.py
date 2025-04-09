import os
import calendar
from datetime import datetime, timezone, timedelta
import customtkinter as ctk
import pytz
from tkinter import Spinbox
from tkcalendar import Calendar
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import threading
import queue


# Set calendar to use Sunday as the first day of the week
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
ERROR_COLOR = "#FF5555"
SUCCESS_COLOR = "#55FF55"
HIGHLIGHT_COLOR = "#6060A0"

# Fonts
FONT_HEADER = ("Helvetica Neue", 18, "bold")
FONT_LABEL = ("Helvetica Neue", 14)
FONT_SMALL = ("Helvetica Neue", 12)
FONT_DAY = ("Helvetica Neue", 12, "bold")
FONT_DATE = ("Helvetica Neue", 18, "bold")
PADDING = 10

# UI Constants
DEFAULT_ALERT_DURATION = 3000
DEFAULT_ERROR_DURATION = 4000
DEFAULT_DIALOG_WIDTH = 400
DEFAULT_DIALOG_HEIGHT = 500
DEFAULT_WINDOW_SIZE = "1200x1000"
MAX_TASKS_PER_CELL = 3

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

def utc_to_local(utc_str):
    """Convert UTC datetime string to local datetime object."""
    return datetime.fromisoformat(utc_str.replace("Z", "+00:00")).astimezone()

def local_to_utc(local_dt):
    """Convert local datetime object to UTC datetime object."""
    return local_dt.astimezone(timezone.utc)

def format_task_time(start_dt, end_dt):
    """Format task start and end time consistently."""
    local_start = start_dt.astimezone()
    local_end = end_dt.astimezone()
    
    if local_start.hour == 0 and local_start.minute == 0 and local_end.hour == 23 and local_end.minute == 59:
        return "All Day"
    else:
        start_str = local_start.strftime('%I:%M %p').lstrip('0')
        end_str = local_end.strftime('%I:%M %p').lstrip('0')
        return f"{start_str} - {end_str}"

def parse_event_datetime(event, field='start', as_date=False):
    """Parse datetime from a Google Calendar event field."""
    if field not in event:
        return datetime.now(timezone.utc)  # Fallback
        
    if 'dateTime' in event[field]:
        # Regular event with specific time
        dt = datetime.fromisoformat(event[field]['dateTime'].replace('Z', '+00:00'))
        return dt.date() if as_date else dt
    elif 'date' in event[field]:
        # All-day event
        local_date = datetime.fromisoformat(event[field]['date']).date()
        if as_date:
            return local_date
            
        # For all-day events, start is beginning of day, end is end of day
        local_dt = datetime.combine(local_date, 
                                    datetime.min.time() if field == 'start' else datetime.max.time())
        # Make timezone-aware
        return local_dt.astimezone().astimezone(timezone.utc)
        
    return datetime.now(timezone.utc)  # Fallback


# GOOGLE API CLASSES
class CacheManager:
    """Centralized cache manager for all calendar data."""
    def __init__(self):
        self.events_by_month = {}  # {(year, month): [events]}
        self.tasks_by_date = {}    # {date: [tasks]}
        self.holidays_by_month = {} # {(year, month): {date: holiday_name}}
        self.cache_lock = threading.Lock()
        self.fetched_ranges = set()
        self.event_ids = set()  # Set to track all event IDs
        
    def add_event(self, event):
        """Add or update an event in the cache."""
        with self.cache_lock:
            event_start = parse_event_datetime(event, field='start')
            month_key = (event_start.year, event_start.month)
            
            # Update events cache
            if month_key not in self.events_by_month:
                self.events_by_month[month_key] = []
                
            # Remove existing event with same ID if present
            event_id = event.get('id')
            if event_id:
                self.events_by_month[month_key] = [e for e in self.events_by_month[month_key] 
                                                  if e.get('id') != event_id]
                self.event_ids.add(event_id)
                
            # Add the new/updated event
            self.events_by_month[month_key].append(event)
            
            # Also update the tasks cache
            task = self._convert_event_to_task(event)
            if task:
                local_date = task.start_dt.astimezone().date()
                if local_date not in self.tasks_by_date:
                    self.tasks_by_date[local_date] = []
                    
                # Remove existing task with same ID
                self.tasks_by_date[local_date] = [t for t in self.tasks_by_date[local_date] 
                                                if getattr(t, 'task_id', None) != event_id]
                
                # Add the new task
                self.tasks_by_date[local_date].append(task)
    
    def add_events(self, events):
        """Add multiple events to the cache at once."""
        for event in events:
            self.add_event(event)
                
    def delete_event(self, event_id):
        """Delete an event from all caches."""
        with self.cache_lock:
            # Remove from events cache
            for month_key, events_list in list(self.events_by_month.items()):
                self.events_by_month[month_key] = [e for e in events_list if e.get('id') != event_id]
            
            # Remove from tasks cache
            for date, tasks_list in list(self.tasks_by_date.items()):
                self.tasks_by_date[date] = [t for t in tasks_list if getattr(t, 'task_id', None) != event_id]
            
            # Remove from event IDs set
            self.event_ids.discard(event_id)
    
    def clear_month(self, year, month):
        """Clear the cache for a specific month."""
        month_key = (year, month)
        with self.cache_lock:
            # Remove event IDs from this month
            if month_key in self.events_by_month:
                for event in self.events_by_month[month_key]:
                    self.event_ids.discard(event.get('id'))
                del self.events_by_month[month_key]
                
            if month_key in self.holidays_by_month:
                del self.holidays_by_month[month_key]
                
            # Clear tasks for this month
            self.tasks_by_date = {date: tasks for date, tasks in self.tasks_by_date.items() 
                                 if date.year != year or date.month != month}
                
            # Remove this range from fetched ranges
            self.fetched_ranges.discard(month_key)
            
    def has_event_id(self, event_id):
        """Check if an event ID exists in the cache."""
        with self.cache_lock:
            return event_id in self.event_ids
    
    def get_events_for_month(self, year, month):
        """Get all events for a specific month."""
        month_key = (year, month)
        with self.cache_lock:
            return self.events_by_month.get(month_key, [])[:]  # Return a copy
    
    def get_tasks_for_date(self, date):
        """Get all tasks for a specific date."""
        with self.cache_lock:
            return self.tasks_by_date.get(date, [])[:]  # Return a copy
    
    def get_tasks_for_month(self, year, month):
        """Get all tasks for a specific month, organized by date."""
        result = {}
        with self.cache_lock:
            for date, tasks in self.tasks_by_date.items():
                if date.year == year and date.month == month:
                    result[date] = tasks[:]  # Copy the list
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
            return self.holidays_by_month.get(month_key, {}).copy()  # Return a copy
    
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
        
        time_min = start_date.isoformat().replace('+00:00', 'Z')
        time_max = None
        if end_date:
            time_max = end_date.isoformat().replace('+00:00', 'Z')
        
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
            start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        range_id = (calendar_id, start_date.isoformat(), end_date.isoformat())
        
        with self.fetch_lock:
            if range_id in self.fetching_ranges:
                return []
            self.fetching_ranges.add(range_id)
        
        try:
            self._ensure_valid_token()
            month_keys = self._get_month_keys_in_range(start_date, end_date)
            
            # Use cached data if all months are cached
            all_cached = all(self.cache.month_is_cached(*month_key) for month_key in month_keys)
            if all_cached:
                return [event for month_key in month_keys 
                       for event in self.cache.get_events_for_month(*month_key) 
                       if start_date <= parse_event_datetime(event, field='start') <= end_date]
            
            # Get data from cached months
            cached_events = [event for month_key in month_keys 
                            if self.cache.month_is_cached(*month_key)
                            for event in self.cache.get_events_for_month(*month_key)
                            if start_date <= parse_event_datetime(event, field='start') <= end_date]
            
            # Fetch uncached months
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
                
                # Fetch all pages of results
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
                
                # Update cache with new events
                self.cache.add_events(month_events)
                self.cache.mark_range_fetched(year, month)
                new_events.extend(month_events)
            
            # Combine cached and new events, avoiding duplicates
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
            # Move to next month
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
            
            # Update both caches
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
            
            # Update cache
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
            
            # Clean up cache
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
            
            time_min = start_date.isoformat().replace('+00:00', 'Z')
            time_max = end_date.isoformat().replace('+00:00', 'Z')
            
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
                    
            # Update cache
            self.cache.add_holidays(year, month, holidays)
            return holidays
            
        except Exception as e:
            print(f"Error fetching holidays: {str(e)}")
            return {}

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

class ReminderManager:
    """Manages task reminders and notifications."""
    def __init__(self, root):
        self.root = root
        self.reminders = []

    def add_reminder(self, task):
        """Add a task to the reminder list."""
        self.reminders.append(task)

    def check_reminders(self):
        """Check if any reminders need to be shown and schedule next check."""
        now = datetime.now(timezone.utc)
        for task in self.reminders:
            if task.status == 'Pending' and (task.start_dt - now) <= timedelta(minutes=task.reminder_minutes) and (task.start_dt - now) > timedelta(0):
                time_str = format_task_time(task.start_dt, task.end_dt)
                self.root.show_alert(f"Reminder: {task.summary} at {time_str}", alert_type="info", duration=5000)
        self.root.after(60000, self.check_reminders)

# DIALOG UI CLASSES
class TaskDialog(ctk.CTkToplevel):
    """Dialog for creating and editing tasks."""
    def __init__(self, master, on_confirm, task=None):
        super().__init__(master)
        self.on_confirm = on_confirm
        self.task = task
        self.title("Task Dialog")
        self.configure(fg_color=DROPDOWN_BG_COLOR)
        
        if master:
            parent_x = master.winfo_rootx()
            parent_y = master.winfo_rooty()
            parent_width = master.winfo_width()
            parent_height = master.winfo_height()
            
            x_pos = parent_x + (parent_width - DEFAULT_DIALOG_WIDTH) // 2
            y_pos = parent_y + (parent_height - DEFAULT_DIALOG_HEIGHT) // 2
            
            self.geometry(f"{DEFAULT_DIALOG_WIDTH}x{DEFAULT_DIALOG_HEIGHT}+{x_pos}+{y_pos}")
            
        self.setup_initial_time()
        
        self.after(10, self.build_widgets)
        
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
        else:
            now = datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            hour_12, period = convert_from_24(str(next_hour.hour))
            self.initial_hour = hour_12
            self.initial_min = 0
            self.initial_period = period

    def build_widgets(self):
        """Create and arrange all dialog widgets."""
        header_text = "Edit Task" if self.task else "Add New Task"
        header = ctk.CTkLabel(self, text=header_text, font=FONT_HEADER, text_color=TEXT_COLOR)
        header.pack(pady=PADDING)

        summary_label = ctk.CTkLabel(self, text="Task Summary:", font=FONT_LABEL, text_color=TEXT_COLOR)
        summary_label.pack(pady=(5, 0))
        self.summary_entry = ctk.CTkEntry(self, font=FONT_LABEL)
        if self.task:
            self.summary_entry.insert(0, self.task.summary)
        self.summary_entry.pack(pady=5, padx=20, fill="x")

        self.calendar = Calendar(self, date_pattern="y-mm-dd")
        self.calendar.pack(pady=5)

        time_frame = ctk.CTkFrame(self, fg_color=DROPDOWN_BG_COLOR)
        time_frame.pack(pady=5)

        # Start time row
        start_label = ctk.CTkLabel(time_frame, text="Start Time (HH:MM):", font=FONT_LABEL, text_color=TEXT_COLOR)
        start_label.grid(row=0, column=0, padx=5, pady=5)
        self.start_hour = Spinbox(time_frame, from_=1, to=12, width=4, format="%02.0f", command=self._update_end_time)
        self.start_hour.grid(row=0, column=1, padx=5, pady=5)
        self.start_min = Spinbox(time_frame, from_=0, to=59, width=4, format="%02.0f", command=self._update_end_time)
        self.start_min.grid(row=0, column=2, padx=5, pady=5)
        self.start_period = ctk.CTkOptionMenu(time_frame, values=["AM", "PM"], width=60)
        self.start_period.set(self.initial_period)
        self.start_period.grid(row=0, column=3, padx=5, pady=5)

        # End time row
        end_label = ctk.CTkLabel(time_frame, text="End Time (HH:MM):", font=FONT_LABEL, text_color=TEXT_COLOR)
        end_label.grid(row=1, column=0, padx=5, pady=5)
        self.end_hour = Spinbox(time_frame, from_=1, to=12, width=4, format="%02.0f")
        self.end_hour.grid(row=1, column=1, padx=5, pady=5)
        self.end_min = Spinbox(time_frame, from_=0, to=59, width=4, format="%02.0f")
        self.end_min.grid(row=1, column=2, padx=5, pady=5)
        self.end_period = ctk.CTkOptionMenu(time_frame, values=["AM", "PM"], width=60)
        self.end_period.set(self.initial_period)
        self.end_period.grid(row=1, column=3, padx=5, pady=5)

        # Bind events for end time auto-update
        self.start_hour.bind("<KeyRelease>", self._update_end_time)
        self.start_min.bind("<KeyRelease>", self._update_end_time)
        self.start_period.configure(command=self._update_end_time)

        # Initialize time values
        if self.task:
            self._init_time_fields()
        else:
            self.start_hour.delete(0, "end")
            self.start_hour.insert(0, f"{self.initial_hour:02d}")
            self.start_min.delete(0, "end")
            self.start_min.insert(0, f"{self.initial_min:02d}")
            self._update_end_time()

        # Buttons
        btn_frame = ctk.CTkFrame(self, fg_color=DROPDOWN_BG_COLOR)
        btn_frame.pack(pady=PADDING)
        
        if self.task and self.task.task_id:
            delete_btn = ctk.CTkButton(btn_frame, text="Delete", font=FONT_LABEL, 
                                      fg_color="#AA3333", hover_color="#CC5555",
                                      command=self.delete_task)
            delete_btn.grid(row=0, column=0, padx=10)
            confirm_btn = ctk.CTkButton(btn_frame, text="Save", font=FONT_LABEL, command=self.confirm)
            confirm_btn.grid(row=0, column=1, padx=10)
            cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", font=FONT_LABEL, command=self.destroy)
            cancel_btn.grid(row=0, column=2, padx=10)
        else:
            confirm_btn = ctk.CTkButton(btn_frame, text="Create", font=FONT_LABEL, command=self.confirm)
            confirm_btn.grid(row=0, column=0, padx=10)
            cancel_btn = ctk.CTkButton(btn_frame, text="Cancel", font=FONT_LABEL, command=self.destroy)
            cancel_btn.grid(row=0, column=1, padx=10)
            
    def delete_task(self):
        """Delete the current task."""
        if self.task and self.task.task_id:
            if hasattr(self.master, 'delete_task'):
                self.master.delete_task(self.task)
            self.destroy()

    def _update_end_time(self, event=None):
        """Update end time to be 1 hour after start time."""
        try:
            start_hour = int(self.start_hour.get())
            start_min = int(self.start_min.get())
            start_period = self.start_period.get()
            
            start_hour_24 = convert_to_24(str(start_hour), start_period)
            
            end_hour_24 = (start_hour_24 + 1) % 24
            
            end_hour_12, end_period = convert_from_24(str(end_hour_24))
            
            self.end_hour.delete(0, "end")
            self.end_hour.insert(0, f"{end_hour_12:02d}")
            self.end_min.delete(0, "end")
            self.end_min.insert(0, f"{start_min:02d}")
            self.end_period.set(end_period)
        except (ValueError, TypeError):
            pass

    def _init_time_fields(self):
        """Initialize time fields when editing an existing task."""
        local_start = self.task.start_dt.astimezone()
        local_end = self.task.end_dt.astimezone()
        
        self.calendar.selection_set(local_start.date())
        
        start_hour, start_period = convert_from_24(str(local_start.hour))
        self.start_hour.delete(0, "end")
        self.start_hour.insert(0, f"{start_hour:02d}")
        self.start_min.delete(0, "end")
        self.start_min.insert(0, f"{local_start.minute:02d}")
        self.start_period.set(start_period)
        
        end_hour, end_period = convert_from_24(str(local_end.hour))
        self.end_hour.delete(0, "end")
        self.end_hour.insert(0, f"{end_hour:02d}")
        self.end_min.delete(0, "end")
        self.end_min.insert(0, f"{local_end.minute:02d}")
        self.end_period.set(end_period)

    def confirm(self):
        """Validate input and create/update task."""
        summary = self.summary_entry.get().strip()
        if not summary:
            self.master.show_alert("Task summary cannot be empty.", alert_type="error", duration=DEFAULT_ERROR_DURATION)
            return

        date_str = self.calendar.get_date()
        try:
            start_hour_24 = convert_to_24(self.start_hour.get(), self.start_period.get())
            end_hour_24 = convert_to_24(self.end_hour.get(), self.end_period.get())
            
            local_tz = datetime.now().astimezone().tzinfo
            start_dt_local = datetime.strptime(f"{date_str} {start_hour_24:02d}:{self.start_min.get()}", "%Y-%m-%d %H:%M")
            start_dt_local = start_dt_local.replace(tzinfo=local_tz)
            start_dt = local_to_utc(start_dt_local)
            
            end_dt_local = datetime.strptime(f"{date_str} {end_hour_24:02d}:{self.end_min.get()}", "%Y-%m-%d %H:%M")
            end_dt_local = end_dt_local.replace(tzinfo=local_tz)
            end_dt = local_to_utc(end_dt_local)
            
            if end_dt <= start_dt:
                self.master.show_alert("End time must be after start time.", alert_type="error", duration=DEFAULT_ERROR_DURATION)
                return
        except Exception as e:
            self.master.show_alert(f"Invalid date or time: {str(e)}", alert_type="error", duration=DEFAULT_ERROR_DURATION)
            return

        if self.task:
            self.task.summary = summary
            self.task.start_dt = start_dt
            self.task.end_dt = end_dt
        else:
            self.task = Task(summary, start_dt, end_dt)
            
        self.on_confirm(self.task)
        self.destroy()

# Main Application UI 
class TodoAppUI(ctk.CTk):
    """Main application UI class for the To-Do List application."""
    
    def __init__(self, calendar_manager):
        super().__init__()
        self.calendar_manager = calendar_manager
        
        self.title("To-Do List")
        self.geometry(DEFAULT_WINDOW_SIZE)
        self.configure(fg_color=BACKGROUND_COLOR)
        
        self.current_view = "daily"
        today = datetime.now().date()
        self.displayed_year, self.displayed_month = today.year, today.month
        
        self.preload_active = False
        self.ui_dirty = True
        self.loading = False
        self.worker = APIWorker(self)
        self.data_lock = threading.Lock()  # Add lock for thread safety
        self.reminder_manager = ReminderManager(self)
        
        # Initialize view containers
        self.monthly_view_frame = None
        self.content_frame = None
        self.calendar_cells = {}
        self.rendered_days = set()

        # Set up UI components
        self._setup_alert_area()
        self._setup_navbar()
        self._setup_main_layout()
        
        # Start background processes
        self.refresh_events()
        self.reminder_manager.check_reminders()
        self.check_token_refresh()
        
        # Set up window close handler
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
    def check_token_refresh(self):
        """Periodically check if token needs refresh and schedule next check."""
        try:
            if hasattr(self.calendar_manager, 'auth_service'):
                refreshed = self.calendar_manager.auth_service.auto_refresh_token()
                if refreshed:
                    self.show_alert("Authentication token refreshed successfully", duration=3000)
        except Exception as e:
            print(f"Error checking token refresh: {str(e)}")
        finally:
            self.after(600000, self.check_token_refresh)
        
    def _on_close(self):
        """Clean up resources before closing."""
        if hasattr(self, 'worker'):
            self.worker.stop()
        self.destroy()
        
    def show_loading(self, is_loading):
        """Show or hide loading indicator."""
        self.loading = is_loading
        if is_loading:
            self.loading_label.pack(side="right", padx=20, pady=5)
            self.alert_frame.pack(fill="x")
        else:
            self.loading_label.pack_forget()
            if not self.alert_label.cget("text"):
                self.alert_frame.pack_forget()

    def _setup_alert_area(self):
        """Set up the alert/notification area."""
        self.alert_frame = ctk.CTkFrame(self, fg_color=BACKGROUND_COLOR, height=30)
        self.alert_frame.pack(fill="x")
        self.alert_label = ctk.CTkLabel(self.alert_frame, text="", font=FONT_LABEL, text_color=TEXT_COLOR)
        self.alert_label.pack(side="left", padx=20, pady=5)
        
        # Create loading label once during initialization
        self.loading_label = ctk.CTkLabel(
            self.alert_frame, 
            text="Loading...", 
            font=FONT_LABEL, 
            text_color="#55AAFF"
        )
        self.loading_label.pack(side="right", padx=20, pady=5)
        self.loading_label.pack_forget()  # Initially hidden
        
        self.alert_frame.pack_forget()

    def _check_scroll_position(self):
        """Periodic check for UI maintenance."""
        self.after(200, self._check_scroll_position)
    
    def _render_pending_tasks(self, visible_top=None, visible_bottom=None, canvas_height=None):
        """Helper function to render all days in expanded month containers that haven't been rendered yet."""
        if not hasattr(self, 'month_containers') or not self.month_containers:
            return
            
        for month_key, month_data in self.month_containers.items():
            if not month_data.get('expanded', False):
                continue
                
            for day_key, day_data in month_data.get('days', {}).items():
                with self.data_lock:
                    already_rendered = day_key in self.rendered_days
                if not already_rendered and not day_data.get('rendered', False):
                    self._render_day(month_key, day_key, day_data)
    
    def _render_day(self, month_key, day_key, day_data):
        """Render a day's content."""
        if not day_data.get('frame') or not day_data.get('tasks'):
            return
            
        parent_frame = day_data.get('frame')
        tasks = day_data.get('tasks', [])
        
        day_data['rendered'] = True
        with self.data_lock:
            self.rendered_days.add(day_key)
        
        tasks_container = day_data.get('container')
        if tasks_container:
            for task in tasks:
                self._add_task_to_container(tasks_container, task)

    def refresh_events(self):
        """Refresh events from Google Calendar using background thread."""
        self.ui_dirty = True
        
        def on_events_loaded(result):
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            if next_token:
                self._fetch_next_page(next_token)
            else:
                self._update_current_view()
        
        def on_error(error):
            self.show_alert(f"Error loading events: {str(error)}", alert_type="error", duration=5000)
            self._update_current_view()
        
        start_date = datetime.now(timezone.utc)
        
        self.worker.add_task(
            "fetch_events",
            self.calendar_manager.fetch_events,
            callback=on_events_loaded,
            error_callback=on_error,
            calendar_id='primary',
            max_results=50,
            start_date=start_date
        )
    
    def _fetch_next_page(self, page_token):
        """Fetch the next page of events in the background."""
        def on_next_page_loaded(result):
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            if next_token:
                self._fetch_next_page(next_token)
            else:
                self._update_current_view()
        
        def on_error(error):
            print(f"Error loading next page: {str(error)}")
            # Update UI with what we have so far
            self._update_current_view()
        
        # Queue the API call in the worker thread
        self.worker.add_task(
            "background_fetch",
            self.calendar_manager.fetch_events,
            callback=on_next_page_loaded,
            error_callback=on_error,
            calendar_id='primary',
            max_results=50,
            page_token=page_token
        )
    
    def _update_current_view(self):
        """Update the current view after data has been loaded."""
        if self.current_view == "daily":
            self.build_daily_view(self.search_entry.get() if hasattr(self, 'search_entry') else "")
        elif self.current_view == "monthly":
            self._update_monthly_view_data(self.search_entry.get() if hasattr(self, 'search_entry') else "")
        self.ui_dirty = False
    
    def _process_loaded_events(self, events):
        """Process loaded events and update the cache."""
        # Add events to cache
        added_count = 0
        
        for event in events:
            event_id = event.get('id')
            
            # Check if event already exists using our dedicated set
            if event_id and self.calendar_manager.cache.has_event_id(event_id):
                continue  # Skip duplicates
                
            # Add to cache which handles converting to task
            self.calendar_manager.cache.add_event(event)
            added_count += 1
            
            # Add to reminders
            task = self.calendar_manager.cache._convert_event_to_task(event)
            if task:
                self.reminder_manager.add_reminder(task)
        
        # Only update UI if we've added events and UI needs updating
        if added_count > 0 and self.ui_dirty:
            self._update_current_view()

    def _convert_event_to_task(self, event):
        """Convert a Google Calendar event to a Task object."""
        try:
            start_dt = parse_event_datetime(event, field='start')
            end_dt = parse_event_datetime(event, field='end')
            task = Task(event['summary'], start_dt, end_dt, task_id=event.get('id'))
            return task
        except Exception as e:
            print(f"Error converting event to task: {str(e)}")
            return None

    def build_daily_view(self, search_term=""):
        """Build the daily view with all tasks rendered for expanded months."""
        # Clear tracking variables
        self.rendered_days = set()
        self.month_containers = {}
        
        # Clear the current content
        for widget in self.content_frame.winfo_children():
            widget.destroy()
        
        # Get filtered tasks by date
        tasks_by_date = self.get_filtered_tasks_by_date(search_term)
        
        # Sort dates for chronological display
        sorted_dates = sorted(tasks_by_date.keys())
        
        if not sorted_dates:
            # Show a message if no tasks found
            no_tasks_label = ctk.CTkLabel(
                self.content_frame, 
                text="No tasks found for this period", 
                font=FONT_HEADER, 
                text_color=TEXT_COLOR
            )
            no_tasks_label.pack(pady=50)
            return
        
        # Get current date to determine which months to expand by default
        current_date = datetime.now().date()
        
        # Group tasks by month for counting
        tasks_by_month = {}
        for day, tasks in tasks_by_date.items():
            month_key = (day.year, day.month)
            if month_key not in tasks_by_month:
                tasks_by_month[month_key] = []
            tasks_by_month[month_key].extend(tasks)
        
        # Track current month and year to detect changes
        current_month = None
        current_year = None
        current_month_frame = None
        
        # Loop through each day in sorted order
        for day in sorted_dates:
            # Check if month or year has changed
            if current_year != day.year or current_month != day.month:
                # Get task count for this month
                month_key = (day.year, day.month)
                task_count = len(tasks_by_month.get(month_key, []))
                
                # Create month/year separator
                separator_frame = ctk.CTkFrame(self.content_frame, fg_color="#262640")
                separator_frame.pack(fill="x", padx=PADDING, pady=(PADDING, PADDING/2))
                
                # Create internal layout for the separator
                header_container = ctk.CTkFrame(separator_frame, fg_color="#262640")
                header_container.pack(fill="x", padx=0, pady=0)
                
                # Determine if this month should be expanded by default (current month)
                is_current_month = (day.year == current_date.year and day.month == current_date.month)
                
                # Month and year header with icon, toggle indicator, and task count
                icon = "🔽" if is_current_month else "▶️"
                month_year_text = f"{calendar.month_name[day.month]} {day.year}"
                task_count_text = f"({task_count} task{'s' if task_count != 1 else ''})"
                
                header_frame = ctk.CTkFrame(header_container, fg_color="#262640")
                header_frame.pack(fill="x", expand=True)
                header_frame.grid_columnconfigure(0, weight=1)  # Month name takes available space
                header_frame.grid_columnconfigure(1, weight=0)  # Task count is compact
                
                # Month name and icon
                month_year_label = ctk.CTkLabel(
                    header_frame, 
                    text=f"📅  {month_year_text} {icon}", 
                    font=FONT_HEADER, 
                    text_color="#FFFFFF",
                    anchor="w"
                )
                month_year_label.grid(row=0, column=0, sticky="w", padx=PADDING, pady=PADDING/3)
                
                # Task count
                task_count_label = ctk.CTkLabel(
                    header_frame,
                    text=task_count_text,
                    font=FONT_LABEL,
                    text_color="#AAAAFF",
                    anchor="e"
                )
                task_count_label.grid(row=0, column=1, sticky="e", padx=PADDING, pady=PADDING/3)
                
                # Add horizontal divider line
                divider = ctk.CTkFrame(separator_frame, height=2, fg_color="#3A3A5C")
                divider.pack(fill="x", padx=PADDING, pady=(0, PADDING/4))
                
                # Create a container for all days in this month
                month_container = ctk.CTkFrame(self.content_frame, fg_color=BACKGROUND_COLOR)
                month_container.pack(fill="x", padx=0, pady=0)
                
                # Track days in this month container
                month_days = {}
                self.month_containers[month_key] = {
                    'frame': month_container,
                    'days': month_days,
                    'expanded': is_current_month
                }
                
                # Hide the container if it's not the current month and we're not searching
                if not is_current_month and not search_term:
                    month_container.pack_forget()
                
                # Store references for toggling
                separator_frame.month_container = month_container
                separator_frame.month_year_label = month_year_label
                separator_frame.is_expanded = is_current_month
                separator_frame.month_year_text = month_year_text
                separator_frame.task_count_text = task_count_text
                separator_frame.month_key = month_key
                
                # Bind click event to toggle
                separator_frame.bind("<Button-1>", self._toggle_month_section)
                header_container.bind("<Button-1>", lambda e, sf=separator_frame: self._toggle_month_section(e, sf))
                header_frame.bind("<Button-1>", lambda e, sf=separator_frame: self._toggle_month_section(e, sf))
                month_year_label.bind("<Button-1>", lambda e, sf=separator_frame: self._toggle_month_section(e, sf))
                task_count_label.bind("<Button-1>", lambda e, sf=separator_frame: self._toggle_month_section(e, sf))
                
                # Update tracking variables
                current_month = day.month
                current_year = day.year
                current_month_frame = month_container
            
            # Create the day frame for tasks inside the month container
            day_frame = ctk.CTkFrame(current_month_frame, fg_color=BACKGROUND_COLOR)
            day_frame.pack(fill="x", padx=PADDING, pady=PADDING/3)
            
            # Create the date strip on the left
            self._create_day_header(day_frame, day)
            
            # Create the tasks container for the day
            tasks_container = ctk.CTkFrame(day_frame, fg_color=BACKGROUND_COLOR)
            tasks_container.pack(side="left", fill="x", expand=True)
            
            # Store day data for rendering
            month_key = (day.year, day.month)
            day_key = str(day)
            
            self.month_containers[month_key]['days'][day_key] = {
                'frame': day_frame,
                'container': tasks_container,
                'tasks': tasks_by_date[day],
                'rendered': False
            }
            
            # Render tasks for visible/expanded months or when searching
            is_current_month = (day.year == current_date.year and day.month == current_date.month)
            if is_current_month or search_term:
                self._render_day(month_key, day_key, self.month_containers[month_key]['days'][day_key])
    
    def _toggle_month_section(self, event, separator_frame=None):
        """Toggle the visibility of a month section."""
        # If called from event, extract the separator_frame
        if separator_frame is None:
            separator_frame = event.widget
            while not hasattr(separator_frame, "month_container"):
                separator_frame = separator_frame.master
                if separator_frame is None:
                    return  # Not found
            
        # Toggle the expanded state
        separator_frame.is_expanded = not separator_frame.is_expanded
        
        # Update the icon
        icon = "🔽" if separator_frame.is_expanded else "▶️"
        separator_frame.month_year_label.configure(
            text=f"📅  {separator_frame.month_year_text} {icon}"
        )
        
        # Show or hide the month container
        if separator_frame.is_expanded:
            separator_frame.month_container.pack(fill="x", padx=0, pady=0, after=separator_frame)
            
            # Render all days that aren't already rendered
            if hasattr(separator_frame, 'month_key') and separator_frame.month_key in self.month_containers:
                month_data = self.month_containers[separator_frame.month_key]
                for day_key, day_data in month_data.get('days', {}).items():
                    if not day_data.get('rendered', False):
                        self._render_day(separator_frame.month_key, day_key, day_data)
                        
            # Update expanded state in tracking dict
            if hasattr(separator_frame, 'month_key') and separator_frame.month_key in self.month_containers:
                self.month_containers[separator_frame.month_key]['expanded'] = True
        else:
            separator_frame.month_container.pack_forget()
            # Update expanded state in tracking dict
            if hasattr(separator_frame, 'month_key') and separator_frame.month_key in self.month_containers:
                self.month_containers[separator_frame.month_key]['expanded'] = False

    def _render_task(self, parent_frame, task, is_monthly_view=False, truncate_length=None):
        """Shared method to render a task UI element consistently across views."""
        # Create task card with appropriate styling
        corner_radius = 3 if is_monthly_view else 6
        task_frame = ctk.CTkFrame(parent_frame, fg_color=CARD_COLOR, corner_radius=corner_radius)
        
        # Format time using the shared helper function
        time_str = format_task_time(task.start_dt, task.end_dt)

        # Handle summary truncation for monthly view
        summary = task.summary
        if truncate_length and len(summary) > truncate_length:
            display_summary = f"{summary[:truncate_length]}..."
        else:
            display_summary = summary

        # Set common parameters based on view type
        font = FONT_SMALL if is_monthly_view else FONT_LABEL
        anchor = "w" if is_monthly_view else "center"
        padding = (2, 1 if is_monthly_view else 0) if is_monthly_view else (4, 3)

        # Create task summary label
        task_label = ctk.CTkLabel(task_frame, text=f"{'• ' if is_monthly_view else ''}{display_summary}", 
                           font=font, text_color=TEXT_COLOR, anchor=anchor)
        task_label.pack(anchor="w" if is_monthly_view else None, fill="x", padx=padding[0], pady=(padding[1], 0))
        
        # Create time label
        time_label = ctk.CTkLabel(task_frame, text=time_str, font=FONT_SMALL, 
                           text_color=TEXT_COLOR, anchor=anchor)
        time_label.pack(anchor="w" if is_monthly_view else None, fill="x", padx=padding[0], pady=(0, padding[1]))
        
        # Bind click events for editing
        for widget in (task_frame, task_label, time_label):
            widget.bind("<Button-1>", lambda e, t=task: self.open_task_dialog(t))
        
        return task_frame

    def _add_task_to_container(self, container, task):
        """Add a single task to a container."""
        # Use the shared render method
        task_frame = self._render_task(container, task)
        task_frame.pack(fill="x", pady=PADDING/3)

    def _add_tasks_to_cell(self, parent_frame, tasks, max_tasks=MAX_TASKS_PER_CELL):
        """Helper to add tasks to a cell - separated for better readability."""
        # Clear all existing widgets first
        for widget in parent_frame.winfo_children():
            widget.destroy()
            
        # Add tasks up to the limit
        for i, task in enumerate(tasks[:max_tasks]):
            task_frame = self._render_task(parent_frame, task, is_monthly_view=True, truncate_length=14)
            task_frame.pack(fill="x", padx=1, pady=1)
        
        # Show "more" indicator if needed
        if len(tasks) > max_tasks:
            more_label = ctk.CTkLabel(parent_frame, text=f"+ {len(tasks) - max_tasks} more", 
                                   font=FONT_SMALL, text_color="#AAAAAA", anchor="w")
            more_label.pack(anchor="w", fill="x", padx=2, pady=0)
        
        return min(len(tasks), max_tasks)
    
    def _create_day_header(self, parent_frame, day):
        """Create the date header for a day in daily view."""
        date_strip = ctk.CTkFrame(parent_frame, fg_color=BACKGROUND_COLOR, width=50)
        date_strip.pack(side="left", anchor="n")
        
        # Day of week abbreviation
        abbr_label = ctk.CTkLabel(date_strip, text=day.strftime("%a").upper(), 
                               font=FONT_DAY, text_color=TEXT_COLOR)
        abbr_label.pack(anchor="w")
        
        # Day number
        date_label = ctk.CTkLabel(date_strip, text=day.strftime("%d"), 
                               font=FONT_DATE, text_color=TEXT_COLOR)
        date_label.pack(anchor="w")
    
    def _add_day_tasks(self, container, tasks):
        """Add tasks for a day to the container in daily view."""
        for task in tasks:
            # Use the shared render method
            task_frame = self._render_task(container, task)
            task_frame.pack(fill="x", pady=PADDING/3)

    # Task Management
    def open_task_dialog(self, task=None):
        """Open dialog to create new task or edit existing task."""
        def on_confirm(new_task):
            # Prepare event data
            event = {
                'summary': new_task.summary,
                'start': {'dateTime': new_task.start_dt.isoformat(), 'timeZone': 'UTC'},
                'end': {'dateTime': new_task.end_dt.isoformat(), 'timeZone': 'UTC'}
            }
            
            # Common success/error handlers
            def on_success(result):
                action = "updated" if task and task.task_id else "created"
                if not task or not task.task_id:
                    new_task.task_id = result.get('id')
                self.show_alert(f"Task {action}: {new_task.summary}", duration=3000)
                self.refresh_events()
            
            def on_error(error):
                action = "update" if task and task.task_id else "add"
                self.show_alert(f"Failed to {action} task: {str(error)}", alert_type="error", duration=DEFAULT_ERROR_DURATION)
            
            # Queue the API operation in the worker thread
            if task and task.task_id:
                # Update existing task
                self.worker.add_task(
                    "update_task",
                    self.calendar_manager.update_event,
                    callback=on_success,
                    error_callback=on_error,
                    calendar_id='primary',
                    event_id=task.task_id,
                    updated_event=event
                )
            else:
                # Create new task
                self.worker.add_task(
                    "create_task",
                    self.calendar_manager.add_event,
                    callback=on_success,
                    error_callback=on_error,
                    calendar_id='primary',
                    event=event
                )
            
        dialog = TaskDialog(self, on_confirm, task)
        dialog.grab_set()
        
    def delete_task(self, task):
        """Delete a task from the calendar."""
        if not task or not task.task_id:
            self.show_alert("Cannot delete task: no task ID", alert_type="error", duration=3000)
            return
            
        def on_delete_success(result):
            self.show_alert(f"Task deleted", duration=3000)
            
            # Refresh the current view
            if self.current_view == "daily":
                self.build_daily_view()
            elif self.current_view == "monthly":
                self._update_monthly_view_data(self.search_entry.get())
        
        def on_delete_error(error):
            self.show_alert(f"Failed to delete task: {str(error)}", alert_type="error", duration=4000)
        
        # Queue the deletion in the worker thread
        self.worker.add_task(
            "delete_task",
            self.calendar_manager.delete_event,
            callback=on_delete_success,
            error_callback=on_delete_error,
            calendar_id='primary',
            event_id=task.task_id
        )

    def get_filtered_tasks_by_date(self, search_term=""):
        """Get tasks filtered by search term, organized by date."""
        tasks_by_date = self._get_tasks_by_date_dict()

        if not search_term:
            return tasks_by_date
        
        # Filter tasks by search term
        search_term = search_term.lower()
        return {date: [task for task in tasks if search_term in task.summary.lower()] 
                for date, tasks in tasks_by_date.items() 
                if any(search_term in task.summary.lower() for task in tasks)}
    
    def _get_tasks_by_date_dict(self):
        """Get tasks organized by date from the cache."""
        return self.calendar_manager.cache.tasks_by_date.copy()

    def _update_monthly_view_data(self, search_term=""):
        """Updates the existing monthly view widgets with data for the current month."""
        if not self.calendar_cells:
            self._create_monthly_view_structure()
            
        # Update month/year header label
        if self.month_year_label:
            self.month_year_label.configure(text=f"{calendar.month_name[self.displayed_month]} {self.displayed_year}")

        # Get data for the month
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        
        # Clear all cells first
        self._clear_calendar_cells()
        
        # Set up calendar cell dates immediately while we load data
        self._setup_calendar_cell_dates(month_calendar)
        
        # Define callbacks for background loading
        def on_events_loaded(events):
            # Process events into tasks by date
            tasks_by_date = self._process_events_for_monthly_view(events)
                
            # Update the UI with these tasks
            self._update_calendar_cells(tasks_by_date, search_term)
            
        def on_fetch_error(error):
            self.show_alert(f"Error fetching events: {str(error)}", alert_type="error", duration=4000)
        
        # Check if we have cached data for this month
        month_key = (self.displayed_year, self.displayed_month)
        
        # Get tasks for this month from the cache
        tasks_by_date = self.calendar_manager.cache.get_tasks_for_month(self.displayed_year, self.displayed_month)
        
        if tasks_by_date:
            # Use cached data
            self._update_calendar_cells(tasks_by_date, search_term)
        else:
            # Calculate date range for the month
            start_date, end_date = self._get_month_date_range(self.displayed_year, self.displayed_month)
                
            # Queue the fetch in background
            self.worker.add_task(
                "fetch_month",
                self.calendar_manager.fetch_events_for_range,
                callback=on_events_loaded,
                error_callback=on_fetch_error,
                start_date=start_date,
                end_date=end_date
            )
                
        # Fetch holidays in background
        self._fetch_holidays_for_month()
            
        # Trigger preload for adjacent months
        self.after(100, lambda: self._preload_adjacent_months())
    
    def _process_events_for_monthly_view(self, events):
        """Process events into tasks by date for monthly view."""
        tasks_by_date = {}
        
        for event in events:
            try:
                # Extract the event date (in local time)
                event_dt = parse_event_datetime(event, field='start')
                local_date = event_dt.astimezone().date()
                
                # Skip events not in the displayed month (could happen with recurring events)
                if local_date.month != self.displayed_month or local_date.year != self.displayed_year:
                    continue
                    
                # Add to tasks by date
                if local_date not in tasks_by_date:
                    tasks_by_date[local_date] = []
                    
                # Convert event to task using helper method
                task = self._convert_event_to_task(event)
                if task:
                    tasks_by_date[local_date].append(task)
            except Exception as e:
                print(f"Error processing event for monthly view: {str(e)}")
                
        return tasks_by_date
    
    def _get_month_date_range(self, year, month):
        """Calculate the start and end dates for a month."""
        start_date = datetime(year, month, 1, tzinfo=timezone.utc)
        
        # Calculate end date (last day of month)
        if month == 12:
            end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
            
        return start_date, end_date
    
    def _fetch_holidays_for_month(self):
        """Fetch holidays for the current month in background."""
        def on_holidays_loaded(holidays):
            # Update cells with holiday information
            for date, holiday_name in holidays.items():
                # Only process holidays for the current month and year
                if date.month != self.displayed_month or date.year != self.displayed_year:
                    continue
                    
                # Find the cell for this date
                for row_idx, week in enumerate(calendar.monthcalendar(self.displayed_year, self.displayed_month)):
                    for col_idx, day_num in enumerate(week):
                        if day_num == date.day:
                            cell_data = self.calendar_cells.get((row_idx, col_idx))
                            if cell_data:
                                self._add_holiday_to_cell(cell_data['tasks_frame'], holiday_name, 
                                                         (self.displayed_year, self.displayed_month))
        
        def on_holiday_error(error):
            print(f"Error fetching holidays: {str(error)}")
            
        # Queue holiday fetch in background
        self.worker.add_task(
            "fetch_holidays",
            self.calendar_manager.fetch_holidays,
            callback=on_holidays_loaded,
            error_callback=on_holiday_error,
            year=self.displayed_year,
            month=self.displayed_month
        )
    
    def _preload_adjacent_months(self):
        """Preload data for adjacent months to improve navigation experience."""
        if self.preload_active:
            return
            
        self.preload_active = True
        
        try:
            # Calculate adjacent months
            prev_year, prev_month = self._get_prev_month(self.displayed_year, self.displayed_month)
            next_year, next_month = self._get_next_month(self.displayed_year, self.displayed_month)
                
            # Check if we already have data for these months
            next_month_cached = self.calendar_manager.cache.month_is_cached(next_year, next_month)
            prev_month_cached = self.calendar_manager.cache.month_is_cached(prev_year, prev_month)
            
            # Preload next month if not cached
            if not next_month_cached:
                self._preload_month_data(next_year, next_month)
            
            # Preload previous month if not cached
            if not prev_month_cached:
                self._preload_month_data(prev_year, prev_month)
                
        except Exception as e:
            print(f"Preload error: {str(e)}")
        finally:
            self.preload_active = False
    
    def _get_prev_month(self, year, month):
        """Get the previous month's year and month values."""
        return (year - 1, 12) if month == 1 else (year, month - 1)
    
    def _get_next_month(self, year, month):
        """Get the next month's year and month values."""
        return (year + 1, 1) if month == 12 else (year, month + 1)
            
    def _preload_month_data(self, year, month):
        """Preload data for a specific month."""
        def on_events_loaded(events):
            # Processing is handled automatically by the cache
            pass
        
        def on_error(error):
            print(f"Error preloading data for {month}/{year}: {str(error)}")
        
        # Calculate date range for the month
        start_date, end_date = self._get_month_date_range(year, month)
        
        # Queue the fetch in background
        self.worker.add_task(
            "preload",
            self.calendar_manager.fetch_events_for_range,
            callback=on_events_loaded,
            error_callback=on_error,
            start_date=start_date,
            end_date=end_date
        )
        
        # Also preload holidays
        self.worker.add_task(
            "preload",
            self.calendar_manager.fetch_holidays,
            error_callback=on_error,
            year=year,
            month=month
        )
    
    def _add_holiday_to_cell(self, parent_frame, holiday_name, month_key=None):
        """Add a holiday indicator at the top of a cell."""
        # Create holiday indicator frame at the top
        holiday_frame = ctk.CTkFrame(parent_frame, fg_color="#2C3D4D", corner_radius=4, height=20)
        holiday_frame.pack(fill="x", padx=2, pady=(0, 2), side="top")
        
        # Store month information in the frame to help with clearing
        if month_key:
            holiday_frame.month_key = month_key
            
        # Holiday label
        holiday_label = ctk.CTkLabel(holiday_frame, 
                                text=f"🎉 {holiday_name}", 
                                font=FONT_SMALL, 
                                text_color="#FFFFFF", 
                                anchor="w")
        holiday_label.pack(anchor="w", fill="x", padx=3, pady=1)
    
    def _setup_calendar_cell_dates(self, month_calendar):
        """Set up the date numbers in calendar cells while waiting for data."""
        today = datetime.now().date()
        
        row_idx = 0
        for week in month_calendar:
            for col_idx, day_num in enumerate(week):
                cell_data = self.calendar_cells.get((row_idx, col_idx))
                if not cell_data:
                    continue
                    
                if day_num == 0:  # Day not in current month
                    cell_data['frame'].configure(fg_color="#1E1E2F")  # Darker background
                    continue
                    
                # Set up the cell for a day in the current month
                current_date = datetime(self.displayed_year, self.displayed_month, day_num).date()
                
                # Configure cell appearance for today highlighting
                self._configure_cell_appearance(cell_data, current_date, day_num, today)
                
                # Bind day label for creating tasks
                cell_data['day_label'].bind("<Button-1>", lambda e, d=current_date: self.open_task_dialog_for_date(d))
            row_idx += 1
    
    def _update_calendar_cells(self, tasks_by_date, search_term=""):
        """Update calendar cells with task data."""
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        today = datetime.now().date()
        MAX_TASKS_PER_CELL = 3  # Limit tasks per cell
        
        row_idx = 0
        for week in month_calendar:
            for col_idx, day_num in enumerate(week):
                cell_data = self.calendar_cells.get((row_idx, col_idx))
                if not cell_data:
                    continue
                    
                if day_num == 0:  # Day not in current month
                    continue  # Skip - already set up in _setup_calendar_cell_dates
                    
                # Set up the cell for a day in the current month
                current_date = datetime(self.displayed_year, self.displayed_month, day_num).date()
                
                # Add tasks for the day
                tasks_today = tasks_by_date.get(current_date, [])
                if search_term:
                    tasks_today = [t for t in tasks_today if search_term.lower() in t.summary.lower()]
                    
                if tasks_today:
                    # Clear existing task widgets first
                    for widget in cell_data['tasks_frame'].winfo_children():
                        if not isinstance(widget, ctk.CTkFrame) or not widget.cget("fg_color") == "#2C3D4D":
                            # Keep holiday frames (blue background)
                            widget.destroy()
                            
                    self._add_tasks_to_cell(cell_data['tasks_frame'], tasks_today, MAX_TASKS_PER_CELL)
            row_idx += 1

    def _setup_navbar(self):
        """Set up the navigation bar with search and controls."""
        self.nav_frame = ctk.CTkFrame(self, fg_color=NAV_BG_COLOR, height=50)
        self.nav_frame.pack(fill="x")

        # Search field
        self.search_entry = ctk.CTkEntry(self.nav_frame, placeholder_text="Search tasks...", width=200)
        self.search_entry.pack(side="left", padx=PADDING)
        self.search_entry.bind("<KeyRelease>", lambda e: self.filter_content())

        # Label
        self.nav_label = ctk.CTkLabel(self.nav_frame, text="Navigation Bar", font=FONT_HEADER, text_color=TEXT_COLOR)
        self.nav_label.pack(side="left", padx=PADDING, pady=PADDING)

        # Add Task button
        self.add_task_btn = ctk.CTkButton(self.nav_frame, text="Add Task", command=self.open_task_dialog)
        self.add_task_btn.pack(side="right", padx=PADDING, pady=PADDING)

    def _setup_main_layout(self):
        """Set up the main layout including sidebar and content areas."""
        self.main_frame = ctk.CTkFrame(self, fg_color=BACKGROUND_COLOR)
        self.main_frame.pack(fill="both", expand=True)

        # Sidebar with view buttons
        self._setup_sidebar()
        
        # Views container for holding daily and monthly views
        self.views_container = ctk.CTkFrame(self.main_frame, fg_color=BACKGROUND_COLOR)
        self.views_container.pack(side="right", fill="both", expand=True)

        # Create the scrollable frame for daily view
        self.content_frame = ctk.CTkScrollableFrame(self.views_container, fg_color=BACKGROUND_COLOR)
        self.content_frame.pack(fill="both", expand=True)
        
        # Initialize the monthly view frame but don't pack it yet
        self.monthly_view_frame = ctk.CTkFrame(self.views_container, fg_color=BACKGROUND_COLOR)
        
        # Build initial content for the default view
        self.build_daily_view()
        
    def _setup_sidebar(self):
        """Set up the sidebar with view selection buttons."""
        self.sidebar = ctk.CTkFrame(self.main_frame, fg_color=NAV_BG_COLOR, width=200)
        self.sidebar.pack(side="left", fill="y")

        # View buttons
        buttons = ["Daily View", "Monthly View"]
        for btn_text in buttons:
            btn = ctk.CTkButton(self.sidebar, text=btn_text, command=lambda x=btn_text: self.switch_view(x))
            btn.pack(pady=10, padx=10, fill="x")
            
    def show_alert(self, message, alert_type="info", duration=DEFAULT_ALERT_DURATION):
        """Show an alert/notification message."""
        colors = {"error": ERROR_COLOR, "info": SUCCESS_COLOR}
        self.alert_label.configure(text=message, 
                                 text_color=colors.get(alert_type, TEXT_COLOR))
        self.alert_frame.pack(fill="x")
        self.after(duration, self.clear_alert)

    def clear_alert(self):
        """Clear the current alert/notification."""
        self.alert_label.configure(text="")
        self.alert_frame.pack_forget()
        
    def switch_view(self, view):
        """Switch between different views (daily, monthly)."""
        # Hide both views first
        self.content_frame.pack_forget()
        self.monthly_view_frame.pack_forget()
            
        if view == "Daily View":
            self.current_view = "daily"
            self.content_frame.pack(fill="both", expand=True)
            self.build_daily_view()
        elif view == "Monthly View":
            self.current_view = "monthly"
            # Show the monthly view frame
            self.monthly_view_frame.pack(fill="both", expand=True)
            # Only create structure if it hasn't been built yet
            if not self.monthly_view_frame.winfo_children():
                self._create_monthly_view_structure()
            # Update the data in the monthly view
            self._update_monthly_view_data(self.search_entry.get())

    def filter_content(self):
        """Filter view content based on search term."""
        search_term = self.search_entry.get()
        if self.current_view == "daily":
            self.build_daily_view(search_term)
        elif self.current_view == "monthly":
            self._update_monthly_view_data(search_term)
            
    def _create_monthly_view_structure(self):
        """Creates the static widgets for the monthly view frame ONCE."""
        # Clear any existing child widgets in the monthly view frame
        for widget in self.monthly_view_frame.winfo_children():
            widget.destroy()
            
        # --- Header for Month Navigation ---
        self._create_month_header()
        
        # --- Main Container (non-scrollable) ---
        container_frame = ctk.CTkFrame(self.monthly_view_frame, fg_color=BACKGROUND_COLOR)
        container_frame.pack(fill="both", expand=True, padx=4, pady=4)
        
        # Create the calendar grid frame
        calendar_frame = ctk.CTkFrame(container_frame, fg_color=BACKGROUND_COLOR)
        calendar_frame.pack(fill="both", expand=True)
        
        # --- Static Day Headers ---
        self._create_day_headers(calendar_frame)
        
        # --- Create Calendar Grid Cells ---
        self._setup_calendar_cells(calendar_frame)
    
    def _create_month_header(self):
        """Create the month navigation header."""
        header_frame = ctk.CTkFrame(self.monthly_view_frame, fg_color=NAV_BG_COLOR)
        header_frame.pack(fill="x", pady=(0, PADDING/4))  # Reduced padding to maximize space

        # Previous month button
        prev_button = ctk.CTkButton(header_frame, text="<", width=30, command=self.prev_month)
        prev_button.pack(side="left", padx=PADDING, pady=1)  # Reduced padding

        # Month and year label
        self.month_year_label = ctk.CTkLabel(header_frame, 
                                     text=f"{calendar.month_name[self.displayed_month]} {self.displayed_year}", 
                                     font=FONT_HEADER, 
                                     text_color=TEXT_COLOR)
        self.month_year_label.pack(side="left", expand=True, pady=1)  # Reduced padding

        # Next month button
        next_button = ctk.CTkButton(header_frame, text=">", width=30, command=self.next_month)
        next_button.pack(side="right", padx=PADDING, pady=1)  # Reduced padding
    
    def _create_day_headers(self, calendar_frame):
        """Create the day of week headers for the calendar."""
        days_of_week = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        for col, day_name in enumerate(days_of_week):
            calendar_frame.grid_columnconfigure(col, weight=1, uniform="calendar_col")
            day_header = ctk.CTkFrame(calendar_frame, fg_color="#1A1A2E", height=25)
            day_header.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            day_header.grid_propagate(False)
            
            day_label = ctk.CTkLabel(day_header, text=day_name, font=FONT_DAY, text_color=TEXT_COLOR)
            day_label.pack(expand=True)
    
    def _setup_calendar_cells(self, calendar_frame):
        """Create uniform calendar grid cells for the month."""
        # Reset cells dictionary
        self.calendar_cells = {}
        
        # Get the current month's calendar to determine number of weeks
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        num_weeks = len(month_calendar)  # This will be 5 or 6 depending on the month
        
        # Create grid based on actual number of weeks needed
        for row_idx in range(num_weeks):
            calendar_frame.grid_rowconfigure(row_idx + 1, weight=1, uniform="calendar_row")
            
            for col_idx in range(7):  # 7 days per week
                # Create cell frame with uniform size
                cell_frame = ctk.CTkFrame(calendar_frame, fg_color=BACKGROUND_COLOR, 
                                       border_width=1, border_color="#333344")
                cell_frame.grid(row=row_idx + 1, column=col_idx, sticky="nsew", padx=1, pady=1)
                cell_frame.grid_propagate(False)  # Prevent content from affecting cell size
                
                # Create internal structure for the cell
                self._create_cell_structure(cell_frame, row_idx, col_idx)
    
    def _create_cell_structure(self, cell_frame, row_idx, col_idx):
        """Create the internal structure for a calendar cell."""
        # Content frame inside cell
        content_frame = ctk.CTkFrame(cell_frame, fg_color="transparent")
        content_frame.pack(fill="both", expand=True, padx=1, pady=1)
        
        # Day number label - fixed size area at top-right
        day_label = ctk.CTkLabel(content_frame, text="", font=FONT_LABEL, 
                              text_color=TEXT_COLOR, anchor="e")
        day_label.pack(side="top", anchor="ne", padx=2, pady=1)
        
        # Special day label (not used with our holiday implementation)
        special_label = ctk.CTkLabel(content_frame, text="", font=FONT_SMALL,
                                 text_color="#AAAAAA", anchor="w")
        special_label.pack(side="bottom", anchor="sw", padx=1, pady=0)
        
        # Tasks area (includes holidays and regular tasks)
        tasks_frame = ctk.CTkFrame(content_frame, fg_color="transparent", corner_radius=0)
        tasks_frame.pack(fill="both", expand=True, padx=0, pady=0)
        
        # Store references for updating
        self.calendar_cells[(row_idx, col_idx)] = {
            'frame': cell_frame,
            'content': content_frame,
            'day_label': day_label,
            'special_label': special_label,
            'tasks_frame': tasks_frame,
            'current_state': None
        }
        
    def _clear_calendar_cells(self):
        """Clear all calendar cells before updating."""
        for cell_key, cell_data in self.calendar_cells.items():
            cell_data['day_label'].configure(text="")
            cell_data['special_label'].configure(text="")
            # Clear ALL widgets in the tasks frame, including holiday frames
            for widget in cell_data['tasks_frame'].winfo_children():
                widget.destroy()
            cell_data['frame'].configure(fg_color=BACKGROUND_COLOR, border_color="#333344")
            
    def _configure_cell_appearance(self, cell_data, current_date, day_num, today):
        """Configure the appearance of a calendar cell based on date type."""
        # Set basic appearance
        if current_date == today:
            # Highlight today's cell
            cell_data['frame'].configure(fg_color="#2D2D4D", border_color=HIGHLIGHT_COLOR)
            cell_data['day_label'].configure(text=str(day_num), font=("Helvetica Neue", 12, "bold"))
        else:
            cell_data['frame'].configure(fg_color=BACKGROUND_COLOR)
            cell_data['day_label'].configure(text=str(day_num), font=FONT_LABEL)
    
    def prev_month(self):
        """Navigate to the previous month in monthly view."""
        self.displayed_year, self.displayed_month = self._get_prev_month(self.displayed_year, self.displayed_month)
        
        # Update the data without recreating structure
        self._update_monthly_view_data(self.search_entry.get()) 
        
        # Preload data for next navigation
        self.after(100, lambda: self._preload_adjacent_months())

    def next_month(self):
        """Navigate to the next month in monthly view."""
        self.displayed_year, self.displayed_month = self._get_next_month(self.displayed_year, self.displayed_month)
            
        # Update the data without recreating structure
        self._update_monthly_view_data(self.search_entry.get())
        
        # Preload data for next navigation
        self.after(100, lambda: self._preload_adjacent_months())
        
    def open_task_dialog_for_date(self, date):
        """Open task dialog pre-set to a specific date."""
        # Create a temporary default task to pre-set the date
        # Use current hour rounded up to next hour as the default time
        local_tz = datetime.now().astimezone().tzinfo
        now = datetime.now()
        
        # Round up to the next hour
        if now.minute > 0 or now.second > 0:
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        else:
            next_hour = now
            
        # Combine selected date with time
        start_dt = datetime.combine(date, next_hour.time())
        start_dt = start_dt.replace(tzinfo=local_tz)
        start_dt_utc = local_to_utc(start_dt)
        
        # Default 1 hour duration
        end_dt_utc = start_dt_utc + timedelta(hours=1)
        
        # Create temp task just to set the date
        temp_task = Task("", start_dt_utc, end_dt_utc)
        self.open_task_dialog(temp_task)

# API WORKER THREAD
class APIWorker:
    """Worker thread for handling API calls without blocking the UI."""
    def __init__(self, parent):
        self.parent = parent
        self.queue = queue.Queue()
        self.running = True
        self.event = threading.Event()
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        
    def add_task(self, task_type, func, callback=None, error_callback=None, **kwargs):
        """Add a task to the queue and signal the worker thread."""
        self.queue.put((task_type, func, callback, error_callback, kwargs))
        self.event.set()  # Signal that there's work to do
        
    def _worker_loop(self):
        """Main worker loop that processes queued tasks using event notification."""
        while self.running:
            # Wait for the event to be set (new task or shutdown)
            self.event.wait()
            
            # Process all tasks in the queue
            while not self.queue.empty() and self.running:
                try:
                    task_type, func, callback, error_callback, kwargs = self.queue.get(block=False)
                    
                    try:
                        if task_type not in ['background_fetch', 'preload']:
                            self.parent.after(0, lambda: self.parent.show_loading(True))
                        
                        result = func(**kwargs)
                        
                        if callback:
                            cb = callback
                            res = result
                            self.parent.after(0, lambda cb=cb, res=res: cb(res))
                            
                    except Exception as e:
                        print(f"Error in worker thread ({task_type}): {str(e)}")
                        if error_callback:
                            # Create a local copy of the error callback and error to avoid closure issues
                            err_cb = error_callback
                            err = e
                            self.parent.after(0, lambda err_cb=err_cb, err=err: err_cb(err))
                    
                    finally:
                        # Hide loading indicator
                        if task_type not in ['background_fetch', 'preload']:
                            self.parent.after(0, lambda: self.parent.show_loading(False))
                        self.queue.task_done()
                        
                except queue.Empty:
                    # Queue is empty now, rare case due to race condition
                    break
            
            # Clear the event since we've processed all tasks
            self.event.clear()
                
    def stop(self):
        """Stop the worker thread."""
        self.running = False
        self.event.set()  # Wake up the thread to check running state
        self.thread.join(timeout=1.0)

# APPLICATION ENTRY POINT
if __name__ == "__main__":
    # Set up CustomTkinter theme
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    
    # Initialize services
    auth_service = GoogleAuthService(SCOPES)
    calendar_manager = CalendarManager(auth_service)
    
    # Start the application
    app = TodoAppUI(calendar_manager)
    app.mainloop()