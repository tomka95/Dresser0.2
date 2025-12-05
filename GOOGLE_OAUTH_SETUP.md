# Google OAuth Setup Instructions

## Current Status
Your `.env` file has placeholder values for Google OAuth credentials. You need to replace them with your actual credentials from Google Cloud Console.

## Steps to Fix

### 1. Get Your Google Credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Select your project (or create one)
3. Navigate to **APIs & Services** → **Credentials**
4. Find your **OAuth 2.0 Client ID** (or create one if you don't have it)
5. Click on it to view details
6. Copy the **Client ID** (should look like: `352369953720-xxxxx.apps.googleusercontent.com`)
7. Copy the **Client Secret** (should look like: `GOCSPX-xxxxx`)

### 2. Update Your `.env` File

Open `/Users/guykalir/Dresser2/Dresser0.2/.env` and find these lines:

```bash
GOOGLE_CLIENT_ID=your_client_id_here
GOOGLE_CLIENT_SECRET=your_client_secret_here
```

Replace them with your actual credentials:

```bash
GOOGLE_CLIENT_ID=352369953720-xxxxxxxxxxxxx.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-xxxxxxxxxxxxx
```

**Important:**
- Use the FULL Client ID including `.apps.googleusercontent.com`
- No quotes, no spaces
- Save the file

### 3. Verify Redirect URI in Google Cloud Console

In your OAuth client settings, make sure this **Authorized redirect URI** is added:
```
http://localhost:3000/gmail/callback
```

### 4. Restart Backend Server

After updating `.env`, restart your backend server:

```bash
# Stop the current server (Ctrl+C)
# Then start it again:
cd /Users/guykalir/Dresser2/Dresser0.2
source .venv/bin/activate
python main.py
```

### 5. Test

After restarting, test the endpoint:

```bash
curl "http://localhost:8000/api/v1/gmail/auth/start?redirect_uri=http://localhost:3000/gmail/callback"
```

The `authorization_url` should now contain your actual Client ID (not `your_client_id_here`).

## Troubleshooting

- **Error: "GOOGLE_CLIENT_ID is not set"** → Make sure you saved the `.env` file and restarted the server
- **Error: "invalid_client"** → Double-check that your Client ID includes `.apps.googleusercontent.com`
- **Error: "redirect_uri_mismatch"** → Make sure `http://localhost:3000/gmail/callback` is added in Google Cloud Console

