from datetime import datetime, timezone, timedelta
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from src.core.models import Task

class ReminderManager(QObject):
    """Manages task reminders and notifications."""
    reminderReady = pyqtSignal(Task)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.reminders = []
        self.timer = QTimer()
        self.timer.timeout.connect(self.check_reminders)
        self.timer.start(10*60000)  # Check every 10 minutes
        
    def add_reminder(self, task):
        """Add a task to the reminder list."""
        self.reminders.append(task)
        
    def check_reminders(self):
        """Check if any reminders need to be shown."""
        now = datetime.now(timezone.utc)
        for task in self.reminders:
            reminder_time = task.start_dt - timedelta(minutes=task.reminder_minutes)
            if (task.status == 'Pending' and 
                reminder_time <= now < task.start_dt):
                self.reminderReady.emit(task) 