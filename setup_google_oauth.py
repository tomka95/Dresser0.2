#!/usr/bin/env python3
"""Helper script to set up Google OAuth credentials in .env file."""
import os
import re

def update_env_file(client_id: str, client_secret: str):
    """Update .env file with Google OAuth credentials."""
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    
    # Read current .env file
    if os.path.exists(env_path):
        with open(env_path, 'r') as f:
            content = f.read()
    else:
        content = ''
    
    # Remove old Google credentials if they exist
    lines = content.split('\n')
    filtered_lines = []
    for line in lines:
        if not line.strip().startswith('GOOGLE_CLIENT_ID') and not line.strip().startswith('GOOGLE_CLIENT_SECRET'):
            filtered_lines.append(line)
    
    # Add new credentials
    filtered_lines.append('')
    filtered_lines.append('# Google OAuth for Gmail Integration')
    filtered_lines.append(f'GOOGLE_CLIENT_ID={client_id}')
    filtered_lines.append(f'GOOGLE_CLIENT_SECRET={client_secret}')
    
    # Write back to file
    with open(env_path, 'w') as f:
        f.write('\n'.join(filtered_lines))
    
    print(f"✅ Successfully updated .env file with Google OAuth credentials!")
    print(f"   Client ID: {client_id[:20]}...")
    print(f"   Client Secret: {client_secret[:10]}...")
    print("\n⚠️  Don't forget to restart your backend server!")

if __name__ == '__main__':
    print("=" * 60)
    print("Google OAuth Credentials Setup")
    print("=" * 60)
    print("\nPlease enter your Google OAuth credentials from Google Cloud Console:")
    print("(You can find these at: https://console.cloud.google.com/apis/credentials)\n")
    
    client_id = input("Enter your Google Client ID (should end with .apps.googleusercontent.com): ").strip()
    client_secret = input("Enter your Google Client Secret (starts with GOCSPX-): ").strip()
    
    if not client_id or client_id == 'your_client_id_here':
        print("\n❌ Error: Invalid Client ID. Please provide your actual Google Client ID.")
        exit(1)
    
    if not client_secret or client_secret == 'your_client_secret_here':
        print("\n❌ Error: Invalid Client Secret. Please provide your actual Google Client Secret.")
        exit(1)
    
    if '.apps.googleusercontent.com' not in client_id:
        print("\n⚠️  Warning: Client ID should include '.apps.googleusercontent.com'")
        response = input("Continue anyway? (y/n): ").strip().lower()
        if response != 'y':
            exit(1)
    
    update_env_file(client_id, client_secret)
    print("\n" + "=" * 60)
    print("Next steps:")
    print("1. Restart your backend server: python main.py")
    print("2. Try clicking 'Log In with Google' again")
    print("=" * 60)

