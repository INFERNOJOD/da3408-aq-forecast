"""Project-wide exception types.

Using our own exceptions lets callers catch project problems separately from
unexpected bugs, and lets the pipeline record a clear failure reason.
"""


class AQError(Exception):
    """Base class for all errors raised on purpose by this project."""


class ConfigError(AQError):
    """A config file or environment variable is missing or invalid."""


class DataValidationError(AQError):
    """Input data failed a hard validation check."""


class PipelineStageError(AQError):
    """A pipeline stage failed; carries the stage name for reporting."""

    def __init__(self, stage: str, message: str) -> None:
        """Store the failing stage name along with the message."""
        super().__init__(f"[{stage}] {message}")
        self.stage = stage
        self.message = message
