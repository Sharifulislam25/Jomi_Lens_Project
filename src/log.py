"""Application logging. Logs never contain personal data (only IDs, statuses and error types)."""
import logging

logger = logging.getLogger("jomilens")
if not logger.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(h)
    logger.setLevel(logging.INFO)
