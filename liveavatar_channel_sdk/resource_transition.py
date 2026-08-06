"""Data model for renderer video resource transitions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ResourceTransitionData:
    """Details for the ``scene.resourceTransition`` event.

    The platform sends this event when the renderer has finished the current
    video resource and is about to switch to the next one. The event is scoped by
    the WebSocket session that delivered it, so this model intentionally does not
    include a separate ``stream_id``.

    Attributes:
        previous_resource_id: Required stable business resource ID that is being
            switched away from. This is not a URL, file path, or display name.
        next_resource_id: Required stable business resource ID that the renderer
            is about to switch to.
        message: Optional human-readable context from the platform. Do not use it
            for branching; use the two resource ID fields instead.
    """

    previous_resource_id: str
    next_resource_id: str
    message: str | None = None

    def has_required_resource_ids(self) -> bool:
        """Return whether both authoritative resource IDs are present.

        Empty or whitespace-only strings are treated as missing because callers
        cannot safely distinguish them from real resource IDs.
        """
        return bool(self.previous_resource_id and self.previous_resource_id.strip()) and bool(
            self.next_resource_id and self.next_resource_id.strip()
        )
