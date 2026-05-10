"""Tests for MessageBuilder, AudioFrameBuilder, and ImageFrameBuilder."""

import json

from liveavatar_channel_sdk.audio_frame import AudioFrame
from liveavatar_channel_sdk.audio_frame_builder import AudioFrameBuilder
from liveavatar_channel_sdk.event_type import EventType
from liveavatar_channel_sdk.image_frame import ImageFrame
from liveavatar_channel_sdk.image_frame_builder import ImageFrameBuilder
from liveavatar_channel_sdk.message_builder import MessageBuilder

# ============================================================================
# MessageBuilder Tests
#
# All messages use an "event" field (not "type") and nest payload data under
# a "data" key where the protocol requires it. Top-level identifiers such as
# requestId / responseId / seq / timestamp sit outside "data".
# ============================================================================


class TestMessageBuilderSessions:
    """Test session-related message builders."""

    def test_session_init(self):
        msg = MessageBuilder.session_init("sess-1", "user-1")
        assert msg["event"] == EventType.SESSION_INIT
        assert msg["data"]["sessionId"] == "sess-1"
        assert msg["data"]["userId"] == "user-1"
        assert set(msg.keys()) == {"event", "data"}

    def test_session_ready(self):
        msg = MessageBuilder.session_ready()
        assert msg["event"] == EventType.SESSION_READY
        assert set(msg.keys()) == {"event"}

    def test_session_state(self):
        msg = MessageBuilder.session_state("IDLE", 42, 10000)
        assert msg["event"] == EventType.SESSION_STATE
        assert msg["seq"] == 42
        assert msg["timestamp"] == 10000
        assert msg["data"]["state"] == "IDLE"
        assert set(msg.keys()) == {"event", "seq", "timestamp", "data"}

    def test_session_stop(self):
        msg = MessageBuilder.session_stop()
        assert msg["event"] == EventType.SESSION_STOP
        assert set(msg.keys()) == {"event"}

    def test_session_closing(self):
        msg = MessageBuilder.session_closing("timeout")
        assert msg["event"] == EventType.SESSION_CLOSING
        assert msg["data"]["reason"] == "timeout"
        assert set(msg.keys()) == {"event", "data"}

    def test_session_closing_missing_reason(self):
        msg = MessageBuilder.session_closing()
        assert msg["event"] == EventType.SESSION_CLOSING
        assert "reason" not in msg.get("data", {})

    def test_scene_ready(self):
        msg = MessageBuilder.scene_ready()
        assert msg["event"] == EventType.SCENE_READY
        assert set(msg.keys()) == {"event"}


class TestMessageBuilderInput:
    """Test input-related message builders."""

    def test_input_text(self):
        msg = MessageBuilder.input_text("req-1", "hello world")
        assert msg["event"] == EventType.INPUT_TEXT
        assert msg["requestId"] == "req-1"
        assert msg["data"]["text"] == "hello world"
        assert set(msg.keys()) == {"event", "requestId", "data"}

    def test_input_asr_partial(self):
        msg = MessageBuilder.input_asr_partial("req-1", "hel", 1)
        assert msg["event"] == EventType.INPUT_ASR_PARTIAL
        assert msg["requestId"] == "req-1"
        assert msg["seq"] == 1
        assert msg["data"]["text"] == "hel"
        assert msg["data"]["final"] is False
        assert set(msg.keys()) == {"event", "requestId", "seq", "data"}

    def test_input_asr_final(self):
        msg = MessageBuilder.input_asr_final("req-1", "hello")
        assert msg["event"] == EventType.INPUT_ASR_FINAL
        assert msg["requestId"] == "req-1"
        assert msg["data"]["text"] == "hello"
        # PROTOCOL.md does not define a `final` field on input.asr.final — the
        # event name itself carries that semantic.
        assert "final" not in msg["data"]
        assert set(msg.keys()) == {"event", "requestId", "data"}

    def test_input_voice_start(self):
        msg = MessageBuilder.input_voice_start("req-1")
        assert msg["event"] == EventType.INPUT_VOICE_START
        assert msg["requestId"] == "req-1"
        assert set(msg.keys()) == {"event", "requestId"}

    def test_input_voice_finish(self):
        msg = MessageBuilder.input_voice_finish("req-1")
        assert msg["event"] == EventType.INPUT_VOICE_FINISH
        assert msg["requestId"] == "req-1"
        assert set(msg.keys()) == {"event", "requestId"}


class TestMessageBuilderResponse:
    """Test response-related message builders."""

    def test_response_start_minimal(self):
        msg = MessageBuilder.response_start("req-1", "resp-1")
        assert msg["event"] == EventType.RESPONSE_START
        assert msg["requestId"] == "req-1"
        assert msg["responseId"] == "resp-1"
        assert msg["data"]["audioConfig"]["speed"] == 1.0
        assert msg["data"]["audioConfig"]["volume"] == 1.0
        assert "mood" not in msg["data"]["audioConfig"]
        assert set(msg.keys()) == {"event", "requestId", "responseId", "data"}

    def test_response_start_with_custom_speed_volume(self):
        msg = MessageBuilder.response_start("req-1", "resp-1", speed=1.5, volume=0.8)
        assert msg["event"] == EventType.RESPONSE_START
        assert msg["data"]["audioConfig"]["speed"] == 1.5
        assert msg["data"]["audioConfig"]["volume"] == 0.8
        assert "mood" not in msg["data"]["audioConfig"]

    def test_response_start_with_mood(self):
        msg = MessageBuilder.response_start("req-1", "resp-1", speed=1.2, volume=1.0, mood="happy")
        assert msg["event"] == EventType.RESPONSE_START
        assert msg["data"]["audioConfig"]["speed"] == 1.2
        assert msg["data"]["audioConfig"]["volume"] == 1.0
        assert msg["data"]["audioConfig"]["mood"] == "happy"

    def test_response_chunk(self):
        msg = MessageBuilder.response_chunk("req-1", "resp-1", seq=3, timestamp=1000, text="hello")
        assert msg["event"] == EventType.RESPONSE_CHUNK
        assert msg["requestId"] == "req-1"
        assert msg["responseId"] == "resp-1"
        assert msg["seq"] == 3
        assert msg["timestamp"] == 1000
        assert msg["data"]["text"] == "hello"
        assert set(msg.keys()) == {
            "event",
            "requestId",
            "responseId",
            "seq",
            "timestamp",
            "data",
        }

    def test_response_done(self):
        msg = MessageBuilder.response_done("req-1", "resp-1")
        assert msg["event"] == EventType.RESPONSE_DONE
        assert msg["requestId"] == "req-1"
        assert msg["responseId"] == "resp-1"
        assert set(msg.keys()) == {"event", "requestId", "responseId"}

    def test_response_audio_start(self):
        msg = MessageBuilder.response_audio_start("req-1", "resp-1")
        assert msg["event"] == EventType.RESPONSE_AUDIO_START
        assert msg["requestId"] == "req-1"
        assert msg["responseId"] == "resp-1"
        assert set(msg.keys()) == {"event", "requestId", "responseId"}

    def test_response_audio_finish(self):
        msg = MessageBuilder.response_audio_finish("req-1", "resp-1")
        assert msg["event"] == EventType.RESPONSE_AUDIO_FINISH
        assert msg["requestId"] == "req-1"
        assert msg["responseId"] == "resp-1"
        assert set(msg.keys()) == {"event", "requestId", "responseId"}

    def test_response_audio_prompt_start(self):
        msg = MessageBuilder.response_audio_prompt_start()
        assert msg["event"] == EventType.RESPONSE_AUDIO_PROMPT_START
        assert set(msg.keys()) == {"event"}

    def test_response_audio_prompt_finish(self):
        msg = MessageBuilder.response_audio_prompt_finish()
        assert msg["event"] == EventType.RESPONSE_AUDIO_PROMPT_FINISH
        assert set(msg.keys()) == {"event"}

    def test_response_cancel(self):
        msg = MessageBuilder.response_cancel("resp-1")
        assert msg["event"] == EventType.RESPONSE_CANCEL
        assert msg["responseId"] == "resp-1"
        assert set(msg.keys()) == {"event", "responseId"}


class TestMessageBuilderControl:
    """Test control-related message builders."""

    def test_control_interrupt_without_request_id(self):
        msg = MessageBuilder.control_interrupt()
        assert msg["event"] == EventType.CONTROL_INTERRUPT
        assert "requestId" not in msg
        assert set(msg.keys()) == {"event"}

    def test_control_interrupt_with_request_id(self):
        msg = MessageBuilder.control_interrupt(request_id="req-1")
        assert msg["event"] == EventType.CONTROL_INTERRUPT
        assert msg["requestId"] == "req-1"
        assert set(msg.keys()) == {"event", "requestId"}


class TestMessageBuilderSystem:
    """Test system-related message builders."""

    def test_system_idle_trigger(self):
        msg = MessageBuilder.system_idle_trigger("no_input", 30000)
        assert msg["event"] == EventType.SYSTEM_IDLE_TRIGGER
        assert msg["data"]["reason"] == "no_input"
        assert msg["data"]["idleTimeMs"] == 30000
        assert set(msg.keys()) == {"event", "data"}

    def test_system_prompt(self):
        msg = MessageBuilder.system_prompt("Hey there, are you there?")
        assert msg["event"] == EventType.SYSTEM_PROMPT
        assert msg["data"]["text"] == "Hey there, are you there?"
        assert set(msg.keys()) == {"event", "data"}


class TestMessageBuilderError:
    """Test error message builder."""

    def test_error_without_request_id(self):
        msg = MessageBuilder.error("TIMEOUT", "Request timed out")
        assert msg["event"] == EventType.ERROR
        assert msg["data"]["code"] == "TIMEOUT"
        assert msg["data"]["message"] == "Request timed out"
        assert "requestId" not in msg
        assert set(msg.keys()) == {"event", "data"}

    def test_error_with_request_id(self):
        msg = MessageBuilder.error("INVALID_STATE", "Invalid state transition", request_id="req-1")
        assert msg["event"] == EventType.ERROR
        assert msg["data"]["code"] == "INVALID_STATE"
        assert msg["data"]["message"] == "Invalid state transition"
        assert msg["requestId"] == "req-1"
        assert set(msg.keys()) == {"event", "requestId", "data"}


class TestMessageBuilderJsonSerializable:
    """Test that all messages can be JSON-serialized and round-tripped."""

    def test_all_messages_json_serializable(self):
        messages = [
            MessageBuilder.session_init("sess-1", "user-1"),
            MessageBuilder.session_ready(),
            MessageBuilder.session_state("IDLE", 0, 0),
            MessageBuilder.session_closing("timeout"),
            MessageBuilder.session_stop(),
            MessageBuilder.scene_ready(),
            MessageBuilder.input_text("req-1", "hello"),
            MessageBuilder.input_asr_partial("req-1", "hel", 0),
            MessageBuilder.input_asr_final("req-1", "hello"),
            MessageBuilder.input_voice_start("req-1"),
            MessageBuilder.input_voice_finish("req-1"),
            MessageBuilder.response_start("req-1", "resp-1"),
            MessageBuilder.response_chunk("req-1", "resp-1", 0, 0, "text"),
            MessageBuilder.response_done("req-1", "resp-1"),
            MessageBuilder.response_audio_start("req-1", "resp-1"),
            MessageBuilder.response_audio_finish("req-1", "resp-1"),
            MessageBuilder.response_audio_prompt_start(),
            MessageBuilder.response_audio_prompt_finish(),
            MessageBuilder.response_cancel("resp-1"),
            MessageBuilder.control_interrupt(),
            MessageBuilder.system_idle_trigger("idle", 1000),
            MessageBuilder.system_prompt("hello"),
            MessageBuilder.error("ERROR", "message"),
        ]

        for msg in messages:
            json_str = json.dumps(msg)
            assert isinstance(json_str, str)
            parsed = json.loads(json_str)
            # Every protocol message carries an "event" identifier.
            assert parsed["event"] is not None


# ============================================================================
# AudioFrameBuilder Tests
# ============================================================================


class TestAudioFrameBuilderBasic:
    """Test basic AudioFrameBuilder functionality."""

    def test_default_values(self):
        builder = AudioFrameBuilder()
        packed = builder.build()
        frame = AudioFrame.unpack(packed)
        assert frame.channel == 0
        assert frame.key == 0
        assert frame.seq == 0
        assert frame.timestamp == 0
        assert frame.sample_rate == 0
        assert frame.samples == 0
        assert frame.codec == 0
        assert frame.payload == b""

    def test_fluent_mono_pcm(self):
        packed = (
            AudioFrameBuilder()
            .mono()
            .pcm()
            .sample_rate_16k()
            .seq(10)
            .timestamp(1000)
            .samples(640)
            .payload(b"audio_data")
            .build()
        )
        frame = AudioFrame.unpack(packed)
        assert frame.channel == 0
        assert frame.codec == 0
        assert frame.sample_rate == 0
        assert frame.seq == 10
        assert frame.timestamp == 1000
        assert frame.samples == 640
        assert frame.payload == b"audio_data"

    def test_fluent_stereo_opus(self):
        packed = (
            AudioFrameBuilder()
            .stereo()
            .opus()
            .sample_rate_48k()
            .keyframe()
            .seq(100)
            .timestamp(5000)
            .samples(480)
            .payload(b"opus_frame")
            .build()
        )
        frame = AudioFrame.unpack(packed)
        assert frame.channel == 1
        assert frame.codec == 1
        assert frame.sample_rate == 2
        assert frame.key == 1
        assert frame.seq == 100
        assert frame.timestamp == 5000
        assert frame.samples == 480
        assert frame.payload == b"opus_frame"


class TestAudioFrameBuilderChannels:
    """Test channel-related methods."""

    def test_mono(self):
        packed = AudioFrameBuilder().mono().payload(b"x").build()
        assert AudioFrame.unpack(packed).channel == 0

    def test_stereo(self):
        packed = AudioFrameBuilder().stereo().payload(b"x").build()
        assert AudioFrame.unpack(packed).channel == 1


class TestAudioFrameBuilderSampleRates:
    """Test sample rate methods."""

    def test_sample_rate_16k(self):
        packed = AudioFrameBuilder().sample_rate_16k().payload(b"x").build()
        assert AudioFrame.unpack(packed).sample_rate == 0

    def test_sample_rate_24k(self):
        packed = AudioFrameBuilder().sample_rate_24k().payload(b"x").build()
        assert AudioFrame.unpack(packed).sample_rate == 1

    def test_sample_rate_48k(self):
        packed = AudioFrameBuilder().sample_rate_48k().payload(b"x").build()
        assert AudioFrame.unpack(packed).sample_rate == 2


class TestAudioFrameBuilderCodecs:
    """Test codec methods."""

    def test_pcm(self):
        packed = AudioFrameBuilder().pcm().payload(b"x").build()
        assert AudioFrame.unpack(packed).codec == 0

    def test_opus(self):
        packed = AudioFrameBuilder().opus().payload(b"x").build()
        assert AudioFrame.unpack(packed).codec == 1


class TestAudioFrameBuilderWrapping:
    """Test wrapping behavior for seq and timestamp."""

    def test_seq_wrapping(self):
        # 0xFFF = 4095 (max 12-bit value)
        packed = AudioFrameBuilder().seq(4095).payload(b"x").build()
        assert AudioFrame.unpack(packed).seq == 4095

    def test_seq_overflow_wraps(self):
        # Setting seq to a value > 4095 should wrap
        packed = AudioFrameBuilder().seq(4096).payload(b"x").build()
        assert AudioFrame.unpack(packed).seq == 0

    def test_timestamp_wrapping(self):
        # 0xFFFFF = 1048575 (max 20-bit value)
        packed = AudioFrameBuilder().timestamp(1048575).payload(b"x").build()
        assert AudioFrame.unpack(packed).timestamp == 1048575

    def test_timestamp_overflow_wraps(self):
        # Setting timestamp to a value > 1048575 should wrap
        packed = AudioFrameBuilder().timestamp(1048576).payload(b"x").build()
        assert AudioFrame.unpack(packed).timestamp == 0


class TestAudioFrameBuilderSamples:
    """Test samples field."""

    def test_samples_field(self):
        packed = AudioFrameBuilder().samples(640).payload(b"x").build()
        assert AudioFrame.unpack(packed).samples == 640

    def test_samples_wrapping(self):
        # Max 12-bit value
        packed = AudioFrameBuilder().samples(4095).payload(b"x").build()
        assert AudioFrame.unpack(packed).samples == 4095


class TestAudioFrameBuilderPayload:
    """Test payload handling."""

    def test_empty_payload(self):
        packed = AudioFrameBuilder().payload(b"").build()
        assert AudioFrame.unpack(packed).payload == b""

    def test_payload_preservation(self):
        payload = b"test_audio_data_12345"
        packed = AudioFrameBuilder().payload(payload).build()
        assert AudioFrame.unpack(packed).payload == payload


# ============================================================================
# ImageFrameBuilder Tests
# ============================================================================


class TestImageFrameBuilderBasic:
    """Test basic ImageFrameBuilder functionality."""

    def test_default_values(self):
        builder = ImageFrameBuilder()
        packed = builder.build()
        frame = ImageFrame.unpack(packed)
        assert frame.format == 0
        assert frame.quality == 85
        assert frame.image_id == 0
        assert frame.width == 0
        assert frame.height == 0
        assert frame.payload == b""

    def test_fluent_jpg_640x480(self):
        packed = (
            ImageFrameBuilder()
            .jpg()
            .quality(90)
            .image_id(1)
            .size(640, 480)
            .payload(b"jpeg_data")
            .build()
        )
        frame = ImageFrame.unpack(packed)
        assert frame.format == 0
        assert frame.quality == 90
        assert frame.image_id == 1
        assert frame.width == 640
        assert frame.height == 480
        assert frame.payload == b"jpeg_data"

    def test_fluent_png_1920x1080(self):
        packed = (
            ImageFrameBuilder()
            .png()
            .quality(100)
            .image_id(2)
            .size(1920, 1080)
            .payload(b"png_data")
            .build()
        )
        frame = ImageFrame.unpack(packed)
        assert frame.format == 1
        assert frame.quality == 100
        assert frame.image_id == 2
        assert frame.width == 1920
        assert frame.height == 1080
        assert frame.payload == b"png_data"


class TestImageFrameBuilderFormats:
    """Test format methods."""

    def test_jpg(self):
        packed = ImageFrameBuilder().jpg().payload(b"x").build()
        assert ImageFrame.unpack(packed).format == 0

    def test_png(self):
        packed = ImageFrameBuilder().png().payload(b"x").build()
        assert ImageFrame.unpack(packed).format == 1

    def test_webp(self):
        packed = ImageFrameBuilder().webp().payload(b"x").build()
        assert ImageFrame.unpack(packed).format == 2

    def test_gif(self):
        packed = ImageFrameBuilder().gif().payload(b"x").build()
        assert ImageFrame.unpack(packed).format == 3

    def test_avif(self):
        packed = ImageFrameBuilder().avif().payload(b"x").build()
        assert ImageFrame.unpack(packed).format == 4


class TestImageFrameBuilderQuality:
    """Test quality field."""

    def test_quality_boundary_values(self):
        for q in (0, 85, 255):
            packed = ImageFrameBuilder().quality(q).payload(b"x").build()
            assert ImageFrame.unpack(packed).quality == q

    def test_quality_wrapping(self):
        # Max 8-bit value
        packed = ImageFrameBuilder().quality(255).payload(b"x").build()
        assert ImageFrame.unpack(packed).quality == 255


class TestImageFrameBuilderImageId:
    """Test image_id field."""

    def test_image_id_values(self):
        for img_id in (0, 1, 100, 65535):
            packed = ImageFrameBuilder().image_id(img_id).payload(b"x").build()
            assert ImageFrame.unpack(packed).image_id == img_id

    def test_image_id_wrapping(self):
        # Max 16-bit value
        packed = ImageFrameBuilder().image_id(65535).payload(b"x").build()
        assert ImageFrame.unpack(packed).image_id == 65535


class TestImageFrameBuilderSize:
    """Test size method."""

    def test_size_method(self):
        packed = ImageFrameBuilder().size(1024, 768).payload(b"x").build()
        frame = ImageFrame.unpack(packed)
        assert frame.width == 1024
        assert frame.height == 768

    def test_max_dimensions(self):
        # Max 16-bit values
        packed = ImageFrameBuilder().size(65535, 65535).payload(b"x").build()
        frame = ImageFrame.unpack(packed)
        assert frame.width == 65535
        assert frame.height == 65535


class TestImageFrameBuilderPayload:
    """Test payload handling."""

    def test_empty_payload(self):
        packed = ImageFrameBuilder().payload(b"").build()
        assert ImageFrame.unpack(packed).payload == b""

    def test_payload_preservation(self):
        payload = b"test_image_data_xyz"
        packed = ImageFrameBuilder().payload(payload).build()
        assert ImageFrame.unpack(packed).payload == payload


class TestImageFrameBuilderChaining:
    """Test method chaining."""

    def test_method_chaining_order_independence(self):
        """Verify that method order doesn't matter (fluent interface)."""
        payload = b"test_img"
        packed1 = (
            ImageFrameBuilder()
            .jpg()
            .quality(90)
            .size(640, 480)
            .image_id(5)
            .payload(payload)
            .build()
        )

        packed2 = (
            ImageFrameBuilder()
            .size(640, 480)
            .jpg()
            .payload(payload)
            .quality(90)
            .image_id(5)
            .build()
        )

        frame1 = ImageFrame.unpack(packed1)
        frame2 = ImageFrame.unpack(packed2)

        assert frame1.format == frame2.format == 0
        assert frame1.quality == frame2.quality == 90
        assert frame1.width == frame2.width == 640
        assert frame1.height == frame2.height == 480
        assert frame1.image_id == frame2.image_id == 5
        assert frame1.payload == frame2.payload == payload
