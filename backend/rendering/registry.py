from rendering.generic_frame_renderer import GenericFrameRenderer


class RendererRegistry:
    """
    Maps renderer-neutral visual types to renderer implementations.
    """

    def __init__(self) -> None:
        generic_renderer = GenericFrameRenderer()
        self._renderers = {
            "text": generic_renderer,
            "diagram": generic_renderer,
            "process": generic_renderer,
            "comparison": generic_renderer,
            "animation": generic_renderer,
            "mixed": generic_renderer,
        }

    def get(self, visual_type: str):
        """
        Return the renderer registered for the given generic visual type.
        """
        renderer_name = visual_type.lower().strip()

        try:
            return self._renderers[renderer_name]
        except KeyError as exc:
            raise ValueError(
                f"Unknown visual type: {visual_type}"
            ) from exc
