"""Google OAuth integration for Gmail access."""
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from dotenv import load_dotenv
from datetime import datetime, timedelta
from typing import List, Tuple
import base64
import os

from .models import EmailMetadata
from .config import MAX_YEARS_TO_SCAN

# Load environment variables
load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def create_oauth_flow(redirect_uri: str):
    """Create OAuth flow for Gmail access."""
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if not client_id or client_id == "your_client_id_here":
        raise ValueError(
            "GOOGLE_CLIENT_ID is not set or is still a placeholder. "
            "Please set GOOGLE_CLIENT_ID in your .env file with your actual Google Client ID."
        )
    
    if not client_secret or client_secret == "your_client_secret_here":
        raise ValueError(
            "GOOGLE_CLIENT_SECRET is not set or is still a placeholder. "
            "Please set GOOGLE_CLIENT_SECRET in your .env file with your actual Google Client Secret."
        )
    
    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    
    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )
    return flow


def get_gmail_service(credentials_dict: dict):
    """Build Gmail service from credentials."""
    # Build credentials object with all required fields
    creds = Credentials(
        token=credentials_dict.get('access_token') or credentials_dict.get('token'),
        refresh_token=credentials_dict.get('refresh_token'),
        token_uri=credentials_dict.get('token_uri'),
        client_id=credentials_dict.get('client_id'),
        client_secret=credentials_dict.get('client_secret'),
        scopes=credentials_dict.get('scopes', SCOPES)
    )
    
    service = build('gmail', 'v1', credentials=creds)
    return service


def _decode_message_body(payload: dict) -> str:
    """Extract and decode message body from Gmail API payload."""
    body_data = ""
    
    if 'parts' in payload:
        # Multipart message
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                if 'data' in part['body']:
                    body_data = part['body']['data']
                    break
            elif part['mimeType'] == 'text/html' and not body_data:
                if 'data' in part['body']:
                    body_data = part['body']['data']
    else:
        # Simple message
        if 'data' in payload.get('body', {}):
            body_data = payload['body']['data']
    
    if body_data:
        # Decode base64url
        decoded_bytes = base64.urlsafe_b64decode(body_data)
        return decoded_bytes.decode('utf-8', errors='ignore')
    
    return ""


def fetch_purchase_emails_via_api(
    service,
    max_years: int | None = None
) -> List[Tuple[EmailMetadata, str]]:
    """Fetch purchase-like emails using Gmail API.
    
    Args:
        service: Gmail API service object
        max_years: How many years back to scan (default from config)
        
    Returns:
        List of (EmailMetadata, body_text) tuples
    """
    years = max_years if max_years is not None else MAX_YEARS_TO_SCAN
    if years <= 0:
        years = 1
    
    since_date = datetime.utcnow() - timedelta(days=365 * years)
    since_str = since_date.strftime('%Y/%m/%d')
    
    # Search for purchase/order-related emails
    query = f'after:{since_str} (subject:order OR subject:purchase OR subject:receipt OR subject:confirmation)'
    
    results = []
    page_token = None
    
    try:
        while True:
            # List messages matching query
            response = service.users().messages().list(
                userId='me',
                q=query,
                pageToken=page_token,
                maxResults=100
            ).execute()
            
            messages = response.get('messages', [])
            
            for msg_ref in messages:
                # Get full message
                msg = service.users().messages().get(
                    userId='me',
                    id=msg_ref['id'],
                    format='full'
                ).execute()
                
                # Extract headers
                headers = {h['name'].lower(): h['value'] for h in msg['payload'].get('headers', [])}
                
                metadata = EmailMetadata(
                    message_id=msg['id'],
                    thread_id=msg.get('threadId', ''),
                    subject=headers.get('subject', ''),
                    sender=headers.get('from', ''),
                    sent_at=datetime.fromtimestamp(int(msg['internalDate']) / 1000),
                    snippet=msg.get('snippet'),
                    labels=msg.get('labelIds', [])
                )
                
                # Decode body
                body_text = _decode_message_body(msg['payload'])
                
                results.append((metadata, body_text))
            
            # Check for more pages
            page_token = response.get('nextPageToken')
            if not page_token:
                break
                
    except Exception as e:
        print(f"Error fetching emails: {e}")
    
    return results

