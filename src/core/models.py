class Task:
    """Represents a task/event with start and end times."""
    def __init__(self, summary, start_dt, end_dt, task_id=None, reminder_minutes=10, status='Pending', source='calendar', isAllDay=False):
        self.summary = summary
        self.start_dt = start_dt
        self.end_dt = end_dt
        self.task_id = task_id
        self.reminder_minutes = reminder_minutes
        self.status = status
        self.source = source
        self.isAllDay = isAllDay 