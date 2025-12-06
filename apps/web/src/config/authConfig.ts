// Google OAuth Configuration
// TODO: Move GOOGLE_CLIENT_ID to environment variables

export const GOOGLE_CLIENT_ID = "380922352484-uud7m4vg7sveaj3crrj6hr47uatsptvr.apps.googleusercontent.com";

/**
 * Constructs the Google OAuth authorization URL
 * @returns Full OAuth URL with all required parameters
 */
export function getGoogleOAuthUrl(): string {
  const params = new URLSearchParams({
    client_id: GOOGLE_CLIENT_ID,
    redirect_uri: `${window.location.origin}/google/callback`,
    response_type: "code",
    access_type: "offline",
    prompt: "consent",
    scope: [
      "openid",
      "email",
      "profile",
      "https://www.googleapis.com/auth/gmail.readonly",
    ].join(" "),
  });

  return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
}

