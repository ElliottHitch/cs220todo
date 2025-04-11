import threading
from datetime import datetime
import time
from src.core.utils import parse_event_datetime
from src.core.models import Task

class CacheManager:
    """Centralized cache manager for all calendar data."""
    def __init__(self):
        self.events_by_month = {}
        self.tasks_by_date = {}
        self.holidays_by_month = {}
        self.cache_lock = threading.Lock()
        self.fetched_ranges = set()
        self.event_ids = set()
        self.tasks_by_id = {} 
        
    def add_event(self, event):
        """Add or update an event in the cache."""
        with self.cache_lock:
            self._add_event_internal(event)
    
    def _add_event_internal(self, event):
        """Internal method to add an event to the cache while holding the lock."""
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
        
        if event_id and event_id not in self.tasks_by_id:
            task = self._convert_event_to_task(event)
            if task:
                self.tasks_by_id[event_id] = task
        elif event_id and event_id in self.tasks_by_id:
            task = self._convert_event_to_task(event)
            if task:
                self.tasks_by_id[event_id] = task
        else:
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
                self._add_event_internal(event)
    
    def delete_event(self, event_id):
        """Delete an event from all caches."""
        with self.cache_lock:
            for month_key, events_list in list(self.events_by_month.items()):
                self.events_by_month[month_key] = [e for e in events_list if e.get('id') != event_id]
            
            for date, tasks_list in list(self.tasks_by_date.items()):
                self.tasks_by_date[date] = [t for t in tasks_list if getattr(t, 'task_id', None) != event_id]
            
            if event_id in self.tasks_by_id:
                del self.tasks_by_id[event_id]
                
            self.event_ids.discard(event_id)
    
    def clear_month(self, year, month):
        """Clear the cache for a specific month."""
        month_key = (year, month)
        with self.cache_lock:
            if month_key in self.events_by_month:
                for event in self.events_by_month[month_key]:
                    event_id = event.get('id')
                    self.event_ids.discard(event_id)
                    if event_id in self.tasks_by_id:
                        del self.tasks_by_id[event_id]
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
    
    def get_task_by_id(self, event_id):
        """Get a task by its event ID."""
        with self.cache_lock:
            return self.tasks_by_id.get(event_id)
    
    def _convert_event_to_task(self, event):
        """Convert a Google Calendar event to a Task object."""
        try:
            start_dt = parse_event_datetime(event, field='start')
            end_dt = parse_event_datetime(event, field='end')
            source = event.get('source', 'calendar')
            isAllDay = event.get('isAllDay', False)
            
            if 'date' in event.get('start', {}) and 'date' in event.get('end', {}):
                isAllDay = True
                
            return Task(event['summary'], start_dt, end_dt, task_id=event.get('id'), source=source, isAllDay=isAllDay)
        except Exception as e:
            print(f"Error converting event to task: {str(e)}")
            return None 