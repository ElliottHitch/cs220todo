import os
import json
import logging
import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from src.core.config import CREDENTIALS_FILE, TOKEN_FILE, SCOPES
from datetime import timezone

class AuthManager:
    """Class to handle Google API authentication."""
    
    def __init__(self):
        """Initialize the authentication manager."""
        self.creds = None
        self.refresh_buffer = 300
        self.service = None
        self.load_credentials()
        
    def load_credentials(self):
        """Load and refresh credentials from the token file."""
        if os.path.exists(TOKEN_FILE):
            self.creds = Credentials.from_authorized_user_info(
                json.loads(open(TOKEN_FILE, 'r').read()), 
                SCOPES
            )
            
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    CREDENTIALS_FILE, SCOPES)
                self.creds = flow.run_local_server(port=0)
            
            with open(TOKEN_FILE, 'w') as token:
                token.write(self.creds.to_json())
                
    def get_credentials(self):
        """Return the current credentials."""
        return self.creds

    def refresh_if_needed(self):
        """Refresh the credentials if they are expired."""
        if self.creds and self.creds.expired and self.creds.refresh_token:
            self.creds.refresh(Request())
            with open(TOKEN_FILE, 'w') as token:
                token.write(self.creds.to_json())
            self.service = None

    def auto_refresh_token(self):
        """Check if token is about to expire and refresh it proactively."""
        if not self.creds:
            self.load_credentials()
            self.service = None
            return True
            
        if self.creds and hasattr(self.creds, 'expiry'):
            now = datetime.datetime.now(timezone.utc)
            if self.creds.expiry and self.creds.expiry.tzinfo is None:
                expiry = self.creds.expiry.replace(tzinfo=timezone.utc)
            else:
                expiry = self.creds.expiry
                
            time_until_expiry = (expiry - now).total_seconds() if expiry else 0
            
            if time_until_expiry < self.refresh_buffer:
                print(f"Token will expire soon ({time_until_expiry:.1f} seconds). Refreshing...")
                try:
                    self.creds = self._refresh_credentials(self.creds)
                    self.service = None
                    return True
                except Exception as e:
                    print(f"Error refreshing token: {str(e)}")
                    return False
        
        return False
        
    def _refresh_credentials(self, creds):
        """Refresh or create new credentials."""
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        self.service = None
        return creds

    def get_calendar_service(self):
        """Get an authenticated calendar service instance."""
        if self.service is not None:
            return self.service
        from googleapiclient.discovery import build
        self.service = build('calendar', 'v3', credentials=self.creds)
        return self.service 

    def get_tasks_service(self):
        """Get an authenticated tasks service instance."""
        from googleapiclient.discovery import build
        return build('tasks', 'v1', credentials=self.creds) 