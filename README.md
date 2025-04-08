## Setup Instructions

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

1. Create a project in Google Cloud Console
2. Enable the Google Calendar API
3. Create OAuth 2.0 credentials
4. Download the credentials JSON file and rename it to `credentials.json`
5. Place it in the same directory as the application

### 4. Run the application
```
python todolist.py

```
The first time you run the application, it will open a browser window for Google authentication. 