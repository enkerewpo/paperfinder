"""Centralized logging configuration using loguru."""

from __future__ import annotations

import sys
from typing import Optional

from loguru import logger

# Remove default handler
logger.remove()

# Standard format with full context (for development/debugging)
STANDARD_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# CLI format - structured with level and module
CLI_FORMAT = (
    "<level>{level: <8}</level> | "
    "<dim>{name: <25}</dim> | "
    "<level>{message}</level>"
)

# Minimal format - clean, just colored messages (for user-facing output)
MINIMAL_FORMAT = "<level>{message}</level>"


def setup_logging(
    level: str = "INFO",
    format_type: str = "standard",
    colorize: bool = True,
    sink=sys.stderr,
) -> None:
    """Setup loguru logging configuration.
    
    Args:
        level: Log level (TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR, CRITICAL)
        format_type: Format type - 'standard', 'cli', or 'minimal'
        colorize: Enable color output
        sink: Output destination (default: stderr)
    """
    # Remove existing handlers
    logger.remove()
    
    # Select format based on type
    if format_type == "minimal":
        fmt = MINIMAL_FORMAT
    elif format_type == "cli":
        fmt = CLI_FORMAT
    else:
        fmt = STANDARD_FORMAT
    
    # Add handler
    logger.add(
        sink,
        format=fmt,
        level=level,
        colorize=colorize,
        backtrace=True,
        diagnose=True,
    )


# Default setup - will be reconfigured by CLI as needed
setup_logging(level="INFO", format_type="standard")

