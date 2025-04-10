import datetime
from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, 
    QPushButton, QFrame, QCalendarWidget, QComboBox, QSpinBox, 
    QGridLayout, QMessageBox, QTimeEdit, QCheckBox, QSizePolicy, QCompleter
)
from PyQt6.QtCore import Qt, QDate, QTime, QStringListModel
from PyQt6.QtGui import QFont

from src.core.utils import convert_to_24, convert_from_24, local_to_utc
from src.core.config import (
    FONT_HEADER, FONT_HEADER_SIZE, FONT_LABEL, FONT_LABEL_SIZE,
    DEFAULT_DIALOG_WIDTH, DEFAULT_DIALOG_HEIGHT, MAIN_STYLE, 
    DROPDOWN_BG_COLOR, TEXT_COLOR
)
from src.core.models import Task

class TaskDialog(QDialog):
    """Dialog for creating and editing tasks."""
    def __init__(self, parent=None, on_confirm=None, task=None):
        super().__init__(parent)
        self.on_confirm = on_confirm
        self.task = task
        
        self.setWindowTitle("Task Dialog")
        self.setFixedSize(DEFAULT_DIALOG_WIDTH, DEFAULT_DIALOG_HEIGHT)
        
        if parent:
            parent_rect = parent.geometry()
            x = parent_rect.x() + (parent_rect.width() - DEFAULT_DIALOG_WIDTH) // 2
            y = parent_rect.y() + (parent_rect.height() - DEFAULT_DIALOG_HEIGHT) // 2
            self.setGeometry(x, y, DEFAULT_DIALOG_WIDTH, DEFAULT_DIALOG_HEIGHT)
        
        self.setup_initial_time()
        
        self.init_ui()
        
    def setup_initial_time(self):
        """Set up initial time values."""
        self.initial_hour = 9
        self.initial_min = 0
        self.initial_period = "AM"
        
        if self.task:
            local_start = self.task.start_dt.astimezone()
            local_end = self.task.end_dt.astimezone()
            
            self.initial_hour, self.initial_period = convert_from_24(str(local_start.hour))
            self.initial_min = local_start.minute
            
            self.initial_date = local_start.date()
        else:
            now = datetime.now()
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            hour_12, period = convert_from_24(str(next_hour.hour))
            self.initial_hour = hour_12
            self.initial_min = 0
            self.initial_period = period
            
            self.initial_date = now.date()
            
    def init_ui(self):
        """Create and arrange all dialog widgets."""
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(10)
        
        header_text = "Edit Task" if self.task else "Add New Task"
        header_label = QLabel(header_text)
        header_font = QFont(FONT_HEADER, FONT_HEADER_SIZE)
        header_font.setBold(True)
        header_label.setFont(header_font)
        header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(header_label)
        
        summary_label = QLabel("Task Summary:")
        summary_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        main_layout.addWidget(summary_label)
        
        self.summary_edit = QLineEdit()
        self.summary_edit.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        if self.task:
            self.summary_edit.setText(self.task.summary)
        main_layout.addWidget(self.summary_edit)
        
        self.calendar = QCalendarWidget()
        self.calendar.setGridVisible(True)
        self.calendar.setVerticalHeaderFormat(QCalendarWidget.VerticalHeaderFormat.NoVerticalHeader)
        if hasattr(self, 'initial_date'):
            self.calendar.setSelectedDate(QDate(
                self.initial_date.year,
                self.initial_date.month,
                self.initial_date.day
            ))
        main_layout.addWidget(self.calendar)
        
        time_frame = QFrame()
        time_layout = QGridLayout(time_frame)
        time_layout.setSpacing(5)
        
        start_label = QLabel("Start Time:")
        start_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        time_layout.addWidget(start_label, 0, 0)
        
        start_time_layout = QHBoxLayout()
        
        self.start_hour = QSpinBox()
        self.start_hour.setRange(1, 12)
        self.start_hour.setValue(self.initial_hour)
        self.start_hour.setFixedWidth(60)
        self.start_hour.valueChanged.connect(self.update_end_time)
        start_time_layout.addWidget(self.start_hour)
        
        time_layout.addWidget(QLabel(":"), 0, 1)
        
        self.start_min = QSpinBox()
        self.start_min.setRange(0, 59)
        self.start_min.setValue(self.initial_min)
        self.start_min.setFixedWidth(60)
        self.start_min.setSingleStep(5)
        self.start_min.valueChanged.connect(self.update_end_time)
        start_time_layout.addWidget(self.start_min)
        
        self.start_period = QComboBox()
        self.start_period.addItems(["AM", "PM"])
        self.start_period.setCurrentText(self.initial_period)
        self.start_period.currentTextChanged.connect(self.update_end_time)
        start_time_layout.addWidget(self.start_period)
        
        time_layout.addLayout(start_time_layout, 0, 2)
        
        end_label = QLabel("End Time:")
        end_label.setFont(QFont(FONT_LABEL, FONT_LABEL_SIZE))
        time_layout.addWidget(end_label, 1, 0)
        
        end_time_layout = QHBoxLayout()
        
        self.end_hour = QSpinBox()
        self.end_hour.setRange(1, 12)
        self.end_hour.setFixedWidth(60)
        end_time_layout.addWidget(self.end_hour)
        
        time_layout.addWidget(QLabel(":"), 1, 1)
        
        self.end_min = QSpinBox()
        self.end_min.setRange(0, 59)
        self.end_min.setFixedWidth(60)
        self.end_min.setSingleStep(5)
        end_time_layout.addWidget(self.end_min)
        
        self.end_period = QComboBox()
        self.end_period.addItems(["AM", "PM"])
        end_time_layout.addWidget(self.end_period)
        
        time_layout.addLayout(end_time_layout, 1, 2)
        
        main_layout.addWidget(time_frame)
        
        button_layout = QHBoxLayout()
        
        if self.task and self.task.task_id:
            delete_btn = QPushButton("Delete")
            delete_btn.setStyleSheet("background-color: #AA3333; color: white;")
            delete_btn.clicked.connect(self.delete_task)
            button_layout.addWidget(delete_btn)
            
            confirm_btn = QPushButton("Save")
            confirm_btn.clicked.connect(self.confirm)
            button_layout.addWidget(confirm_btn)
        else:
            confirm_btn = QPushButton("Create")
            confirm_btn.clicked.connect(self.confirm)
            button_layout.addWidget(confirm_btn)
        
        main_layout.addLayout(button_layout)
        
        if self.task:
            self.init_time_fields()
        else:
            self.update_end_time()
            
    def init_time_fields(self):
        """Initialize time fields when editing an existing task."""
        local_start = self.task.start_dt.astimezone()
        local_end = self.task.end_dt.astimezone()
        
        self.calendar.setSelectedDate(QDate(
            local_start.year,
            local_start.month, 
            local_start.day
        ))
        
        start_hour, start_period = convert_from_24(str(local_start.hour))
        self.start_hour.setValue(start_hour)
        self.start_min.setValue(local_start.minute)
        self.start_period.setCurrentText(start_period)
        
        end_hour, end_period = convert_from_24(str(local_end.hour))
        self.end_hour.setValue(end_hour)
        self.end_min.setValue(local_end.minute)
        self.end_period.setCurrentText(end_period)
            
    def update_end_time(self):
        """Update end time to be 1 hour after start time."""
        try:
            start_hour = self.start_hour.value()
            start_min = self.start_min.value()
            start_period = self.start_period.currentText()
            
            start_hour_24 = convert_to_24(str(start_hour), start_period)
            
            end_hour_24 = (start_hour_24 + 1) % 24
            
            end_hour_12, end_period = convert_from_24(str(end_hour_24))
            
            self.end_hour.setValue(end_hour_12)
            self.end_min.setValue(start_min)
            self.end_period.setCurrentText(end_period)
        except (ValueError, TypeError) as e:
            print(f"Error updating end time: {str(e)}")
            
    def delete_task(self):
        """Delete the current task."""
        if self.task and self.task.task_id:
            parent = self.parent()
            if parent and hasattr(parent, 'delete_task'):
                parent.delete_task(self.task)
            self.accept()
            
    def confirm(self):
        """Validate input and create/update task."""
        summary = self.summary_edit.text().strip()
        if not summary:
            QMessageBox.warning(self, "Warning", "Task summary cannot be empty.")
            return
            
        selected_date = self.calendar.selectedDate()
        date_str = f"{selected_date.year()}-{selected_date.month():02d}-{selected_date.day():02d}"
        
        try:
            start_hour_24 = convert_to_24(str(self.start_hour.value()), self.start_period.currentText())
            end_hour_24 = convert_to_24(str(self.end_hour.value()), self.end_period.currentText())
            
            local_tz = datetime.now().astimezone().tzinfo
            start_dt_local = datetime.strptime(
                f"{date_str} {start_hour_24:02d}:{self.start_min.value():02d}", 
                "%Y-%m-%d %H:%M"
            )
            start_dt_local = start_dt_local.replace(tzinfo=local_tz)
            start_dt = local_to_utc(start_dt_local)
            
            end_dt_local = datetime.strptime(
                f"{date_str} {end_hour_24:02d}:{self.end_min.value():02d}", 
                "%Y-%m-%d %H:%M"
            )
            end_dt_local = end_dt_local.replace(tzinfo=local_tz)
            end_dt = local_to_utc(end_dt_local)
            
            if end_dt <= start_dt:
                QMessageBox.warning(self, "Warning", "End time must be after start time.")
                return
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Invalid date or time: {str(e)}")
            return
            
        if self.task:
            self.task.summary = summary
            self.task.start_dt = start_dt
            self.task.end_dt = end_dt
        else:
            self.task = Task(summary, start_dt, end_dt)
            
        if self.on_confirm:
            self.on_confirm(self.task)
            
        self.accept() 