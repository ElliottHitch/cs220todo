import calendar
from datetime import datetime, timezone, timedelta
import uuid

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

def format_date(dt):
    """Format date as YYYY-MM-DD."""
    if isinstance(dt, datetime):
        return dt.strftime('%Y-%m-%d')
    return dt.strftime('%Y-%m-%d')

def format_time(dt):
    """Format time as HH:MM AM/PM."""
    return format_datetime(dt, 'time', include_minutes=True)

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

def generate_id():
    """Generate a unique ID for tasks."""
    return str(uuid.uuid4())

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