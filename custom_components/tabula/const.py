DOMAIN = "tabula"

CONF_API_KEY = "api_key"

DEFAULT_BASE_URL = "https://api.tabula.de"
# TODO: allow overriding base_url for staging once they expose one

ATTR_PATH = "path"
ATTR_DOCUMENT_TYPE = "document_type"
ATTR_EXTERNAL_ID = "external_id"
ATTR_UPLOAD_ID = "upload_id"
ATTR_BATCH_ID = "batch_id"
ATTR_POLL = "poll"
ATTR_CONFIG_ENTRY_ID = "config_entry_id"

DOCUMENT_TYPES = (
    "auto",
    "supplier_invoice",
    "customer_invoice",
    "bank_statement",
    "other_document",
)

UPLOAD_TERMINAL = frozenset({"completed", "failed", "deleted"})
BATCH_TERMINAL = frozenset(
    {"completed", "completed_with_errors", "failed"}
)

EVENT_UPLOAD = "tabula_upload"
EVENT_BATCH = "tabula_batch"
