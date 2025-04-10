import queue
import threading
from PyQt6.QtCore import QThread, pyqtSignal

class APIWorker(QThread):
    """Worker thread for handling API calls without blocking the UI."""
    taskCompleted = pyqtSignal(object, object)
    taskError = pyqtSignal(Exception, object)
    loadingChanged = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue = queue.Queue()
        self.running = True
        
    def add_task(self, task_type, func, **kwargs):
        """Add a task to the queue."""
        self.queue.put((task_type, func, kwargs))
            
        if not self.isRunning():
            self.start()
    
    def run(self):
        """Main worker loop that processes queued tasks."""
        while self.running:
            try:
                try:
                    task_type, func, kwargs = self.queue.get(block=True, timeout=0.5)
                except queue.Empty:
                    continue
                
                try:
                    if task_type not in ['background_fetch', 'preload']:
                        self.loadingChanged.emit(True)
                    
                    result = func(**kwargs)
                    
                    self.taskCompleted.emit(result, task_type)
                    
                except Exception as e:
                    print(f"Error in worker thread ({task_type}): {str(e)}")
                    self.taskError.emit(e, task_type)
                
                finally:
                    if task_type not in ['background_fetch', 'preload']:
                        self.loadingChanged.emit(False)
                    self.queue.task_done()
                    
            except Exception as e:
                print(f"Unexpected error in worker thread: {str(e)}")
                
        print("Worker thread stopped")
                
    def stop(self):
        """Stop the worker thread."""
        self.running = False
        self.wait(1000) 