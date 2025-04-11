import sys
from PyQt6.QtWidgets import QApplication
from src.api.auth import AuthManager
from src.api.calendar import CalendarManager
from src.api.tasks import TaskManager
from src.ui.todo_app import TodoApp

def main():
    """Main entry point for the application."""
    # Initialize services
    auth_manager = AuthManager()
    calendar_manager = CalendarManager(auth_manager)
    task_manager = TaskManager(auth_manager)
    
    # Create and start the application
    app = QApplication(sys.argv)
    
    # Set style to fusion for better appearance
    app.setStyle("Fusion")
    
    # Create and show main window
    main_window = TodoApp(calendar_manager, task_manager)
    main_window.show()
    
    # Start the event loop
    sys.exit(app.exec())

if __name__ == "__main__":
    main() 