"""Configuration constants for the Gmail clothing extraction pipeline."""

# Maximum number of years to look back when scanning emails
MAX_YEARS_TO_SCAN = .2

# Maximum concurrent LLM extraction requests
MAX_CONCURRENT_EXTRACTIONS = 5

# IMAP server settings
IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993

# Email search terms for purchase/receipt emails
PURCHASE_SEARCH_TERMS = [
    "order",
    "receipt",
    "confirmation",
    "purchase",
    "shipped",
    "delivered",
    "invoice",
    "payment",
    "transaction",
]

# Folders to exclude from search
EXCLUDED_FOLDERS = ["[Gmail]/Spam", "[Gmail]/Trash", "Spam", "Trash"]

