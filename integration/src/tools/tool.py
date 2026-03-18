"""Tool interface."""

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Tool interface with execute method."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description."""
        pass

    @abstractmethod
    def execute(self, **kwargs) -> dict[str, Any]:
        """Execute the tool with given parameters."""
        pass
