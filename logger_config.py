import logging
import sys

def setup_logging():
    """Sets up the global logging configuration."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(module)s:%(lineno)d | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout)
            # You could add a FileHandler here as well
        ]
    )
    # Silence overly verbose libraries if needed
    # logging.getLogger("httpx").setLevel(logging.WARNING)

def get_logger(name: str) -> logging.Logger:
    """Returns a logger instance for a specific module."""
    return logging.getLogger(name)

# Initial setup when this module is imported
setup_logging()