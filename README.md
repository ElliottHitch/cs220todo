## To-Do List Application with Google Calendar Integration

### Setup Instructions

### 1. Create and activate a virtual environment

**Windows**:
```
python -m venv venv
venv\Scripts\activate
```

**macOS/Linux**:
```
python3 -m venv venv
source venv/bin/activate
```

### 2. Install dependencies

```
pip install -r requirements.txt
```

### 3. Google API Setup

```
Place credentials.json in /config
```

### 4. Run the application
```
python main.py
```

The first time you run the application, it will open a browser window for Google authentication. After authenticating, a `token.json` file will be created automatically in the `config` folder to store your access tokens.

### 5. Using the application

- The application displays your calendar events and lets you create, update, and delete tasks
- Tasks are synchronized with your Google Calendar
- You can filter tasks using the search bar 