from abc import ABC, abstractmethod
from pathlib import Path


class BaseRenderer(ABC):
    """
    Base interface for all educational visual renderers.
    """

    @abstractmethod
    def render(
        self,
        description: str,
        output_dir: Path,
    ) -> Path:
        """
        Render a visual instruction and return the generated video path.
        """
        raise NotImplementedError