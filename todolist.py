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
calendar.setfirstweekday(6)  # 6 corresponds to Sunday in the calendar module
# CONSTANTS AND STYLING
# API Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
TOKEN_FILE = 'token.json'
CREDENTIALS_FILE = 'credentials.json'


# Color Theme
BACKGROUND_COLOR = "#1E1E2F"   # Dark background       
NAV_BG_COLOR = "#2A2A3B"       # navigation bar background
DROPDOWN_BG_COLOR = "#252639"  # dialog/dropdown background
CARD_COLOR = "#1F6AA5"         # task card background (matches button blue)
TEXT_COLOR = "#E0E0E0"         # Light text

# Fonts
FONT_HEADER = ("Helvetica Neue", 18, "bold")
FONT_LABEL = ("Helvetica Neue", 14)
FONT_SMALL = ("Helvetica Neue", 12)
FONT_DAY = ("Helvetica Neue", 12, "bold")
FONT_DATE = ("Helvetica Neue", 18, "bold")
PADDING = 10

# HELPER FUNCTIONS
def convert_to_24(hour_str, period):
    """Convert 12-hour time format to 24-hour format."""
    hour = int(hour_str)
    if period == "AM":
        return 0 if hour == 12 else hour
    else:  # PM
        return hour if hour == 12 else hour + 12

def convert_from_24(hour_24_str):
    """Convert 24-hour time format to 12-hour format with AM/PM."""
    hour_24 = int(hour_24_str)
    if hour_24 == 0:
        return 12, "AM"
    elif hour_24 < 12:
        return hour_24, "AM"
    elif hour_24 == 12:
        return 12, "PM"
    else:
        return hour_24 - 12, "PM"

def utc_to_local(utc_str):
    """Convert UTC datetime string to local datetime object."""
    utc_dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
    local_dt = utc_dt.astimezone()
    return local_dt

def local_to_utc(local_dt):
    """Convert local datetime object to UTC datetime object."""
    return local_dt.astimezone(timezone.utc)

def format_task_time(start_dt, end_dt):
    """Format task start and end time consistently.
    
    Args:
        start_dt: Start datetime (UTC)
        end_dt: End datetime (UTC)
        
    Returns:
        str: Formatted time string (e.g. "9:00 AM - 10:00 AM" or "All Day")
    """
    # Convert to local timezone
    local_start = start_dt.astimezone()
    local_end = end_dt.astimezone()
    
    # Check if it's an all-day event
    if local_start.hour == 0 and local_start.minute == 0 and local_end.hour == 23 and local_end.minute == 59:
        return "All Day"
    else:
        # Format times in 12-hour format with AM/PM
        start_str = local_start.strftime('%I:%M %p').lstrip('0')
        end_str = local_end.strftime('%I:%M %p').lstrip('0')
        return f"{start_str} - {end_str}"

def parse_event_datetime(event, field='start', as_date=False):
    """Parse datetime from a Google Calendar event field.
    
    Args:
        event: The Google Calendar event dictionary
        field: Field to parse (either 'start' or 'end')
        as_date: If True, return just the date object instead of datetime
        
    Returns:
        Datetime object with timezone information
    """
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
        if field == 'start':
            local_dt = datetime.combine(local_date, datetime.min.time())
        else:  # field == 'end'
            local_dt = datetime.combine(local_date, datetime.max.time())
            
        # Make timezone-aware
        return local_dt.astimezone().astimezone(timezone.utc)
        
    return datetime.now(timezone.utc)  # Fallback


# GOOGLE API CLASSES
class GoogleAuthService:
    """Handles authentication with Google API."""
    def __init__(self, scopes, token_file=TOKEN_FILE, credentials_file=CREDENTIALS_FILE):
        self.scopes = scopes
        self.token_file = token_file
        self.credentials_file = credentials_file
        self.creds = None
        # Time buffer in seconds before expiration to trigger refresh (default 5 minutes)
        self.refresh_buffer = 300

    def get_calendar_service(self):
        """Get an authenticated Google Calendar service."""
        creds = self._get_credentials()
        return build('calendar', 'v3', credentials=creds)

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
        return creds
        
    def auto_refresh_token(self):
        """Check if token is about to expire and refresh it proactively.
        
        Returns:
            bool: True if token was refreshed, False otherwise
        """
        if not self.creds:
            self.creds = self._get_credentials()
            return True
            
        # Check if token exists and will expire soon
        if self.creds and hasattr(self.creds, 'expiry'):
            # Calculate time until expiration
            now = datetime.now(timezone.utc)
            if self.creds.expiry and self.creds.expiry.tzinfo is None:
                # Convert naive datetime to aware datetime
                expiry = self.creds.expiry.replace(tzinfo=timezone.utc)
            else:
                expiry = self.creds.expiry
                
            # If token will expire within buffer time, refresh it
            time_until_expiry = (expiry - now).total_seconds() if expiry else 0
            
            if time_until_expiry < self.refresh_buffer:
                print(f"Token will expire soon ({time_until_expiry:.1f} seconds). Refreshing...")
                try:
                    self.creds = self._refresh_credentials(self.creds)
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
        self.holiday_cache = {}  # Cache for holidays {(year, month): {date: holiday_name}}
        self.event_cache = {}    # Cache for events {(year, month): [events]}
        self.fetch_lock = threading.Lock()  # Lock for thread safety
        self.fetching_ranges = set()  # Track which date ranges are currently being fetched
    
    def _ensure_valid_token(self):
        """Ensure the token is valid before making API calls."""
        try:
            # Check if token needs refreshing
            refreshed = self.auth_service.auto_refresh_token()
            if refreshed:
                # Re-initialize the service with the refreshed token
                self.service = self.auth_service.get_calendar_service()
        except Exception as e:
            print(f"Error ensuring valid token: {str(e)}")

    def fetch_events(self, calendar_id='primary', max_results=50, page_token=None, 
                     start_date=None, end_date=None):
        """Fetch events from Google Calendar with pagination support.
        
        Args:
            calendar_id: ID of the calendar to fetch from
            max_results: Maximum number of results per page
            page_token: Token for pagination
            start_date: Optional start date to filter by (datetime)
            end_date: Optional end date to filter by (datetime)
            
        Returns:
            Tuple of (events list, next_page_token)
        """
        # Ensure valid token before making API call
        self._ensure_valid_token()
        
        # Set time range
        if not start_date:
            start_date = datetime.now(timezone.utc)
        
        time_min = start_date.isoformat().replace('+00:00', 'Z')
        time_max = None
        if end_date:
            time_max = end_date.isoformat().replace('+00:00', 'Z')
        
        # Build the request parameters
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
            # Execute the request
            events_result = self.service.events().list(**params).execute()
            
            # Get the events and next page token
            events = events_result.get('items', [])
            next_token = events_result.get('nextPageToken')
            
            return events, next_token
        except Exception as e:
            print(f"Error fetching events: {str(e)}")
            return [], None
    
    def fetch_events_for_range(self, start_date, end_date, calendar_id='primary'):
        """Fetch all events within a date range, using the cache if available.
        
        Args:
            start_date: Start date (datetime)
            end_date: End date (datetime)
            calendar_id: ID of the calendar to fetch from
            
        Returns:
            List of event items in the range
        """
        # Convert to datetime objects if strings
        if isinstance(start_date, str):
            start_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
        if isinstance(end_date, str):
            end_date = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        
        # Create a unique identifier for this date range
        range_id = (calendar_id, start_date.isoformat(), end_date.isoformat())
        
        # Check if we're already fetching this range
        with self.fetch_lock:
            if range_id in self.fetching_ranges:
                return []  # Avoid duplicate fetches
            self.fetching_ranges.add(range_id)
        
        try:
            # Ensure valid token before potential API calls
            self._ensure_valid_token()
            
            # Generate month keys for all months in the range
            month_keys = self._get_month_keys_in_range(start_date, end_date)
            
            # Check if all months are cached
            all_cached = all(key in self.event_cache for key in month_keys)
            
            if all_cached:
                # Get events from cache and filter by date range
                return self._get_cached_events_in_range(month_keys, start_date, end_date)
            
            # Identify which months need to be fetched
            uncached_months = [key for key in month_keys if key not in self.event_cache]
            
            # Get cached events for the cached months
            cached_events = self._get_cached_events_in_range(
                [key for key in month_keys if key in self.event_cache], 
                start_date, 
                end_date
            )
            
            # Fetch only the uncached months
            new_events = []
            for month_key in uncached_months:
                year, month = month_key
                # Calculate start and end date for this month
                month_start = datetime(year, month, 1, tzinfo=timezone.utc)
                if month == 12:
                    month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
                else:
                    month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
                
                # Adjust to requested date range if needed
                fetch_start = max(month_start, start_date)
                fetch_end = min(month_end, end_date)
                
                # Fetch events for this month
                month_events = []
                next_token = None
                
                while True:
                    batch, next_token = self.fetch_events(
                        calendar_id=calendar_id,
                        max_results=50,
                        page_token=next_token,
                        start_date=fetch_start,
                        end_date=fetch_end
                    )
                    
                    if not batch:
                        break
                        
                    month_events.extend(batch)
                    
                    # Break if no more pages
                    if not next_token:
                        break
                
                # Update cache with these events
                self._update_cache_with_events(month_events)
                new_events.extend(month_events)
            
            # Merge cached and new events, avoiding duplicates
            all_events = cached_events.copy()
            existing_ids = {event.get('id') for event in cached_events if event.get('id')}
            
            for event in new_events:
                event_id = event.get('id')
                if event_id and event_id not in existing_ids:
                    all_events.append(event)
                    existing_ids.add(event_id)
            
            return all_events
            
        except Exception as e:
            print(f"Error fetching events for range: {str(e)}")
            return []
        finally:
            # Remove from fetching set
            with self.fetch_lock:
                self.fetching_ranges.discard(range_id)
    
    def _get_month_keys_in_range(self, start_date, end_date):
        """Generate all month keys (year, month) in a date range."""
        month_keys = []
        current = (start_date.year, start_date.month)
        end = (end_date.year, end_date.month)
        
        month_keys.append(current)
        while current != end:
            year, month = current
            if month == 12:
                current = (year + 1, 1)
            else:
                current = (year, month + 1)
            month_keys.append(current)
            
        return month_keys
    
    def _get_cached_events_in_range(self, month_keys, start_date, end_date):
        """Get events from cache that fall within the date range."""
        all_events = []
        
        for key in month_keys:
            events = self.event_cache.get(key, [])
            for event in events:
                event_start = self._get_event_start_datetime(event)
                if start_date <= event_start <= end_date:
                    all_events.append(event)
                    
        return all_events
    
    def _update_cache_with_events(self, events):
        """Update the event cache with new events."""
        with self.fetch_lock:
            for event in events:
                event_start = self._get_event_start_datetime(event)
                month_key = (event_start.year, event_start.month)
                
                # Initialize cache for this month if needed
                if month_key not in self.event_cache:
                    self.event_cache[month_key] = []
                    
                # Check if event already exists in cache
                event_id = event.get('id')
                if event_id:
                    # Remove existing event with same ID if present
                    self.event_cache[month_key] = [e for e in self.event_cache[month_key] 
                                                  if e.get('id') != event_id]
                    
                # Add event to cache
                self.event_cache[month_key].append(event)
    
    def _get_event_start_datetime(self, event):
        """Extract start datetime from an event object."""
        return parse_event_datetime(event, field='start')
    
    def clear_cache_for_month(self, year, month):
        """Clear the cache for a specific month to force refresh."""
        month_key = (year, month)
        with self.fetch_lock:
            if month_key in self.event_cache:
                del self.event_cache[month_key]

    def add_event(self, calendar_id, event):
        """Add a new event to Google Calendar."""
        # Ensure valid token before making API call
        self._ensure_valid_token()
        
        try:
            result = self.service.events().insert(
                calendarId=calendar_id,
                body=event
            ).execute()
            
            # Update cache with the new event
            self._update_cache_with_events([result])
            return result
        except Exception as e:
            print(f"Error adding event: {str(e)}")
            raise

    def update_event(self, calendar_id, event_id, updated_event):
        """Update an existing event in Google Calendar."""
        # Ensure valid token before making API call
        self._ensure_valid_token()
        
        try:
            result = self.service.events().update(
                calendarId=calendar_id,
                eventId=event_id,
                body=updated_event
            ).execute()
            
            # Update cache with the updated event
            self._update_cache_with_events([result])
            return result
        except Exception as e:
            print(f"Error updating event: {str(e)}")
            raise

    def delete_event(self, calendar_id, event_id):
        """Delete an event from Google Calendar."""
        # Ensure valid token before making API call
        self._ensure_valid_token()
        
        try:
            result = self.service.events().delete(
                calendarId=calendar_id,
                eventId=event_id
            ).execute()
            
            # Remove event from cache
            with self.fetch_lock:
                for month_events in self.event_cache.values():
                    for i, event in enumerate(month_events):
                        if event.get('id') == event_id:
                            month_events.pop(i)
                            break
            
            return result
        except Exception as e:
            print(f"Error deleting event: {str(e)}")
            raise

    def fetch_holidays(self, year, month):
        """Fetch holidays for a specific month from Google Calendar."""
        # Ensure valid token before making API call
        self._ensure_valid_token()
        
        # Check cache first
        cache_key = (year, month)
        if cache_key in self.holiday_cache:
            return self.holiday_cache[cache_key]
            
        try:
            # Public holiday calendar ID for US holidays
            holiday_calendar_id = 'en.usa#holiday@group.v.calendar.google.com'
            
            # Calculate time range for the month
            start_date = datetime(year, month, 1, tzinfo=timezone.utc)
            # Calculate last day of month
            if month == 12:
                end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
            else:
                end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(days=1)
            end_date = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=timezone.utc)
            
            # Format dates for API request
            time_min = start_date.isoformat().replace('+00:00', 'Z')
            time_max = end_date.isoformat().replace('+00:00', 'Z')
            
            # Call Google Calendar API to get holidays
            holidays_result = self.service.events().list(
                calendarId=holiday_calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            
            # Process the holidays
            holidays = {}
            for item in holidays_result.get('items', []):
                if 'date' in item['start']:  # All-day event (typical for holidays)
                    event_date = datetime.fromisoformat(item['start']['date']).date()
                    holidays[event_date] = item['summary']
                    
            # Cache the results
            self.holiday_cache[cache_key] = holidays
            return holidays
            
        except Exception as e:
            print(f"Error fetching holidays: {str(e)}")
            return {}  # Return empty dict on error

# TASK AND REMINDER CLASSES
class Task:
    """Represents a task/event with start and end times."""
    def __init__(self, summary, start_dt, end_dt, task_id=None, reminder_minutes=10, status='Pending'):
        self.summary = summary
        self.start_dt = start_dt  # datetime (UTC)
        self.end_dt = end_dt      # datetime (UTC)
        self.task_id = task_id
        self.reminder_minutes = reminder_minutes
        self.status = status

class ReminderManager:
    """Manages task reminders and notifications."""
    def __init__(self, root):
        self.root = root
        self.reminders = []  # List of Task objects

    def add_reminder(self, task):
        """Add a task to the reminder list."""
        self.reminders.append(task)

    def check_reminders(self):
        """Check if any reminders need to be shown and schedule next check."""
        now = datetime.now(timezone.utc)
        for task in self.reminders:
            if task.status == 'Pending' and (task.start_dt - now) <= timedelta(minutes=task.reminder_minutes) and (task.start_dt - now) > timedelta(0):
                # Use the shared time formatting function
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
        
        # Position the dialog near the center of the parent window
        if master:
            parent_x = master.winfo_rootx()
            parent_y = master.winfo_rooty()
            parent_width = master.winfo_width()
            parent_height = master.winfo_height()
            
            # Calculate position (centered on parent)
            self.dialog_width = 400
            self.dialog_height = 500
            x_pos = parent_x + (parent_width - self.dialog_width) // 2
            y_pos = parent_y + (parent_height - self.dialog_height) // 2
            
            # Set window size and position
            self.geometry(f"{self.dialog_width}x{self.dialog_height}+{x_pos}+{y_pos}")
            
        # Set up initial time values
        self.setup_initial_time()
        
        # Build the UI after a short delay to improve responsiveness
        self.after(10, self.build_widgets)
        
    def setup_initial_time(self):
        """Set up initial time values."""
        self.initial_hour = 9  # Default to 9 AM
        self.initial_min = 0
        self.initial_period = "AM"
        
        # If editing task, extract its time
        if self.task:
            # Get task time (local)
            local_start = self.task.start_dt.astimezone()
            local_end = self.task.end_dt.astimezone()
            
            # Convert to 12-hour format for later use
            self.initial_hour, self.initial_period = convert_from_24(str(local_start.hour))
            self.initial_min = local_start.minute
        else:
            # Set to next hour if creating new task
            now = datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            hour_12, period = convert_from_24(str(next_hour.hour))
            self.initial_hour = hour_12
            self.initial_min = 0
            self.initial_period = period

    def build_widgets(self):
        """Create and arrange all dialog widgets."""
        # Header
        header_text = "Edit Task" if self.task else "Add New Task"
        header = ctk.CTkLabel(self, text=header_text, font=FONT_HEADER, text_color=TEXT_COLOR)
        header.pack(pady=PADDING)

        # Task Summary Entry
        summary_label = ctk.CTkLabel(self, text="Task Summary:", font=FONT_LABEL, text_color=TEXT_COLOR)
        summary_label.pack(pady=(5, 0))
        self.summary_entry = ctk.CTkEntry(self, font=FONT_LABEL)
        if self.task:
            self.summary_entry.insert(0, self.task.summary)
        self.summary_entry.pack(pady=5, padx=20, fill="x")

        # Date Picker
        self.calendar = Calendar(self, date_pattern="y-mm-dd")
        self.calendar.pack(pady=5)

        # Time Selector
        time_frame = ctk.CTkFrame(self, fg_color=DROPDOWN_BG_COLOR)
        time_frame.pack(pady=5)

        # Start Time
        start_label = ctk.CTkLabel(time_frame, text="Start Time (HH:MM):", font=FONT_LABEL, text_color=TEXT_COLOR)
        start_label.grid(row=0, column=0, padx=5, pady=5)
        self.start_hour = Spinbox(time_frame, from_=1, to=12, width=4, format="%02.0f", command=self._update_end_time)
        self.start_hour.grid(row=0, column=1, padx=5, pady=5)
        self.start_min = Spinbox(time_frame, from_=0, to=59, width=4, format="%02.0f", command=self._update_end_time)
        self.start_min.grid(row=0, column=2, padx=5, pady=5)
        self.start_period = ctk.CTkOptionMenu(time_frame, values=["AM", "PM"], width=60)
        self.start_period.set(self.initial_period)
        self.start_period.grid(row=0, column=3, padx=5, pady=5)

        # End Time
        end_label = ctk.CTkLabel(time_frame, text="End Time (HH:MM):", font=FONT_LABEL, text_color=TEXT_COLOR)
        end_label.grid(row=1, column=0, padx=5, pady=5)
        self.end_hour = Spinbox(time_frame, from_=1, to=12, width=4, format="%02.0f")
        self.end_hour.grid(row=1, column=1, padx=5, pady=5)
        self.end_min = Spinbox(time_frame, from_=0, to=59, width=4, format="%02.0f")
        self.end_min.grid(row=1, column=2, padx=5, pady=5)
        self.end_period = ctk.CTkOptionMenu(time_frame, values=["AM", "PM"], width=60)
        self.end_period.set(self.initial_period)
        self.end_period.grid(row=1, column=3, padx=5, pady=5)

        # Set up event bindings for automatic end time updates
        self.start_hour.bind("<KeyRelease>", self._update_end_time)
        self.start_min.bind("<KeyRelease>", self._update_end_time)
        self.start_period.configure(command=self._update_end_time)

        # Initialize time fields if editing existing task
        if self.task:
            self._init_time_fields()
        else:
            # Set start time to initial values
            self.start_hour.delete(0, "end")
            self.start_hour.insert(0, f"{self.initial_hour:02d}")
            self.start_min.delete(0, "end")
            self.start_min.insert(0, f"{self.initial_min:02d}")
            
            # Set end time to one hour after start
            self._update_end_time()

        # Action Buttons
        btn_frame = ctk.CTkFrame(self, fg_color=DROPDOWN_BG_COLOR)
        btn_frame.pack(pady=PADDING)
        
        # Add Delete button if editing existing task
        if self.task and self.task.task_id:
            delete_btn = ctk.CTkButton(
                btn_frame, 
                text="Delete", 
                font=FONT_LABEL, 
                fg_color="#AA3333", 
                hover_color="#CC5555",
                command=self.delete_task
            )
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
            # Confirm deletion
            if hasattr(self.master, 'delete_task'):
                self.master.delete_task(self.task)
            self.destroy()

    def _update_end_time(self, event=None):
        """Update end time to be 1 hour after start time."""
        try:
            # Get start time values
            start_hour = int(self.start_hour.get())
            start_min = int(self.start_min.get())
            start_period = self.start_period.get()
            
            # Convert to 24-hour format
            start_hour_24 = convert_to_24(str(start_hour), start_period)
            
            # Calculate end time (1 hour later)
            end_hour_24 = (start_hour_24 + 1) % 24
            
            # Convert back to 12-hour format
            end_hour_12, end_period = convert_from_24(str(end_hour_24))
            
            # Update end time fields
            self.end_hour.delete(0, "end")
            self.end_hour.insert(0, f"{end_hour_12:02d}")
            self.end_min.delete(0, "end")
            self.end_min.insert(0, f"{start_min:02d}")
            self.end_period.set(end_period)
        except (ValueError, TypeError):
            # Handle any conversion errors silently
            pass

    def _init_time_fields(self):
        """Initialize time fields when editing an existing task."""
        # Convert UTC to local time
        local_start = self.task.start_dt.astimezone()
        local_end = self.task.end_dt.astimezone()
        
        # Set the calendar date
        self.calendar.selection_set(local_start.date())
        
        # Set start time
        start_hour, start_period = convert_from_24(str(local_start.hour))
        self.start_hour.delete(0, "end")
        self.start_hour.insert(0, f"{start_hour:02d}")
        self.start_min.delete(0, "end")
        self.start_min.insert(0, f"{local_start.minute:02d}")
        self.start_period.set(start_period)
        
        # Set end time
        end_hour, end_period = convert_from_24(str(local_end.hour))
        self.end_hour.delete(0, "end")
        self.end_hour.insert(0, f"{end_hour:02d}")
        self.end_min.delete(0, "end")
        self.end_min.insert(0, f"{local_end.minute:02d}")
        self.end_period.set(end_period)

    def confirm(self):
        """Validate input and create/update task."""
        # Validate task summary
        summary = self.summary_entry.get().strip()
        if not summary:
            self.master.show_alert("Task summary cannot be empty.", alert_type="error", duration=4000)
            return

        # Get and validate date/time
        date_str = self.calendar.get_date()
        try:
            # Convert time format
            start_hour_24 = convert_to_24(self.start_hour.get(), self.start_period.get())
            end_hour_24 = convert_to_24(self.end_hour.get(), self.end_period.get())
            
            # Create datetime objects
            local_tz = datetime.now().astimezone().tzinfo
            start_dt_local = datetime.strptime(f"{date_str} {start_hour_24:02d}:{self.start_min.get()}", "%Y-%m-%d %H:%M")
            start_dt_local = start_dt_local.replace(tzinfo=local_tz)
            start_dt = local_to_utc(start_dt_local)
            
            end_dt_local = datetime.strptime(f"{date_str} {end_hour_24:02d}:{self.end_min.get()}", "%Y-%m-%d %H:%M")
            end_dt_local = end_dt_local.replace(tzinfo=local_tz)
            end_dt = local_to_utc(end_dt_local)
            
            # Validate time range
            if end_dt <= start_dt:
                self.master.show_alert("End time must be after start time.", alert_type="error", duration=4000)
                return
        except Exception as e:
            self.master.show_alert(f"Invalid date or time: {str(e)}", alert_type="error", duration=4000)
            return

        # Update or create task
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
    
    # Initialization and Setup
    def __init__(self, calendar_manager):
        super().__init__()
        self.calendar_manager = calendar_manager
        
        # Application setup
        self.title("To-Do List")
        self.geometry("1200x1000")
        self.configure(fg_color=BACKGROUND_COLOR)
        
        # State variables
        self.task_list = []
        self.current_view = "daily"
        
        # Monthly view state
        today = datetime.now().date()
        self.displayed_year = today.year
        self.displayed_month = today.month
        
        # Performance optimization
        self.task_cache = {}  # Format: {(year, month): tasks_by_date_dict}
        self.preload_active = False  # Flag to prevent multiple preload operations
        self.ui_dirty = True         # Flag to indicate if UI needs refresh
        self.loading = False         # Loading state
        self.worker = APIWorker(self) # Background worker thread
        
        # Initialize components
        self.reminder_manager = ReminderManager(self)
        self.monthly_view_frame = None
        self.content_frame = None
        self.calendar_cells = {}
        self.rendered_days = set()   # Track which days have been rendered in daily view

        # Set up UI components
        self._setup_alert_area()
        self._setup_navbar()
        self._setup_main_layout()
        
        # Initialize data and start periodic tasks
        self.refresh_events()
        self.reminder_manager.check_reminders()
        
        # Set up virtual rendering checker for scrollable content
        self.after(100, self._check_scroll_position)
        
        # Set up token refresh checker (check every 10 minutes)
        self.check_token_refresh()
        
        # Set up window close handler
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        
    # Add this new method
    def check_token_refresh(self):
        """Periodically check if token needs refresh and schedule next check."""
        try:
            # Access the auth_service through calendar_manager
            if hasattr(self.calendar_manager, 'auth_service'):
                refreshed = self.calendar_manager.auth_service.auto_refresh_token()
                if refreshed:
                    self.show_alert("Authentication token refreshed successfully", duration=3000)
        except Exception as e:
            print(f"Error checking token refresh: {str(e)}")
        finally:
            # Check again in 10 minutes (600000 ms)
            self.after(600000, self.check_token_refresh)
        
    def _on_close(self):
        """Clean up resources before closing."""
        # Stop the worker thread
        if hasattr(self, 'worker'):
            self.worker.stop()
        # Destroy the window
        self.destroy()
        
    def show_loading(self, is_loading):
        """Show or hide loading indicator."""
        self.loading = is_loading
        if is_loading:
            if not hasattr(self, 'loading_label'):
                self.loading_label = ctk.CTkLabel(
                    self.alert_frame, 
                    text="Loading...", 
                    font=FONT_LABEL, 
                    text_color="#55AAFF"
                )
                self.loading_label.pack(side="right", padx=20, pady=5)
            self.alert_frame.pack(fill="x")
        else:
            if hasattr(self, 'loading_label'):
                self.loading_label.pack_forget()
            if not self.alert_label.cget("text"):
                self.alert_frame.pack_forget()

    def _setup_alert_area(self):
        """Set up the alert/notification area."""
        self.alert_frame = ctk.CTkFrame(self, fg_color=BACKGROUND_COLOR, height=30)
        self.alert_frame.pack(fill="x")
        self.alert_label = ctk.CTkLabel(self.alert_frame, text="", font=FONT_LABEL, text_color=TEXT_COLOR)
        self.alert_label.pack(side="left", padx=20, pady=5)
        self.alert_frame.pack_forget()  # Hide initially

    def _check_scroll_position(self):
        """Check scroll position to implement virtual rendering."""
        if self.current_view == "daily" and hasattr(self, 'content_frame'):
            try:
                # Get visible region
                visible_top = self.content_frame._parent_canvas.yview()[0]
                visible_bottom = self.content_frame._parent_canvas.yview()[1]
                canvas_height = self.content_frame._parent_canvas.winfo_height()
                
                # Only render items in or near the visible area
                self._update_virtual_rendering(visible_top, visible_bottom, canvas_height)
            except Exception as e:
                print(f"Error checking scroll position: {str(e)}")
                
        # Schedule next check
        self.after(200, self._check_scroll_position)
        
    def _update_virtual_rendering(self, visible_top, visible_bottom, canvas_height):
        """Update which days are rendered based on scroll position."""
        if not hasattr(self, 'month_containers') or not self.month_containers:
            return
            
        # Convert fraction to actual pixels
        total_height = self.content_frame._parent_canvas.bbox("all")[3]
        visible_top_px = visible_top * total_height
        visible_bottom_px = visible_bottom * total_height
        
        # Add buffer zone (render a bit above and below visible area)
        buffer = canvas_height * 0.5
        render_top = max(0, visible_top_px - buffer)
        render_bottom = min(total_height, visible_bottom_px + buffer)
        
        for month_key, month_data in self.month_containers.items():
            month_frame = month_data.get('frame')
            if not month_frame:
                continue
                
            # Get position of this month container
            try:
                frame_y = month_frame.winfo_y()
                frame_height = month_frame.winfo_height()
                
                # Check if frame is in or near visible area
                if frame_y + frame_height < render_top or frame_y > render_bottom:
                    # Skip rendering days for this month - it's not visible
                    continue
                    
                # Render days for this month if not already rendered
                for day_key, day_data in month_data.get('days', {}).items():
                    if day_key not in self.rendered_days and not day_data.get('rendered', False):
                        # Render this day
                        self._render_day(month_key, day_key, day_data)
            except Exception:
                # Frame might not be mapped yet
                continue
        
    def _render_day(self, month_key, day_key, day_data):
        """Actually render a day's content."""
        if not day_data.get('frame') or not day_data.get('tasks'):
            return
            
        parent_frame = day_data.get('frame')
        tasks = day_data.get('tasks', [])
        
        # Mark as rendered
        day_data['rendered'] = True
        self.rendered_days.add(day_key)
        
        # Add tasks to the container
        tasks_container = day_data.get('container')
        if tasks_container:
            for task in tasks:
                self._add_task_to_container(tasks_container, task)

    def refresh_events(self):
        """Refresh events from Google Calendar using background thread."""
        self.ui_dirty = True
        
        # Define the callbacks
        def on_events_loaded(result):
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            # If there are more pages, fetch them in the background
            if next_token:
                self._fetch_next_page(next_token)
            else:
                # All data loaded, update the UI
                self._update_current_view()
        
        def on_error(error):
            self.show_alert(f"Error loading events: {str(error)}", alert_type="error", duration=5000)
            self._update_current_view()  # Update UI anyway to show what we have
        
        # Start date for fetching (today)
        start_date = datetime.now(timezone.utc)
        
        # Queue the API call in the worker thread
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
            
            # If there are more pages, fetch them
            if next_token:
                self._fetch_next_page(next_token)
            else:
                # All pages loaded, update the UI
                self._update_current_view()
        
        def on_error(error):
            print(f"Error loading next page: {str(error)}")
            # Update UI with what we have so far
            self._update_current_view()
        
        # Start date for fetching (today)
        start_date = datetime.now(timezone.utc)
        
        # Queue the API call in the worker thread
        self.worker.add_task(
            "background_fetch",
            self.calendar_manager.fetch_events,
            callback=on_next_page_loaded,
            error_callback=on_error,
            calendar_id='primary',
            max_results=50,
            page_token=page_token,
            start_date=start_date
        )
    
    def _update_current_view(self):
        """Update the current view after data has been loaded."""
        if self.current_view == "daily":
            self.build_daily_view(self.search_entry.get() if hasattr(self, 'search_entry') else "")
        elif self.current_view == "monthly":
            self._update_monthly_view_data(self.search_entry.get() if hasattr(self, 'search_entry') else "")
        self.ui_dirty = False
    
    def _process_loaded_events(self, events):
        """Process loaded events and update the task list and cache."""
        # Add events to task list (avoid duplicates)
        existing_ids = {task.task_id for task in self.task_list if task.task_id}
        added_count = 0
        
        for event in events:
            event_id = event.get('id')
            if event_id in existing_ids:
                continue  # Skip duplicates
                
            # Process event start time
            try:
                start_dt = parse_event_datetime(event, field='start')
                end_dt = parse_event_datetime(event, field='end')

                # Create task from event
                task = Task(event['summary'], start_dt, end_dt, task_id=event.get('id'))
                self.task_list.append(task)
                added_count += 1
                
                # Add to cache by date
                local_date = task.start_dt.astimezone().date()
                year_month = (local_date.year, local_date.month)
                
                # Initialize cache structure if not exists
                if year_month not in self.task_cache:
                    self.task_cache[year_month] = {}
                if local_date not in self.task_cache[year_month]:
                    self.task_cache[year_month][local_date] = []
                    
                # Add task to cache
                self.task_cache[year_month][local_date].append(task)
                
                # Add task to reminders
                self.reminder_manager.add_reminder(task)
            except Exception as e:
                print(f"Error processing event: {str(e)}")
        
        # Only update UI if we've added events and UI needs updating
        if added_count > 0 and self.ui_dirty:
            self._update_current_view()

    def build_daily_view(self, search_term=""):
        """Build the daily view with efficient rendering for visible content."""
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
                
                # Track days in this month container for virtual rendering
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
            
            # Store day data for lazy rendering
            month_key = (day.year, day.month)
            day_key = str(day)
            
            self.month_containers[month_key]['days'][day_key] = {
                'frame': day_frame,
                'container': tasks_container,
                'tasks': tasks_by_date[day],
                'rendered': False
            }
            
            # Only render tasks for visible days or current month
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
            
            # Render days that are now visible
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
        """Shared method to render a task UI element consistently across views.
        
        Args:
            parent_frame: Frame to add the task to
            task: Task object to render
            is_monthly_view: Whether rendering in monthly view (affects styling)
            truncate_length: Length to truncate summary text (None = no truncation)
            
        Returns:
            task_frame: The created task frame
        """
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

        # Create task summary label
        prefix = "• " if is_monthly_view else ""
        task_label = ctk.CTkLabel(
            task_frame, 
            text=f"{prefix}{display_summary}", 
            font=FONT_SMALL if is_monthly_view else FONT_LABEL, 
            text_color=TEXT_COLOR,
            anchor="w" if is_monthly_view else "center"
        )
        
        # Pack with appropriate padding based on view
        if is_monthly_view:
            task_label.pack(anchor="w", fill="x", padx=2, pady=(1, 0))
        else:
            task_label.pack(fill="x", padx=4, pady=(3, 0))
        
        # Create time label
        time_label = ctk.CTkLabel(
            task_frame,
            text=time_str,
            font=FONT_SMALL,
            text_color=TEXT_COLOR,
            anchor="w" if is_monthly_view else "center"
        )
        
        # Pack with appropriate padding based on view
        if is_monthly_view:
            time_label.pack(anchor="w", fill="x", padx=2, pady=(0, 1))
        else:
            time_label.pack(fill="x", padx=4, pady=(0, 3))
        
        # Bind click events for editing
        task_frame.bind("<Button-1>", lambda e, t=task: self.open_task_dialog(t))
        task_label.bind("<Button-1>", lambda e, t=task: self.open_task_dialog(t))
        time_label.bind("<Button-1>", lambda e, t=task: self.open_task_dialog(t))
        
        return task_frame

    def _add_task_to_container(self, container, task):
        """Add a single task to a container."""
        # Use the shared render method
        task_frame = self._render_task(container, task)
        task_frame.pack(fill="x", pady=PADDING/3)

    def _add_tasks_to_cell(self, parent_frame, tasks, max_tasks):
        """Helper to add tasks to a cell - separated for better readability."""
        # Clear all existing widgets first
        for widget in parent_frame.winfo_children():
            widget.destroy()
            
        tasks_added_count = 0
        for i, task in enumerate(tasks):
            if i >= max_tasks:
                more_label = ctk.CTkLabel(parent_frame, text=f"+ {len(tasks) - max_tasks} more", 
                                       font=FONT_SMALL, text_color="#AAAAAA", anchor="w")
                more_label.pack(anchor="w", fill="x", padx=2, pady=0)
                break
            
            # Use the shared render method with monthly view settings
            task_frame = self._render_task(parent_frame, task, is_monthly_view=True, truncate_length=14)
            task_frame.pack(fill="x", padx=1, pady=1)
            tasks_added_count += 1
            
        return tasks_added_count
    
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
            if task and task.task_id:
                # Update existing task
                updated_event = {
                    'summary': new_task.summary,
                    'start': {'dateTime': new_task.start_dt.isoformat(), 'timeZone': 'UTC'},
                    'end': {'dateTime': new_task.end_dt.isoformat(), 'timeZone': 'UTC'}
                }
                
                def on_update_success(result):
                    self.show_alert(f"Task updated: {new_task.summary}", duration=3000)
                    self.refresh_events()
                
                def on_update_error(error):
                    self.show_alert(f"Failed to update task: {str(error)}", alert_type="error", duration=4000)
                
                # Queue the update in the worker thread
                self.worker.add_task(
                    "update_task",
                    self.calendar_manager.update_event,
                    callback=on_update_success,
                    error_callback=on_update_error,
                    calendar_id='primary',
                    event_id=task.task_id,
                    updated_event=updated_event
                )
            else:
                # Create new task
                event = {
                    'summary': new_task.summary,
                    'start': {'dateTime': new_task.start_dt.isoformat(), 'timeZone': 'UTC'},
                    'end': {'dateTime': new_task.end_dt.isoformat(), 'timeZone': 'UTC'}
                }
                
                def on_create_success(result):
                    new_task.task_id = result.get('id')
                    self.show_alert(f"Task created: {new_task.summary}", duration=3000)
                    self.refresh_events()
                
                def on_create_error(error):
                    self.show_alert(f"Failed to add task: {str(error)}", alert_type="error", duration=4000)
                
                # Queue the creation in the worker thread
                self.worker.add_task(
                    "create_task",
                    self.calendar_manager.add_event,
                    callback=on_create_success,
                    error_callback=on_create_error,
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
            # Remove from local list
            self.task_list = [t for t in self.task_list if t.task_id != task.task_id]
            # Remove from cache
            for month_data in self.task_cache.values():
                for date, tasks in list(month_data.items()):
                    month_data[date] = [t for t in tasks if t.task_id != task.task_id]
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
        
        if search_term:
            filtered = {}
            search_term = search_term.lower()
            
            for date, tasks in tasks_by_date.items():
                matching_tasks = [task for task in tasks if search_term in task.summary.lower()]
                
                if matching_tasks:
                    filtered[date] = matching_tasks
            
            return filtered
        
        return tasks_by_date
    
    def _get_tasks_by_date_dict(self):
        """Get tasks organized by date from the task list."""
        tasks_dict = {}
        for task in self.task_list:
            local_date = task.start_dt.astimezone().date()
            if local_date not in tasks_dict:
                tasks_dict[local_date] = []
            tasks_dict[local_date].append(task)
        return tasks_dict

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
                
            # Store in cache
            self.task_cache[(self.displayed_year, self.displayed_month)] = tasks_by_date
            
            # Update the UI with these tasks
            self._update_calendar_cells(tasks_by_date, search_term)
            
        def on_fetch_error(error):
            self.show_alert(f"Error fetching events: {str(error)}", alert_type="error", duration=4000)
        
        # Check if we have cached data for this month
        month_key = (self.displayed_year, self.displayed_month)
        
        if month_key in self.task_cache:
            # Use cached data
            tasks_by_date = self.task_cache[month_key]
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
                    
                # Create task from event
                start_dt = parse_event_datetime(event, field='start')
                end_dt = parse_event_datetime(event, field='end')
                    
                task = Task(event['summary'], start_dt, end_dt, task_id=event.get('id'))
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
            next_month_key = (next_year, next_month)
            prev_month_key = (prev_year, prev_month)
            
            # Preload next month if not cached
            if next_month_key not in self.task_cache:
                self._preload_month_data(next_year, next_month)
            
            # Preload previous month if not cached
            if prev_month_key not in self.task_cache:
                self._preload_month_data(prev_year, prev_month)
                
        except Exception as e:
            print(f"Preload error: {str(e)}")
        finally:
            self.preload_active = False
    
    def _get_prev_month(self, year, month):
        """Get the previous month's year and month values."""
        if month == 1:
            return year - 1, 12
        else:
            return year, month - 1
    
    def _get_next_month(self, year, month):
        """Get the next month's year and month values."""
        if month == 12:
            return year + 1, 1
        else:
            return year, month + 1
    
    def _preload_month_data(self, year, month):
        """Preload data for a specific month."""
        def on_events_loaded(events):
            # Process events into tasks by date for the month
            tasks_by_date = {}
            
            for event in events:
                try:
                    # Extract the event date (in local time)
                    event_dt = parse_event_datetime(event, field='start')
                    local_date = event_dt.astimezone().date()
                    
                    # Only process events for this month
                    if local_date.month != month or local_date.year != year:
                        continue
                        
                    # Add to tasks by date
                    if local_date not in tasks_by_date:
                        tasks_by_date[local_date] = []
                        
                    # Create task from event
                    start_dt = parse_event_datetime(event, field='start')
                    end_dt = parse_event_datetime(event, field='end')
                        
                    task = Task(event['summary'], start_dt, end_dt, task_id=event.get('id'))
                    tasks_by_date[local_date].append(task)
                except Exception as e:
                    print(f"Error processing preloaded event: {str(e)}")
            
            # Store in cache for future use
            self.task_cache[(year, month)] = tasks_by_date
        
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
            
    def show_alert(self, message, alert_type="info", duration=3000):
        """Show an alert/notification message."""
        if alert_type == "error":
            self.alert_label.configure(text=message, text_color="#FF5555")
        elif alert_type == "info":
            self.alert_label.configure(text=message, text_color="#55FF55")
        else:
            self.alert_label.configure(text=message, text_color=TEXT_COLOR)
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
            cell_data['frame'].configure(fg_color="#2D2D4D", border_color="#6060A0")
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
        
    def open_task_dialog(self, task=None):
        """Open dialog to create new task or edit existing task."""
        def on_confirm(new_task):
            if task and task.task_id:
                # Update existing task
                updated_event = {
                    'summary': new_task.summary,
                    'start': {'dateTime': new_task.start_dt.isoformat(), 'timeZone': 'UTC'},
                    'end': {'dateTime': new_task.end_dt.isoformat(), 'timeZone': 'UTC'}
                }
                
                def on_update_success(result):
                    self.show_alert(f"Task updated: {new_task.summary}", duration=3000)
                    self.refresh_events()
                
                def on_update_error(error):
                    self.show_alert(f"Failed to update task: {str(error)}", alert_type="error", duration=4000)
                
                # Queue the update in the worker thread
                self.worker.add_task(
                    "update_task",
                    self.calendar_manager.update_event,
                    callback=on_update_success,
                    error_callback=on_update_error,
                    calendar_id='primary',
                    event_id=task.task_id,
                    updated_event=updated_event
                )
            else:
                # Create new task
                event = {
                    'summary': new_task.summary,
                    'start': {'dateTime': new_task.start_dt.isoformat(), 'timeZone': 'UTC'},
                    'end': {'dateTime': new_task.end_dt.isoformat(), 'timeZone': 'UTC'}
                }
                
                def on_create_success(result):
                    new_task.task_id = result.get('id')
                    self.show_alert(f"Task created: {new_task.summary}", duration=3000)
                    self.refresh_events()
                
                def on_create_error(error):
                    self.show_alert(f"Failed to add task: {str(error)}", alert_type="error", duration=4000)
                
                # Queue the creation in the worker thread
                self.worker.add_task(
                    "create_task",
                    self.calendar_manager.add_event,
                    callback=on_create_success,
                    error_callback=on_create_error,
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
            # Remove from local list
            self.task_list = [t for t in self.task_list if t.task_id != task.task_id]
            # Remove from cache
            for month_data in self.task_cache.values():
                for date, tasks in list(month_data.items()):
                    month_data[date] = [t for t in tasks if t.task_id != task.task_id]
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
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        
    def add_task(self, task_type, func, callback=None, error_callback=None, **kwargs):
        """Add a task to the queue.
        
        Args:
            task_type: String identifier for the type of task
            func: Function to call
            callback: Function to call with the result
            error_callback: Function to call if an error occurs
            **kwargs: Arguments to pass to func
        """
        self.queue.put((task_type, func, callback, error_callback, kwargs))
        
    def _worker_loop(self):
        """Main worker loop that processes queued tasks."""
        while self.running:
            try:
                task_type, func, callback, error_callback, kwargs = self.queue.get(timeout=0.5)
                
                try:
                    # Show loading indicator in UI
                    if task_type not in ['background_fetch', 'preload']:
                        self.parent.after(0, lambda: self.parent.show_loading(True))
                    
                    # Execute the function
                    result = func(**kwargs)
                    
                    # Call the callback in the main thread
                    if callback:
                        # Create a local copy of the callback and result to avoid closure issues
                        cb = callback  # Create a local reference that won't change
                        res = result   # Create a local reference to the result
                        self.parent.after(0, lambda cb=cb, res=res: cb(res))
                        
                except Exception as e:
                    print(f"Error in worker thread ({task_type}): {str(e)}")
                    # Call the error callback in the main thread
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
                # No tasks in queue, continue waiting
                pass
                
    def stop(self):
        """Stop the worker thread."""
        self.running = False
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