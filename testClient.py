import datetime
import sys
from src.api.auth import AuthManager
from src.api.tasks import TaskManager
from src.core.models import Task

def test_task_manager():
    """Test the TaskManager class functionality."""
    auth_manager = AuthManager()
    task_manager = TaskManager(auth_manager)

    # Fetch existing tasks
    print("Fetching existing tasks...")
    try:
        tasks, _ = task_manager.fetch_tasks()
        print(f"Found {len(tasks)} existing tasks")
        
        # Display the tasks
        if tasks:
            print("\nTask list:")
            for i, task in enumerate(tasks):
                print(f"{i+1}. {task.get('summary', 'Untitled')}")
        else:
            print("No tasks found.")
    except Exception as e:
        print(f"Error fetching tasks: {str(e)}")

if __name__ == "__main__":
    print("===== TASK MANAGER TEST =====\n")
    print(test_task_manager.__doc__)
    test_task_manager()