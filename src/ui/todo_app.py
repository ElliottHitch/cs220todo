import sys
import calendar
from calendar import monthrange
from datetime import datetime, timezone, timedelta
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QFrame, QScrollArea, QCalendarWidget, QComboBox, 
    QSpinBox, QStackedWidget, QGridLayout, QMessageBox
)
from PyQt6.QtCore import Qt, QSize, QTimer, QDate, pyqtSignal, QFileSystemWatcher
from PyQt6.QtGui import QColor, QFont
from src.core.config import (
    DEFAULT_WINDOW_SIZE, MAIN_STYLE, BACKGROUND_COLOR, HIGHLIGHT_COLOR, CARD_COLOR,
    NAV_BG_COLOR, TEXT_COLOR, FONT_HEADER, FONT_HEADER_SIZE, FONT_LABEL, 
    FONT_LABEL_SIZE, FONT_SMALL, FONT_SMALL_SIZE, FONT_DAY, 
    FONT_DAY_SIZE, FONT_DATE, FONT_DATE_SIZE, PADDING, 
    MAX_TASKS_PER_CELL
)
from src.core.utils import format_datetime, format_task_time, format_iso_for_api
from src.ui.task_dialog import TaskDialog
from src.ui.reminder_manager import ReminderManager
from src.workers.api_worker import APIWorker
from src.core.models import Task

import os
import importlib

class FileChangeMonitor:
    """Monitor file changes using PyQt6's QFileSystemWatcher for hot reloading."""
    
    def __init__(self, app, dirs_to_monitor=None):
        self.app = app
        self.dirs_to_monitor = dirs_to_monitor or ['src']
        self.watcher = QFileSystemWatcher()
        self.watched_files = []
        self.file_timestamps = {}
        self.check_timer = QTimer()
        self.check_timer.setInterval(1000)
        self.check_timer.timeout.connect(self.check_for_changes)
        self.setup_watcher()
        
    def setup_watcher(self):
        """Set up the file watcher to monitor Python files."""
        for dir_path in self.dirs_to_monitor:
            if os.path.exists(dir_path):
                self.watcher.addPath(dir_path)

                self._add_directory_files(dir_path)
                
    def _add_directory_files(self, directory):
        """Add all Python files in the directory and its subdirectories to the watcher."""
        for root, dirs, files in os.walk(directory):
            for d in dirs:
                dir_path = os.path.join(root, d)
                try:
                    self.watcher.addPath(dir_path)
                except Exception:
                    pass
                
            for file in files:
                if file.endswith('.py') and '__pycache__' not in root:
                    file_path = os.path.join(root, file)
                    try:
                        self.watcher.addPath(file_path)
                        self.watched_files.append(file_path)
                        self.file_timestamps[file_path] = os.path.getmtime(file_path)
                    except Exception:
                        pass 
        
    def start(self):
        """Start monitoring for file changes."""
        self.watcher.fileChanged.connect(self.on_file_changed)
        self.watcher.directoryChanged.connect(self.on_directory_changed)
        self.check_timer.start()
        print("Hot reload monitoring started")
        
    def stop(self):
        """Stop monitoring for file changes."""

        try:
            self.watcher.fileChanged.disconnect(self.on_file_changed)
            self.watcher.directoryChanged.disconnect(self.on_directory_changed)
        except Exception:
            pass 
        self.check_timer.stop()
        print("Hot reload monitoring stopped")
        
    def check_for_changes(self):
        """Periodically check for file changes that might have been missed by the watcher."""
        for file_path in list(self.watched_files):
            if not os.path.exists(file_path):
                self.watched_files.remove(file_path)
                self.file_timestamps.pop(file_path, None)
                continue
                
            try:
                current_mtime = os.path.getmtime(file_path)
                if file_path in self.file_timestamps:
                    if current_mtime > self.file_timestamps[file_path]:
                        print(f"Timer detected change in: {file_path}")
                        self.file_timestamps[file_path] = current_mtime
                        self.reload_module(file_path)
                else:
                    self.file_timestamps[file_path] = current_mtime
            except Exception:
                pass 
                
        for dir_path in self.dirs_to_monitor:
            if os.path.exists(dir_path):
                self._add_directory_files(dir_path)
        
    def on_file_changed(self, path):
        """Handle file change events."""
        if path.endswith('.py') and '__pycache__' not in path:
            print(f"Watcher detected change in: {path}")
            try:
                if os.path.exists(path):
                    self.file_timestamps[path] = os.path.getmtime(path)
                    self.watcher.addPath(path)
            except Exception:
                pass
            self.reload_module(path)
            
    def on_directory_changed(self, path):
        """Handle directory change events."""
        self._add_directory_files(path)
        
    def reload_module(self, file_path):
        """Reload the Python module."""
        try:
            rel_path = os.path.relpath(file_path)
            mod_path = rel_path.replace('\\', '/').replace('/', '.')
            if mod_path.endswith('.py'):
                mod_path = mod_path[:-3]
                
            module_parts = mod_path.split('.')
            if 'src' in module_parts:
                src_index = module_parts.index('src')
                module_path = '.'.join(module_parts[src_index:])
                
                try:
                    module = importlib.import_module(module_path)
                    importlib.reload(module)
                    print(f"Reloaded module: {module_path}")
                    
                    QTimer.singleShot(100, self.app.refresh_after_hot_reload)
                except (ImportError, AttributeError) as e:
                    print(f"Error reloading module {module_path}: {e}")
        except Exception as e:
            print(f"Error during hot reload: {e}")

class TodoApp(QMainWindow):
    """Main application window."""
    def __init__(self, calendar_manager, task_manager=None):
        super().__init__()
        self.calendar_manager = calendar_manager
        self.task_manager = task_manager
        
        self.setWindowTitle("To-Do List")
        self.resize(*DEFAULT_WINDOW_SIZE)
        
        self.setStyleSheet(MAIN_STYLE)
        
        self.current_view = "daily"
        today = datetime.now().date()
        self.displayed_year, self.displayed_month = today.year, today.month
        
        self.loading = False
        
        self.initial_load = True
        
        self.init_ui()
        
        self.worker = APIWorker(self)
        self.worker.taskCompleted.connect(self.on_task_completed)
        self.worker.taskError.connect(self.on_task_error)
        self.worker.loadingChanged.connect(self.on_loading_changed)
        
        self.reminder_manager = ReminderManager(self)
        self.reminder_manager.reminderReady.connect(self.show_reminder)
        
        try:
            self.file_monitor = FileChangeMonitor(self)
            self.file_monitor.start()
            print("Hot reloading enabled")
        except Exception as e:
            print(f"Warning: Could not enable hot reloading: {e}")
        
        self.refresh_events()
        
    def init_ui(self):
        """Initialize the main UI components."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.init_navbar(main_layout)
        
        self.init_main_content(main_layout)
        
    def init_navbar(self, parent_layout):
        """Initialize the navigation bar."""
        navbar = QFrame()
        navbar.setStyleSheet(f"background-color: {NAV_BG_COLOR};")
        navbar.setMinimumHeight(60)
        
        nav_layout = QHBoxLayout(navbar)
        nav_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        
        title_label = QLabel("To-Do List ")
        title_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE, QFont.Weight.Bold))
        nav_layout.addWidget(title_label)
        
        search_frame = QFrame()
        search_layout = QHBoxLayout(search_frame)
        search_layout.setContentsMargins(0, 0, 0, 0)
        
        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("Search tasks...")
        self.search_entry.textChanged.connect(self.filter_content)
        search_layout.addWidget(self.search_entry)
        
        nav_layout.addWidget(search_frame, 1)
        
        button_container = QFrame()
        button_layout = QHBoxLayout(button_container)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(PADDING)
        
        today_button = QPushButton("Today")
        today_button.clicked.connect(self.scroll_to_today)
        today_button.setFixedWidth(100)
        today_button.setStyleSheet("""
            QPushButton:hover {
                background-color: #1F6AA5;
            }
        """)
        button_layout.addWidget(today_button)
        
        self.view_toggle_button = QPushButton("Monthly View")
        self.view_toggle_button.clicked.connect(self.toggle_view)
        self.view_toggle_button.setFixedWidth(120)
        self.view_toggle_button.setStyleSheet("""
            QPushButton:hover {
                background-color: #1F6AA5;
            }
        """)
        button_layout.addWidget(self.view_toggle_button)
        
        self.new_task_btn = QPushButton("+ Add Task")
        self.new_task_btn.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        self.new_task_btn.clicked.connect(self.show_add_task_dialog)
        self.new_task_btn.setStyleSheet("""
            QPushButton:hover {
                background-color: #1F6AA5;
            }
        """)
        button_layout.addWidget(self.new_task_btn)
        
        nav_layout.addWidget(button_container)
        
        parent_layout.addWidget(navbar)
        
    def init_main_content(self, parent_layout):
        """Initialize the main content area with stacked views."""
        self.views_stack = QStackedWidget()
        
        self.daily_view = QScrollArea()
        self.daily_view.setWidgetResizable(True)
        self.daily_content = QWidget()
        self.daily_layout = QVBoxLayout(self.daily_content)
        self.daily_layout.setSpacing(PADDING//2)
        self.daily_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        self.daily_view.setWidget(self.daily_content)
        
        self.monthly_view = QWidget()
        self.monthly_layout = QVBoxLayout(self.monthly_view)
        self.monthly_layout.setSpacing(0)
        self.monthly_layout.setContentsMargins(0, 0, 0, 0)
        
        self.views_stack.addWidget(self.daily_view)
        self.views_stack.addWidget(self.monthly_view)
        
        parent_layout.addWidget(self.views_stack, 1)
    
    def on_task_completed(self, result, task_type):
        """Handle completed tasks from worker thread."""
        if task_type == "fetch_events":
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            if next_token:
                self._fetch_next_page(next_token)
            else:
                self._update_current_view()
                
        elif task_type == "fetch_tasks":
            tasks, _ = result
            if tasks:
                self._process_loaded_events(tasks)
                self._update_current_view()
                
        elif task_type == "background_fetch":
            events, next_token = result
            if events:
                self._process_loaded_events(events)
            
            if next_token:
                self._fetch_next_page(next_token)
            else:
                self._update_current_view()
                
        elif task_type == "fetch_month":
            if self.current_view == "monthly":
                search_term = self.search_entry.text() if hasattr(self, 'search_entry') else ""
                tasks_by_date = self.calendar_manager.cache.get_tasks_for_month(self.displayed_year, self.displayed_month)
                
                self._update_calendar_cells(tasks_by_date, search_term)
            else:
                self._update_current_view()
            
        elif task_type == "fetch_holidays":
            self._update_holidays(result)
            
        elif task_type == "create_task" or task_type == "update_task":
            action = "created" if task_type == "create_task" else "updated"
            self.show_alert(f"Task {action}: {result['summary']}", duration=3000)
            
            self._update_current_view()
            
        elif task_type == "delete_task":
            self.show_alert(f"Task deleted", duration=3000)
            
            self._update_current_view()
        
    def on_task_error(self, error, task_type):
        """Handle errors from worker thread."""
        if task_type == "fetch_events":
            self.show_alert(f"Error fetching events: {str(error)}", duration=4000)
            self._update_current_view()
            
        elif task_type == "fetch_tasks":
            self.show_alert(f"Error fetching tasks: {str(error)}", duration=4000)
            self._update_current_view()
            
        elif task_type in ["create_task", "update_task"]:
            action = "create" if task_type == "create_task" else "update"
            self.show_alert(f"Failed to {action} task: {str(error)}", duration=4000)
            
        elif task_type == "delete_task":
            self.show_alert(f"Failed to delete task: {str(error)}", duration=4000)
            
        else:
            self.show_alert(f"Error in {task_type}: {str(error)}", duration=4000)
            
    def on_loading_changed(self, is_loading):
        """Handle loading state changes."""
        self.loading = is_loading
        if is_loading:
            print("Loading started")
        else:
            print("Loading finished")
            
    def show_alert(self, message, duration=3000):
        """Log alerts to console."""
        print(f"INFO: {message}")
        
    def show_reminder(self, task):
        """Show a reminder notification for a task."""
        time_str = format_task_time(task.start_dt, task.end_dt)
        self.show_alert(f"Reminder: {task.summary} at {time_str}", duration=5000)
        
    def refresh_events(self):
        """Refresh events from Google Calendar."""
        now = datetime.now()
        start_date = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
        
        self.worker.add_task(
            "fetch_events",
            self.calendar_manager.fetch_events,
            calendar_id='primary',
            max_results=50,
            start_date=start_date
        )
        
        if self.task_manager:
            self.worker.add_task(
                "fetch_tasks",
                self.task_manager.fetch_tasks,
                tasklist_id='@default',
                max_results=50
            )

    def _fetch_next_page(self, page_token):
        """Fetch the next page of events."""
        self.worker.add_task(
            "background_fetch",
            self.calendar_manager.fetch_events,
            calendar_id='primary',
            max_results=50,
            page_token=page_token
        )
        
    def _update_current_view(self):
        """Update the current view after data has been loaded."""
        if self.current_view == "daily":
            self.build_daily_view(self.search_entry.text() if hasattr(self, 'search_entry') else "")
        elif self.current_view == "monthly":
            self._update_monthly_view_data(self.search_entry.text() if hasattr(self, 'search_entry') else "")
        
    def _process_loaded_events(self, events):
        """Process loaded events and update the cache."""
        added_count = 0
        
        for event in events:
            event_id = event.get('id')
            
            if event_id and self.calendar_manager.cache.has_event_id(event_id):
                continue
                
            self.calendar_manager.cache.add_event(event)
            added_count += 1
            
            task = self.calendar_manager.cache._convert_event_to_task(event)
            if task:
                self.reminder_manager.add_reminder(task)
        
        if added_count > 0:
            self._update_current_view()
            
    def get_filtered_tasks_by_date(self, search_term=""):
        """Get tasks filtered by search term, organized by date."""
        tasks_by_date = self._get_tasks_by_date_dict()

        if not search_term:
            return tasks_by_date
        
        search_term = search_term.lower()
        return {date: [task for task in tasks if search_term in task.summary.lower()] 
                for date, tasks in tasks_by_date.items() 
                if any(search_term in task.summary.lower() for task in tasks)}
    
    def _get_tasks_by_date_dict(self):
        """Get tasks organized by date from the cache."""
        return self.calendar_manager.cache.tasks_by_date.copy()
            
    def build_daily_view(self, search_term=""):
        """Build the daily view with all tasks organized by date."""
        self.clear_widget(self.daily_content)
        
        tasks_by_date = self.get_filtered_tasks_by_date(search_term)
        
        sorted_dates = sorted(tasks_by_date.keys())
        
        if not sorted_dates:
            no_tasks_label = QLabel("No tasks found for this period")
            no_tasks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            no_tasks_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE))
            self.daily_layout.addWidget(no_tasks_label)
            self.daily_layout.addStretch(1)
            return
            
        tasks_by_month = {}
        for day, tasks in tasks_by_date.items():
            month_key = (day.year, day.month)
            if month_key not in tasks_by_month:
                tasks_by_month[month_key] = []
            tasks_by_month[month_key].extend(tasks)
            
        self.month_containers = {}
        
        current_month = None
        current_year = None
        
        for day in sorted_dates:
            if current_year != day.year or current_month != day.month:
                month_key = (day.year, day.month)
                task_count = len(tasks_by_month.get(month_key, []))
                
                if current_month is not None:
                    self.daily_layout.addSpacing(20)
                
                self.create_month_separator(day, task_count)
                
                current_month = day.month
                current_year = day.year
                
            month_key = (day.year, day.month)
            if month_key in self.month_containers:
                self.create_day_content(day, tasks_by_date[day], self.month_containers[month_key]['container'])
                
    def create_month_separator(self, day, task_count):
        """Create a month/year separator with a simple text header."""
        month_key = (day.year, day.month)
        
        separator_frame = QFrame()
        separator_frame.setStyleSheet("background-color: #262640;")
        separator_frame.setMinimumHeight(40)
        self.daily_layout.addWidget(separator_frame)
        
        separator_layout = QVBoxLayout(separator_frame)
        separator_layout.setContentsMargins(PADDING, PADDING//2, PADDING, PADDING//2)
        separator_layout.setSpacing(0)
        
        header_layout = QHBoxLayout()
        
        month_year_text = format_datetime(day, 'month_year')
        task_count_text = f"({task_count} task{'s' if task_count != 1 else ''})"
        
        month_label = QLabel(f"📅  {month_year_text}")
        month_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE, QFont.Weight.Bold))
        header_layout.addWidget(month_label, 1)
        
        count_label = QLabel(task_count_text)
        count_label.setStyleSheet("color: #AAAAFF;")
        count_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        header_layout.addWidget(count_label)
        
        separator_layout.addLayout(header_layout)
        
        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet("background-color: #3A3A5C;")
        divider.setFixedHeight(2)
        separator_layout.addWidget(divider)
        
        month_container = QWidget()
        month_layout = QVBoxLayout(month_container)
        month_layout.setContentsMargins(0, 0, 0, 0)
        month_layout.setSpacing(PADDING//2)
        
        self.daily_layout.addWidget(month_container)
        
        self.month_containers[month_key] = {
            'frame': separator_frame,
            'header_label': month_label,
            'container': month_container,
            'expanded': True
        }
            
    def create_day_content(self, day, tasks, parent_container):
        """Create the content for a single day."""
        day_frame = QFrame()
        day_frame.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")
        
        day_layout = QHBoxLayout(day_frame)
        day_layout.setContentsMargins(PADDING, PADDING//2, PADDING, PADDING//2)
        
        date_strip = self.create_date_strip(day)
        day_layout.addWidget(date_strip)
        
        tasks_container = QWidget()
        tasks_layout = QVBoxLayout(tasks_container)
        tasks_layout.setContentsMargins(PADDING, 0, 0, 0)
        tasks_layout.setSpacing(PADDING//2)
        
        def sort_key(task):
            if hasattr(task, 'source') and task.source == 'tasks':
                return (2, task.start_dt)  # Google Tasks last
            elif hasattr(task, 'isAllDay') and task.isAllDay:
                return (1, task.start_dt)  # All-day events second
            else:
                return (0, task.start_dt)  # Regular events first
                
        sorted_tasks = sorted(tasks, key=sort_key)
        
        for task in sorted_tasks:
            task_card = self.create_task_card(task, False)
            tasks_layout.addWidget(task_card)
            
        day_layout.addWidget(tasks_container, 1)
        
        parent_layout = parent_container.layout()
        parent_layout.addWidget(day_frame)
        
    def create_date_strip(self, day):
        """Create the date strip showing weekday and date."""
        date_strip = QWidget()
        date_strip.setMinimumWidth(50)
        
        strip_layout = QVBoxLayout(date_strip)
        strip_layout.setContentsMargins(0, 0, 0, 0)
        strip_layout.setSpacing(0)
        
        weekday_label = QLabel(format_datetime(day, 'weekday'))
        weekday_label.setFont(QFont(FONT_DAY, FONT_DAY_SIZE, QFont.Weight.Bold))
        weekday_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        strip_layout.addWidget(weekday_label)
        
        day_label = QLabel(format_datetime(day, 'day'))
        day_label.setFont(QFont(FONT_DATE, FONT_DATE_SIZE, QFont.Weight.Bold))
        day_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        strip_layout.addWidget(day_label)
        
        strip_layout.addStretch(1)
        
        return date_strip
        
    def create_task_card(self, task, is_monthly_view=False):
        """Create a card for displaying a task."""
        task_card = QFrame()
        
        if is_monthly_view:
            task_card.setStyleSheet("background-color: transparent; border: none;")
            task_card.setFixedHeight(18)
            task_card.setMaximumWidth(170)
        else:
            task_card.setStyleSheet(f"background-color: {CARD_COLOR}; border-radius: 6px;")
        
        task_card.mousePressEvent = lambda e, t=task: self.open_task_dialog(t)
        
        card_layout = QHBoxLayout(task_card) if is_monthly_view else QVBoxLayout(task_card)
        
        if is_monthly_view:
            card_layout.setContentsMargins(0, 0, 0, 0)
            card_layout.setSpacing(2)
        else:
            card_layout.setContentsMargins(10, 10, 10, 10)
            card_layout.setSpacing(4)
        
        is_all_day = hasattr(task, 'isAllDay') and task.isAllDay
        is_google_task = hasattr(task, 'source') and task.source == 'tasks'
        
        if is_google_task:
            time_str = "Task"
        elif is_all_day:
            time_str = "All day"
        else:
            time_str = format_task_time(task.start_dt, task.end_dt)
        
        summary = task.summary
        if is_monthly_view and len(summary) > 15:
            display_summary = f"{summary[:15]}..."
        else:
            display_summary = summary
            
        if is_monthly_view:
            local_start = task.start_dt.astimezone()
            bullet_color = "#50A0FF"
            
            if is_google_task:
                bullet_color = "#FFAA50"
            elif is_all_day:
                bullet_color = "#FFCC50"
            elif local_start.hour < 12:
                bullet_color = "#60C060"
            elif local_start.hour >= 17:
                bullet_color = "#FF8050"
                
            bullet_label = QLabel("•")
            bullet_label.setStyleSheet(f"color: {bullet_color}; font-weight: bold; font-size: 14px; background: transparent; border: none;")
            bullet_label.setFixedWidth(15)
            card_layout.addWidget(bullet_label)
            
            time_text = "Task" if is_google_task else "All day" if is_all_day else format_datetime(local_start, 'time', include_minutes=False)
            time_label = QLabel(time_text)
            time_label.setStyleSheet(f"color: {bullet_color}; background: transparent; border: none;")
            time_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 2))
            time_label.setFixedWidth(45)
            card_layout.addWidget(time_label)
            
            task_label = QLabel(display_summary)
            task_label.setStyleSheet("color: white; background: transparent; border: none;")
            task_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 1))
            task_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            task_label.setWordWrap(False)
            card_layout.addWidget(task_label, 1)
        else:
            summary_label = QLabel(display_summary)
            summary_label.setStyleSheet("color: white;")
            summary_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
            summary_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(summary_label)
            
            time_label = QLabel(time_str)
            time_label.setStyleSheet("color: white;")
            time_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE))
            time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            card_layout.addWidget(time_label)
            
        return task_card
        
    def clear_widget(self, widget):
        """Clear all child widgets from a container."""
        if widget is None:
            return
            
        layout = widget.layout()
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
                elif item.layout():
                    self.clear_widget(item.widget())
    
    def filter_content(self):
        """Filter view content based on search term."""
        search_term = self.search_entry.text()
        if self.current_view == "daily":
            self.build_daily_view(search_term)
        elif self.current_view == "monthly":
            self._update_monthly_view_data(search_term)
            
    def toggle_view(self):
        """Toggle between daily and monthly views."""
        if self.current_view == "daily":
            self.current_view = "monthly"
            self.view_toggle_button.setText("Daily View")
            self.views_stack.setCurrentIndex(1)
            if not self.monthly_view.layout().count():
                self._create_monthly_view_structure()
            self._update_monthly_view_data(self.search_entry.text())
        else:
            self.current_view = "daily"
            self.view_toggle_button.setText("Monthly View")
            self.views_stack.setCurrentIndex(0)
            self.build_daily_view(self.search_entry.text())
        QTimer.singleShot(100, self.scroll_to_today)
        
    def show_add_task_dialog(self):
        """Show dialog to add a new task with option to select destination service."""
        from src.ui.task_dialog import TaskDialog
        dialog = TaskDialog(self, on_confirm=self.on_task_dialog_confirm)
        dialog.exec()
        
    def open_task_dialog(self, task=None):
        """Open the task dialog for editing an existing task."""
        from src.ui.task_dialog import TaskDialog
        dialog = TaskDialog(self, on_confirm=self.on_task_dialog_confirm, task=task)
        dialog.exec()
        
    def open_task_dialog_for_date(self, date):
        """Open the task dialog with the selected date pre-filled."""
        from src.ui.task_dialog import TaskDialog
        # Create a new task with the selected date
        start_time = datetime.combine(date, datetime.min.time())
        end_time = start_time + timedelta(hours=1)
        task = Task(
            summary="",
            start_dt=start_time,
            end_dt=end_time
        )
        dialog = TaskDialog(self, on_confirm=self.on_task_dialog_confirm, task=task)
        dialog.exec()
        
    def on_task_dialog_confirm(self, task):
        """Handle confirmed task from dialog."""
        if (task.task_id and hasattr(task, 'source') and task.source == 'tasks') or \
           (not task.task_id and hasattr(task, 'source') and task.source == 'tasks'):
            if self.task_manager:
                if task.task_id:
                    self.worker.add_task(
                        "update_task",
                        self.task_manager.update_task,
                        tasklist_id='@default',
                        task_id=task.task_id,
                        updated_task=task
                    )
                else:
                    self.worker.add_task(
                        "create_task",
                        self.task_manager.add_task,
                        tasklist_id='@default',
                        task=task
                    )
            else:
                self.show_alert("Cannot manage task: Task manager not available", duration=3000)
        else:
            event = {
                'summary': task.summary,
                'start': {'dateTime': format_iso_for_api(task.start_dt), 'timeZone': 'UTC'},
                'end': {'dateTime': format_iso_for_api(task.end_dt), 'timeZone': 'UTC'}
            }
            
            if task.task_id:
                self.worker.add_task(
                    "update_task",
                    self.calendar_manager.update_event,
                    calendar_id='primary',
                    event_id=task.task_id,
                    updated_event=event
                )
            else:
                self.worker.add_task(
                    "create_task",
                    self.calendar_manager.add_event,
                    calendar_id='primary',
                    event=event
                )
                
    def delete_task(self, task):
        """Delete a task from the calendar or tasks API."""
        if not task or not task.task_id:
            self.show_alert("Cannot delete task: no task ID", duration=3000)
            return
        
        if hasattr(task, 'source') and task.source == 'tasks':
            if self.task_manager:
                self.worker.add_task(
                    "delete_task",
                    self.task_manager.delete_task,
                    tasklist_id='@default',
                    task_id=task.task_id
                )
            else:
                self.show_alert("Cannot delete task: Task manager not available", duration=3000)
        else:
            self.worker.add_task(
                "delete_task",
                self.calendar_manager.delete_event,
                calendar_id='primary',
                event_id=task.task_id
            )

    def _create_monthly_view_structure(self):
        """Create the static widgets for the monthly view."""
        self.clear_widget(self.monthly_view)
        self._create_month_header()
        self._create_calendar_grid()
        
    def _create_month_header(self):
        """Create the month navigation header."""
        header_frame = QFrame()
        header_frame.setStyleSheet(f"background-color: {NAV_BG_COLOR};")
        header_frame.setMinimumHeight(50)
        
        header_layout = QHBoxLayout(header_frame)
        header_layout.setContentsMargins(PADDING, PADDING, PADDING, PADDING)
        
        prev_button = QPushButton("<")
        prev_button.setFixedWidth(40)
        prev_button.clicked.connect(self.prev_month)
        prev_button.setStyleSheet("""
            QPushButton:hover {
                background-color: #1F6AA5;
            }
        """)
        header_layout.addWidget(prev_button)
        
        month_date = datetime(self.displayed_year, self.displayed_month, 1)
        self.month_year_label = QLabel(format_datetime(month_date, 'month_year'))
        self.month_year_label.setFont(QFont(FONT_HEADER, FONT_HEADER_SIZE, QFont.Weight.Bold))
        self.month_year_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(self.month_year_label, 1)
        
        next_button = QPushButton(">")
        next_button.setFixedWidth(40)
        next_button.clicked.connect(self.next_month)
        next_button.setStyleSheet("""
            QPushButton:hover {
                background-color: #1F6AA5;
            }
        """)
        header_layout.addWidget(next_button)
        
        self.monthly_layout.addWidget(header_frame)
        
    def _create_calendar_grid(self):
        """Create the calendar grid for monthly view."""
        grid_container = QFrame()
        grid_container.setStyleSheet(f"background-color: {BACKGROUND_COLOR};")
        
        grid_layout = QGridLayout(grid_container)
        grid_layout.setSpacing(1)
        
        days_of_week = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
        for col, day_name in enumerate(days_of_week):
            day_header = QFrame()
            day_header.setStyleSheet("background-color: #1A1A2E;")
            day_header.setMinimumHeight(25)
            day_header.setMaximumHeight(25)
            
            header_layout = QVBoxLayout(day_header)
            header_layout.setContentsMargins(5, 2, 5, 2)
            
            label = QLabel(day_name)
            label.setFont(QFont(FONT_DAY, FONT_DAY_SIZE, QFont.Weight.Bold))
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            header_layout.addWidget(label)
            
            grid_layout.addWidget(day_header, 0, col)
        
        self.calendar_cells = {}
        
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        num_weeks = len(month_calendar)
        
        for row_idx in range(num_weeks):
            for col_idx in range(7):
                cell = self._create_calendar_cell(row_idx, col_idx)
                grid_layout.addWidget(cell, row_idx + 1, col_idx)
                
        for col in range(7):
            grid_layout.setColumnStretch(col, 1)
        for row in range(num_weeks):
            grid_layout.setRowStretch(row + 1, 1)
            
        self.monthly_layout.addWidget(grid_container, 1)
        
    def _create_calendar_cell(self, row, col):
        """Create a single calendar cell."""
        cell = QFrame()
        cell.setStyleSheet(f"background-color: {BACKGROUND_COLOR}; border: 1px solid #333344;")
        cell.setMinimumSize(180, 120)
        
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(2, 2, 2, 2)
        cell_layout.setSpacing(1)
        
        day_label = QLabel("")
        day_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        day_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        day_label.setFixedHeight(35)
        cell_layout.addWidget(day_label)
        
        tasks_container = QFrame()
        tasks_container.setStyleSheet("background: transparent; border: none;")
        tasks_layout = QVBoxLayout(tasks_container)
        tasks_layout.setContentsMargins(2, 0, 2, 0)
        tasks_layout.setSpacing(1)
        cell_layout.addWidget(tasks_container, 1) 
        
        self.calendar_cells[(row, col)] = {
            'frame': cell,
            'day_label': day_label,
            'tasks_container': tasks_container,
            'current_state': {
                'date': None,
                'tasks': [],
                'holiday': None,
                'is_current_month': False,
                'is_today': False
            }
        }
        
        cell.mousePressEvent = lambda e, r=row, c=col: self._on_cell_clicked(r, c)
        return cell
        
    def _on_cell_clicked(self, row, col):
        """Handle calendar cell click to create a new task."""
        cell_data = self.calendar_cells.get((row, col))
        if cell_data and cell_data['current_state']['date']:
            self.open_task_dialog_for_date(cell_data['current_state']['date'])
            
    def _update_monthly_view_data(self, search_term="", force_refresh=False):
        """Update the monthly view with current month's data."""
        if hasattr(self, 'month_year_label'):
            month_date = datetime(self.displayed_year, self.displayed_month, 1)
            self.month_year_label.setText(format_datetime(month_date, 'month_year'))
            
        month_calendar = calendar.monthcalendar(self.displayed_year, self.displayed_month)
        
        self._setup_calendar_cell_dates(month_calendar)
        
        start_date, end_date = self._get_month_date_range(self.displayed_year, self.displayed_month)
        
        tasks_by_date = self.calendar_manager.cache.get_tasks_for_month(self.displayed_year, self.displayed_month)
        
        if tasks_by_date and not force_refresh:
            self._update_calendar_cells(tasks_by_date, search_term)
        else:
            if force_refresh:
                self.calendar_manager.clear_cache_for_month(self.displayed_year, self.displayed_month)
            
            self.worker.add_task(
                "fetch_month",
                self.calendar_manager.fetch_events_for_range,
                start_date=start_date,
                end_date=end_date
            )
            
            if self.task_manager:
                self.worker.add_task(
                    "fetch_tasks",
                    self.task_manager.fetch_tasks
                )
        
        holidays = self.calendar_manager.cache.get_holidays_for_month(self.displayed_year, self.displayed_month)
        if not holidays or force_refresh:
            self.worker.add_task(
                "fetch_holidays",
                self.calendar_manager.fetch_holidays,
                year=self.displayed_year,
                month=self.displayed_month
            )
         
    def _setup_calendar_cell_dates(self, month_calendar):
        """Set up date numbers in calendar cells."""
        today = datetime.now().date()
        
        row_idx = 0
        for week in month_calendar:
            for col_idx, day_num in enumerate(week):
                cell_data = self.calendar_cells.get((row_idx, col_idx))
                if not cell_data:
                    continue
                    
                if day_num == 0:
                    cell_data['frame'].setStyleSheet("background-color: #1E1E2F; border: 1px solid #333344;")
                    cell_data['day_label'].setText("")
                    cell_data['current_state']['is_current_month'] = False
                    cell_data['current_state']['date'] = None
                    continue
                    
                current_date = datetime(self.displayed_year, self.displayed_month, day_num).date()
                
                date_changed = cell_data['current_state']['date'] != current_date
                today_changed = (current_date == today) != cell_data['current_state']['is_today']
                
                cell_data['current_state']['date'] = current_date
                cell_data['current_state']['is_current_month'] = True
                cell_data['current_state']['is_today'] = (current_date == today)
                
                if date_changed or today_changed:
                    self.clear_widget(cell_data['tasks_container'])
                    cell_data['current_state']['tasks'] = []
                    cell_data['current_state']['holiday'] = None
                
                self._configure_cell_appearance(cell_data, current_date, day_num, today)
                
            row_idx += 1
            
    def _configure_cell_appearance(self, cell_data, current_date, day_num, today):
        """Configure the appearance of a calendar cell."""
        if current_date == today:
            cell_data['frame'].setStyleSheet(f"background-color: #2D2D4D; border: 2px solid {HIGHLIGHT_COLOR};")
            cell_data['day_label'].setStyleSheet("color: white; font-weight: bold;")
        else:
            cell_data['frame'].setStyleSheet(f"background-color: {BACKGROUND_COLOR}; border: 1px solid #333344;")
            cell_data['day_label'].setStyleSheet("")
            
        cell_data['day_label'].setText(str(day_num))
        
    def _update_holidays(self, holidays):
        """Update cells with holiday information."""
        if not holidays:
            return
            
        for date, holiday_name in holidays.items():
            for cell_key, cell_data in self.calendar_cells.items():
                if cell_data['current_state']['date'] == date:
                    if cell_data['current_state']['holiday'] != holiday_name:
                        cell_data['current_state']['holiday'] = holiday_name
                        self._add_holiday_to_cell(cell_data['tasks_container'], holiday_name)
                        
    def _add_holiday_to_cell(self, container, holiday_name):
        """Add a holiday indicator to a cell."""
        holiday_frame = QFrame()
        holiday_frame.setStyleSheet("background-color: transparent; border: none;")
        holiday_frame.setMaximumHeight(18)
        
        holiday_layout = QHBoxLayout(holiday_frame)
        holiday_layout.setContentsMargins(0, 0, 0, 0) 
        holiday_layout.setSpacing(1)
        
        if len(holiday_name) > 20:
            holiday_name = holiday_name[:17] + "..."
            
        holiday_label = QLabel(f"🎉 {holiday_name}")
        holiday_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 1))
        holiday_label.setStyleSheet("color: #CCCCFF; background: transparent; border: none;")
        holiday_layout.addWidget(holiday_label)
        
        container_layout = container.layout()
        
        for i in range(container_layout.count()):
            widget = container_layout.itemAt(i).widget()
            if widget and isinstance(widget, QFrame) and widget.layout() and widget.layout().count() > 0:
                label = widget.layout().itemAt(0).widget()
                if isinstance(label, QLabel) and label.text().startswith("🎉"):
                    widget.deleteLater()
                    break
                
        container_layout.insertWidget(0, holiday_frame)
        
    def _update_calendar_cells(self, tasks_by_date, search_term=""):
        """Update calendar cells with task data."""
        for cell_key, cell_data in self.calendar_cells.items():
            date = cell_data['current_state']['date']
            if not date or not cell_data['current_state']['is_current_month']:
                continue
                
            tasks = tasks_by_date.get(date, [])
            if search_term:
                tasks = [t for t in tasks if search_term.lower() in t.summary.lower()]

            container = cell_data['tasks_container']
            layout = container.layout()
            
            holiday_frames = []
            for i in range(layout.count()):
                widget = layout.itemAt(i).widget()

                if widget and isinstance(widget, QFrame) and widget.layout() and widget.layout().count() > 0:
                    first_child = widget.layout().itemAt(0).widget()
                    if isinstance(first_child, QLabel) and first_child.text().startswith("🎉"):
                        holiday_frames.append(widget)
                    else:
                        widget.deleteLater()
                else:
                    if widget:
                        widget.deleteLater()
                    
            while layout.count():
                item = layout.takeAt(0)
                if item.widget() not in holiday_frames:
                    if item.widget():
                        item.widget().deleteLater()
                        

            for frame in holiday_frames:
                layout.addWidget(frame)
                
            if tasks:
                def sort_key(task):
                    if hasattr(task, 'source') and task.source == 'tasks':
                        return (2, task.start_dt)
                    elif hasattr(task, 'isAllDay') and task.isAllDay:
                        return (1, task.start_dt)
                    else:
                        return (0, task.start_dt)
                
                sorted_tasks = sorted(tasks, key=sort_key)
            
                layout.setSpacing(1)
                
                for i, task in enumerate(sorted_tasks[:MAX_TASKS_PER_CELL]):
                    task_card = self.create_task_card(task, True)
                    layout.addWidget(task_card)
                    
                if len(tasks) > MAX_TASKS_PER_CELL:
                    more_label = QLabel(f"+ {len(tasks) - MAX_TASKS_PER_CELL} more")
                    more_label.setStyleSheet("color: #CCCCFF; font-size: 9px; background: transparent; border: none;")
                    more_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE - 2))
                    more_label.setAlignment(Qt.AlignmentFlag.AlignRight)
                    more_label.setFixedHeight(15)
                    layout.addWidget(more_label)
            elif not holiday_frames:
                no_tasks_label = QLabel("No tasks")
                no_tasks_label.setStyleSheet("color: #888888; font-style: italic; background: transparent; border: none;")
                no_tasks_label.setFont(QFont(FONT_SMALL, FONT_SMALL_SIZE))
                no_tasks_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(no_tasks_label)
                
            cell_data['current_state']['tasks'] = tasks
            
    def _get_month_date_range(self, year, month):
        """Calculate the start and end dates for a month."""
        start_date = datetime(year, month, 1, tzinfo=timezone.utc)
        
        if month == 12:
            end_date = datetime(year + 1, 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
        else:
            end_date = datetime(year, month + 1, 1, tzinfo=timezone.utc) - timedelta(seconds=1)
            
        return start_date, end_date
        
    def _get_prev_month(self, year, month):
        """Get the previous month's year and month values."""
        return (year - 1, 12) if month == 1 else (year, month - 1)
    
    def _get_next_month(self, year, month):
        """Get the next month's year and month values."""
        return (year + 1, 1) if month == 12 else (year, month + 1)
        
    def prev_month(self):
        """Navigate to the previous month."""
        self.displayed_year, self.displayed_month = self._get_prev_month(self.displayed_year, self.displayed_month)
        self._update_monthly_view_data(self.search_entry.text())
        
    def next_month(self):
        """Navigate to the next month."""
        self.displayed_year, self.displayed_month = self._get_next_month(self.displayed_year, self.displayed_month)
        self._update_monthly_view_data(self.search_entry.text())
        
    def wheelEvent(self, event):
        """Handle mouse wheel events to navigate through months in monthly view."""
        if self.current_view == "monthly":
            delta = event.angleDelta().y()
            if delta < 0:  # Scrolling down
                self.next_month()
            elif delta > 0:  # Scrolling up
                self.prev_month()
            event.accept()
        else:

            super().wheelEvent(event)
        
    def closeEvent(self, event):
        """Handle window close event."""
        if hasattr(self, 'worker'):
            self.worker.stop()
        
        if hasattr(self, 'file_monitor'):
            self.file_monitor.stop()
            
        event.accept()
        
    def scroll_to_today(self):
        """Scroll to the current day in either daily or monthly view."""
        today = datetime.now().date()
        
        if self.current_view == "daily":
            month_key = (today.year, today.month)

            if month_key in self.month_containers:
                month_container = self.month_containers[month_key]['container']
                
                pos = month_container.pos().y()
                self.daily_view.verticalScrollBar().setValue(pos)
                
                for widget in month_container.findChildren(QFrame):
                    for child in widget.findChildren(QLabel):
                        if child.text() == format_datetime(today, 'day') and pos > 0:
                            day_pos = widget.pos().y() + pos
                            self.daily_view.verticalScrollBar().setValue(day_pos)
                            return
        
        elif self.current_view == "monthly":
            if today.year != self.displayed_year or today.month != self.displayed_month:
                self.displayed_year = today.year
                self.displayed_month = today.month
                self._update_monthly_view_data(self.search_entry.text())

    def refresh_after_hot_reload(self):
        """Refresh the UI after a hot reload has occurred."""
        self.show_alert("Hot reload detected, refreshing UI...", duration=2000)
        
        current_search = self.search_entry.text() if hasattr(self, 'search_entry') else ""
        current_view = self.current_view
        
        self.clear_widget(self.centralWidget())
        
        main_layout = QVBoxLayout(self.centralWidget())
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)
        
        self.init_navbar(main_layout)
        self.init_main_content(main_layout)
        
        self.search_entry.setText(current_search)
        self.current_view = current_view
        
        if self.current_view == "daily":
            self.view_toggle_button.setText("Monthly View")
            self.views_stack.setCurrentIndex(0)
            self.build_daily_view(current_search)
        else:
            self.view_toggle_button.setText("Daily View")
            self.views_stack.setCurrentIndex(1)
            if not self.monthly_view.layout().count():
                self._create_monthly_view_structure()
            self._update_monthly_view_data(current_search, force_refresh=True)
            
        self.refresh_events()
        
        QTimer.singleShot(100, self.scroll_to_today)