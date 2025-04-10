import threading
import datetime
from src.core.utils import format_date, format_time, generate_id, format_iso_for_api, parse_iso_from_api
from src.core.config import DEFAULT_CALENDAR_ID, API_MAX_RESULTS
from src.api.cache import CacheManager
from src.core.models import Task

class TaskManager:
    """Manages Google Tasks with local caching."""
    
    def __init__(self, auth_manager):
        """Initialize with an auth manager."""
        self.auth_service = auth_manager
        self.service = self.auth_service.get_tasks_service()
        self.cache = CacheManager()
        self.fetch_lock = threading.Lock()
        self.fetching_ranges = set()
        
    def fetch_tasks(self, tasklist_id='@default', max_results=API_MAX_RESULTS):
        """Fetch tasks from Google Tasks API."""
        self._ensure_valid_token()
        
        try:
            if tasklist_id == '@default':
                tasklists_result = self.service.tasklists().list().execute()
                if tasklists_result.get('items'):
                    tasklist_id = tasklists_result['items'][0]['id']

            tasks_result = self.service.tasks().list(
                tasklist=tasklist_id,
                maxResults=max_results,
                showCompleted=True,
                showHidden=False
            ).execute()
            
            tasks = tasks_result.get('items', [])

            processed_tasks = []
            for task in tasks:
                if not task.get('title'):
                    continue

                start_date = None
                if task.get('due'):

                    raw_due = task['due'].replace('Z', '+00:00')
                    due_datetime = datetime.datetime.fromisoformat(raw_due)
                    
                    is_midnight = due_datetime.hour == 0 and due_datetime.minute == 0 and due_datetime.second == 0
                    
                    if is_midnight:

                        morning_dt = datetime.datetime.combine(
                            due_datetime.date(), 
                            datetime.time(9, 0, 0, tzinfo=datetime.timezone.utc)
                        )
                        event_like = {
                            'id': task.get('id', generate_id()),
                            'summary': task.get('title', 'Untitled Task'),
                            'status': 'completed' if task.get('completed') else 'needs_action',
                            'start': {'dateTime': morning_dt.isoformat()},
                            'end': {'dateTime': (morning_dt + datetime.timedelta(hours=1)).isoformat()},
                            'source': 'tasks',
                            'isAllDay': True
                        }
                    else:
                        event_like = {
                            'id': task.get('id', generate_id()),
                            'summary': task.get('title', 'Untitled Task'),
                            'status': 'completed' if task.get('completed') else 'needs_action',
                            'start': {'dateTime': due_datetime.isoformat()},
                            'end': {'dateTime': (due_datetime + datetime.timedelta(hours=1)).isoformat()},
                            'source': 'tasks'
                        }
                else:
                    now = datetime.datetime.now(datetime.timezone.utc)
                    event_like = {
                        'id': task.get('id', generate_id()),
                        'summary': task.get('title', 'Untitled Task'),
                        'status': 'completed' if task.get('completed') else 'needs_action',
                        'start': {'dateTime': now.isoformat()},
                        'end': {'dateTime': (now + datetime.timedelta(hours=1)).isoformat()},
                        'source': 'tasks'
                    }
                processed_tasks.append(event_like)
                
            return processed_tasks, None
        except Exception as e:
            print(f"Error fetching tasks: {str(e)}")
            return [], None
    
    def _ensure_valid_token(self):
        """Ensure the token is valid before making API calls."""
        try:
            refreshed = self.auth_service.auto_refresh_token()
            if refreshed:
                self.service = self.auth_service.get_tasks_service()
        except Exception as e:
            print(f"Error ensuring valid token: {str(e)}")

    def add_task(self, tasklist_id, task):
        """Add a new task to Google Tasks."""
        self._ensure_valid_token()
        
        try:
            due_date = task.start_dt.date().isoformat()
            
            task_body = {
                'title': task.summary,
                'notes': '',
                'due': due_date
            }
            
            result = self.service.tasks().insert(
                tasklist=tasklist_id,
                body=task_body
            ).execute()
            
            morning_dt = datetime.datetime.combine(
                task.start_dt.date(), 
                datetime.time(9, 0, 0, tzinfo=datetime.timezone.utc)
            )
            
            event_like = {
                'id': result.get('id', generate_id()),
                'summary': result.get('title', 'Untitled Task'),
                'status': 'completed' if result.get('completed') else 'needs_action',
                'start': {'dateTime': morning_dt.isoformat()},
                'end': {'dateTime': (morning_dt + datetime.timedelta(hours=1)).isoformat()},
                'source': 'tasks',
                'isAllDay': True
            }
            
            self.cache.add_event(event_like)
            return event_like
        except Exception as e:
            print(f"Error adding task: {str(e)}")
            raise

    def update_task(self, tasklist_id, task_id, updated_task):
        """Update an existing task in Google Tasks."""
        self._ensure_valid_token()
        
        try:
            due_date = updated_task.start_dt.date().isoformat()
            
            task_body = {
                'title': updated_task.summary,
                'due': due_date
            }
            
            result = self.service.tasks().update(
                tasklist=tasklist_id,
                task=task_id,
                body=task_body
            ).execute()
            
            morning_dt = datetime.datetime.combine(
                updated_task.start_dt.date(), 
                datetime.time(9, 0, 0, tzinfo=datetime.timezone.utc)
            )
            
            event_like = {
                'id': result.get('id', generate_id()),
                'summary': result.get('title', 'Untitled Task'),
                'status': 'completed' if result.get('completed') else 'needs_action',
                'start': {'dateTime': morning_dt.isoformat()},
                'end': {'dateTime': (morning_dt + datetime.timedelta(hours=1)).isoformat()},
                'source': 'tasks',
                'isAllDay': True
            }
            
            self.cache.add_event(event_like)
            return event_like
        except Exception as e:
            print(f"Error updating task: {str(e)}")
            raise

    def delete_task(self, tasklist_id, task_id):
        """Delete a task from Google Tasks."""
        self._ensure_valid_token()
        
        try:
            self.service.tasks().delete(
                tasklist=tasklist_id,
                task=task_id
            ).execute()
            
            self.cache.delete_event(task_id)
            return {'success': True}
        except Exception as e:
            print(f"Error deleting task: {str(e)}")
            raise 