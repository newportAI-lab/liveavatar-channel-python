"""Build emotion SSML for avatars configured to use HiThink TTS only."""

from xml.sax.saxutils import escape


_MAX_LENGTH = 10_000
_TARGET_LENGTH = 3_000
_SUFFIX = "</emotion></voice></speak>"
_TEXT_ENTITIES = {'"': '&quot;', "'": '&apos;', '\r': '&#13;'}
_ATTRIBUTES = {**_TEXT_ENTITIES, '\t': '&#9;', '\n': '&#10;'}
_EXPANDED_WIDTH = {**{ch: len(entity) for ch, entity in _TEXT_ENTITIES.items()},
                   '&': 5, '<': 4, '>': 4}
_SENTENCE_END = ".!?。！？\n\r"
_PAUSE = ",;:，；：、 \t"


def hithink_emotion_ssml_segments(text: str, voice_id: str, label: str) -> list[str]:
    """Build ordered emotion SSML fragments for an avatar configured with platform HiThink TTS.

    Pass plain text and the HiThink voice ID from the avatar's configuration.
    The same label is applied to every fragment. Each fragment contains at most
    3,000 Unicode code points, including tags and XML escapes. If the complete
    SSML fits, the list contains one fragment. Send each fragment separately,
    in list order, within the same prompt or response stream.

    For speech without an explicit emotion, send plain text directly through
    the prompt or response method. HiThink documents natural, non, neutral,
    happy, sad, angry, fearful, disgust and surprised. The effect depends on
    the voice. The SDK accepts unrecognized labels, which HiThink treats as
    text without an explicit emotion.

    Raise ValueError for non-string, blank, or XML-invalid arguments, or when
    the markup and the next escaped character cannot fit.
    """
    return hithink_emotion_ssml_segments_with_limit(text, voice_id, label, _TARGET_LENGTH)


def hithink_emotion_ssml_segments_with_limit(
    text: str, voice_id: str, label: str, max_code_points: int,
) -> list[str]:
    """Build HiThink emotion SSML with a custom fragment limit.

    See hithink_emotion_ssml_segments for usage and label handling.
    max_code_points counts Unicode code points in each fragment, including tags
    and XML escapes. It must be an integer from 1 to 10,000. Prefer 4,000 or fewer
    for playback. Raise ValueError for invalid arguments or when the markup and
    the next escaped character cannot fit.
    """
    if type(max_code_points) is not int or not 1 <= max_code_points <= _MAX_LENGTH:
        raise ValueError("max_code_points must be an integer between 1 and 10000")
    prefix = _prefix(text, voice_id, label, max_code_points)
    capacity = max_code_points - len(prefix) - len(_SUFFIX)
    fragments = []
    start = 0
    while start < len(text):
        end = start
        remaining = capacity
        sentence = pause = start
        while end < len(text):
            ch = text[end]
            width = _EXPANDED_WIDTH.get(ch, 1)
            if width > remaining:
                break
            remaining -= width
            end += 1
            if ch in _SENTENCE_END:
                sentence = end
            elif ch in _PAUSE:
                pause = end
        if end == start:
            raise ValueError("HiThink SSML wrapper leaves insufficient room for text")
        if end < len(text):
            end = sentence if sentence > start else pause if pause > start else end
        fragments.append(_fragment(prefix, text[start:end]))
        start = end
    return fragments


def _fragment(prefix: str, text: str) -> str:
    return prefix + escape(text, _TEXT_ENTITIES) + _SUFFIX


def _prefix(text: str, voice_id: str, label: str, limit: int) -> str:
    if any(isinstance(value, str) and len(value) >= limit for value in (voice_id, label)):
        raise ValueError("HiThink SSML attributes exceed the fragment limit")
    for value in (text, voice_id, label):
        if not isinstance(value, str) or not value.strip() or not all(
            cp in (9, 10, 13) or 32 <= cp <= 0xD7FF or 0xE000 <= cp <= 0xFFFD or cp >= 0x10000
            for cp in map(ord, value)
        ):
            raise ValueError("SSML arguments must be non-blank XML characters")
    return (f'<speak><voice name="{escape(voice_id, _ATTRIBUTES)}">'
            f'<emotion type="{escape(label, _ATTRIBUTES)}">')
