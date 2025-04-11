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
        self.services = {}
        self.load_credentials()
        
    def load_credentials(self):
        """Load credentials from the token file."""
        if os.path.exists(TOKEN_FILE):
            self.creds = Credentials.from_authorized_user_info(
                json.loads(open(TOKEN_FILE, 'r').read()), 
                SCOPES
            )
            
        if not self.creds or not self.creds.valid:
            self.refresh_token()
                
    def get_credentials(self):
        """Return the current credentials, refreshing if needed."""
        self.refresh_token_if_needed()
        return self.creds

    def refresh_token_if_needed(self):
        """Check if token needs refreshing and refresh it if necessary."""
        if not self.creds:
            self.load_credentials()
            return
            
        if self.creds and hasattr(self.creds, 'expiry'):
            now = datetime.datetime.now(timezone.utc)
            if self.creds.expiry and self.creds.expiry.tzinfo is None:
                expiry = self.creds.expiry.replace(tzinfo=timezone.utc)
            else:
                expiry = self.creds.expiry
                
            time_until_expiry = (expiry - now).total_seconds() if expiry else 0
            
            if time_until_expiry < self.refresh_buffer:
                print(f"Token will expire soon ({time_until_expiry:.1f} seconds). Refreshing...")
                self.refresh_token()
        
    def refresh_token(self):
        """Refresh or create new credentials."""
        try:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
                self.creds = flow.run_local_server(port=0)
                
            with open(TOKEN_FILE, 'w') as token:
                token.write(self.creds.to_json())
                
            self.services = {}
            return True
        except Exception as e:
            print(f"Error refreshing token: {str(e)}")
            return False

    def get_service(self, service_name, version):
        """Get an authenticated service instance with caching."""
        self.refresh_token_if_needed()
        
        cache_key = f"{service_name}_{version}"
        if cache_key in self.services:
            return self.services[cache_key]
            
        from googleapiclient.discovery import build
        service = build(service_name, version, credentials=self.creds)
        self.services[cache_key] = service
        return service

    def get_calendar_service(self):
        """Get an authenticated calendar service instance."""
        return self.get_service('calendar', 'v3')

    def get_tasks_service(self):
        """Get an authenticated tasks service instance."""
        return self.get_service('tasks', 'v1') 