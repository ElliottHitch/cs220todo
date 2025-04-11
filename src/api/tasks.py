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
        
    def _create_event_like_structure(self, task_id, title, due_datetime=None, completed=False, is_all_day=False):
        """Helper method to create a standardized event-like structure from a task.
        
        Args:
            task_id: ID of the task
            title: Title/summary of the task
            due_datetime: Due datetime, or None if not specified
            completed: Whether the task is completed
            is_all_day: Whether it should be treated as an all-day event
            
        Returns:
            A dictionary with event-like structure
        """
        if due_datetime is None:
            due_datetime = datetime.datetime.now(datetime.timezone.utc)
            
        # If all-day, set to 9 AM
        if is_all_day:
            morning_dt = datetime.datetime.combine(
                due_datetime.date(), 
                datetime.time(9, 0, 0, tzinfo=datetime.timezone.utc)
            )
            start_time = morning_dt
        else:
            start_time = due_datetime
            
        end_time = start_time + datetime.timedelta(hours=1)
        
        return {
            'id': task_id or generate_id(),
            'summary': title or 'Untitled Task',
            'status': 'completed' if completed else 'needs_action',
            'start': {'dateTime': start_time.isoformat()},
            'end': {'dateTime': end_time.isoformat()},
            'source': 'tasks',
            'isAllDay': is_all_day
        }
        
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

                due_datetime = None
                is_all_day = False
                
                if task.get('due'):
                    raw_due = task['due'].replace('Z', '+00:00')
                    due_datetime = datetime.datetime.fromisoformat(raw_due)
                    is_all_day = due_datetime.hour == 0 and due_datetime.minute == 0 and due_datetime.second == 0
                
                event_like = self._create_event_like_structure(
                    task_id=task.get('id'),
                    title=task.get('title'),
                    due_datetime=due_datetime,
                    completed=task.get('completed'),
                    is_all_day=is_all_day
                )
                processed_tasks.append(event_like)
                
            return processed_tasks, None
        except Exception as e:
            print(f"Error fetching tasks: {str(e)}")
            return [], None
    
    def _ensure_valid_token(self):
        """Ensure the token is valid before making API calls."""
        try:
            self.auth_service.refresh_token_if_needed()
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
            
            event_like = self._create_event_like_structure(
                task_id=result.get('id'),
                title=result.get('title'),
                due_datetime=task.start_dt,
                completed=False,
                is_all_day=True
            )
            
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
            
            event_like = self._create_event_like_structure(
                task_id=result.get('id'),
                title=result.get('title'),
                due_datetime=updated_task.start_dt,
                completed=result.get('completed'),
                is_all_day=True
            )
            
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