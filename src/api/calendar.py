import threading
import datetime
from src.core.utils import format_date, format_time, generate_id, format_iso_for_api, parse_iso_from_api, parse_event_datetime
from src.core.config import DEFAULT_CALENDAR_ID, API_MAX_RESULTS
from src.api.cache import CacheManager

class CalendarManager:
    """Manages Google Calendar events with local caching."""
    
    def __init__(self, auth_manager):
        """Initialize with an auth manager."""
        self.auth_service = auth_manager
        self.service = self.auth_service.get_calendar_service()
        self.cache = CacheManager()
        self.fetch_lock = threading.Lock()
        self.fetching_ranges = set()
        
    def fetch_events(self, calendar_id=DEFAULT_CALENDAR_ID, max_results=API_MAX_RESULTS, page_token=None, 
                     start_date=None, end_date=None):
        """Fetch events from Google Calendar with pagination support."""
        self._ensure_valid_token()
        
        if not start_date:
            start_date = datetime.datetime.now(datetime.timezone.utc)
        
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
    
    def get_events_for_month(self, year, month, calendar_id=DEFAULT_CALENDAR_ID):
        """Get all events for a specific month."""
        start_date = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
        if month == 12:
            end_date = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc) - datetime.timedelta(seconds=1)
        else:
            end_date = datetime.datetime(year, month + 1, 1, tzinfo=datetime.timezone.utc) - datetime.timedelta(seconds=1)
        return self.fetch_events(start_date, end_date, calendar_id)
    
    def get_event(self, event_id, calendar_id=DEFAULT_CALENDAR_ID):
        """Get a single event by ID from the API."""
        try:
            event = self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()
            return event
        except Exception as e:
            print(f"Error fetching event {event_id}: {str(e)}")
            return None

    def _ensure_valid_token(self):
        """Ensure the token is valid before making API calls."""
        try:
            refreshed = self.auth_service.auto_refresh_token()
            if refreshed:
                self.service = self.auth_service.get_calendar_service()
        except Exception as e:
            print(f"Error ensuring valid token: {str(e)}")

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
                month_start = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
                month_end = (datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc) if month == 12 
                            else datetime.datetime(year, month + 1, 1, tzinfo=datetime.timezone.utc)) - datetime.timedelta(seconds=1)
                
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
            
            start_date = datetime.datetime(year, month, 1, tzinfo=datetime.timezone.utc)
            if month == 12:
                end_date = datetime.datetime(year + 1, 1, 1, tzinfo=datetime.timezone.utc) - datetime.timedelta(days=1)
            else:
                end_date = datetime.datetime(year, month + 1, 1, tzinfo=datetime.timezone.utc) - datetime.timedelta(days=1)
            end_date = datetime.datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=datetime.timezone.utc)
            
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
                    event_date = datetime.datetime.fromisoformat(item['start']['date']).date()
                    holidays[event_date] = item['summary']
                    
            self.cache.add_holidays(year, month, holidays)
            return holidays
            
        except Exception as e:
            print(f"Error fetching holidays: {str(e)}")
            return {} 