"""Gmail token seam for closet ingestion.

The regex extraction pipeline that used to live here was deleted in phase 3a.
What remains is the OAuth token seam (gmail_oauth_service / gmail_oauth_client)
and small shared data (models.EmailMetadata, retailers) that the 3b rebuild
builds on.
"""


