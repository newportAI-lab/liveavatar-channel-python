import pytest
from liveavatar_channel_sdk.audio_frame import AudioFrame


def test_round_trip_basic():
    frame = AudioFrame(
        channel=0, key=1, seq=100, timestamp=5000,
        sample_rate=0, samples=640, codec=0, payload=b"audio_data",
    )
    assert AudioFrame.unpack(frame.pack()) == frame


def test_round_trip_stereo_opus():
    frame = AudioFrame(
        channel=1, key=0, seq=4095, timestamp=1048575,
        sample_rate=2, samples=480, codec=1, payload=b"\x00\xff" * 50,
    )
    assert AudioFrame.unpack(frame.pack()) == frame


def test_seq_wrapping_boundary():
    frame = AudioFrame(seq=4095, payload=b"x")
    unpacked = AudioFrame.unpack(frame.pack())
    assert unpacked.seq == 4095


def test_timestamp_wrapping_boundary():
    frame = AudioFrame(timestamp=1048575, payload=b"x")
    unpacked = AudioFrame.unpack(frame.pack())
    assert unpacked.timestamp == 1048575


def test_header_length():
    frame = AudioFrame(payload=b"hello")
    packed = frame.pack()
    assert len(packed) == 9 + 5


def test_type_bits_fixed():
    """Type field must always be 0b01 for audio frames."""
    frame = AudioFrame(payload=b"")
    packed = frame.pack()
    # First byte: top 2 bits should be 01 (0x40)
    assert (packed[0] >> 6) == 0b01


def test_empty_payload():
    frame = AudioFrame(payload=b"")
    unpacked = AudioFrame.unpack(frame.pack())
    assert unpacked == frame
    assert unpacked.payload == b""


def test_all_sample_rates():
    for sr in (0, 1, 2):
        frame = AudioFrame(sample_rate=sr, payload=b"sr")
        assert AudioFrame.unpack(frame.pack()).sample_rate == sr


def test_both_codecs():
    for codec in (0, 1):
        frame = AudioFrame(codec=codec, payload=b"c")
        assert AudioFrame.unpack(frame.pack()).codec == codec


def test_length_field_matches_payload():
    payload = b"abcdefghij"
    frame = AudioFrame(payload=payload)
    packed = frame.pack()
    # L field is the last 2 bytes of the 9-byte header (bits 0-15)
    header_int = int.from_bytes(packed[:9], "big")
    length_field = header_int & 0xFFFF
    assert length_field == len(payload)


def test_wrong_type_raises():
    # Construct a frame with type bits set to 0b10 (image) and try to unpack as audio
    val = 0b10 << 70  # type = image
    data = val.to_bytes(9, "big") + b"payload"
    with pytest.raises(ValueError, match="Not an audio frame"):
        AudioFrame.unpack(data)


def test_too_short_raises():
    with pytest.raises(ValueError, match="too short"):
        AudioFrame.unpack(b"\x00" * 8)
