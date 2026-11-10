"""Failures the ingest pipeline can explain to the user.

The message of an `IngestError` is written for the person who dropped the item: the worker stores
it in `inbox_items.error` and the web app shows it as is. Any other exception is treated as a bug
or an outage: the worker logs the traceback and shows a generic message instead.
"""


class IngestError(Exception):
    """A failure with a user-readable message. Permanent unless `retryable` is set."""

    # False: trying again cannot help (a blocked address, a page with no text), so the worker
    # marks the item failed at once. True: worth another attempt (a timeout, a 503).
    retryable = False
