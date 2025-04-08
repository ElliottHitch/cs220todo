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

You need to set up Google Calendar API credentials:

1. Go to the [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the Google Calendar API for your project
4. Create OAuth 2.0 credentials (Desktop application type)
5. Download the credentials JSON file and save it as `credentials.json` in the root folder of this project


### 4. Run the application
```
python todolist.py
```

The first time you run the application, it will open a browser window for Google authentication. After authenticating, a `token.json` file will be created automatically to store your access tokens.

### 5. Using the application

- The application displays your calendar events and lets you create, update, and delete tasks
- Tasks are synchronized with your Google Calendar
- You can filter tasks using the search bar 