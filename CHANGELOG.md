# Changelog

Notable changes to this SDK are documented here. The date is the release day.

## [0.4.1] - 2026-10-15

1. Added: `AvatarAgentConfig` adds the optional parameter `external_audio_config`. `sampleRate`: `0` or omitted follows the session voice format; otherwise 16000, 24000, 44100, or 48000. `channels`: `0` or omitted follows the session voice format; otherwise 1 or 2. Any other value is rejected. On session start it is sent as `externalAudioConfig`.
2. Added: `send_external_audio(pcm, timestamp_us=0)` is a new method. `pcm` is 16-bit little-endian PCM. `timestamp_us` of `0` lets the platform choose the presentation time. The audio does not drive lip sync. Do not use `response.audio.*`. Its sample rate and channel count must match `external_audio_config` when set, otherwise the session TTS format. One frame including its header must not exceed 65536 bytes. Send later packets before the queued audio finishes, and make the first packet longer than the later ones without exceeding that limit.
3. Added: `send_interrupt` adds the string parameter `interrupt_scope`. An omitted value, an empty value, and `VOICE_ONLY` stop voice playback only. `BGM_ONLY` clears queued external audio only. `VOICE_AND_ACCOMPANIMENT` stops voice playback and clears queued external audio. Surrounding spaces are removed. Any other value is rejected before sending. The value is sent as `data.interruptScope` on `control.interrupt`. Base-video audio is not cleared.
4. Fixed: response lifecycle callbacks can call back into the SDK without deadlocking or being rejected as reentrant.
5. Changed: the `response.state` description in the protocol document was clarified. Runtime behavior is unchanged.
6. Changed: session start fields `onceVideoIds` and `loopVideoIds`, and `scene.switchVideo` fields `onceVideos`, `loopVideos`, and `videoChoreographyGroups`, used to accept only resource IDs. Each item may now also be an alias of that avatar's base video. An alias is 3 to 32 characters, starts with a letter, uses only lowercase letters, digits, and underscores, and does not end with an underscore. The SDK passes the string through. The platform replaces an alias with its resource ID before playback.

## [0.4.0] - 2026-09-10

### Added

- Response lifecycle support.

## [0.3.0] - 2026-09-04

### Added

- Response stream lifecycle.

## [0.2.7] - 2026-08-06

### Added

- Resource transition messages.

## [0.2.6] - 2026-07-10

### Added

- The `scene.ready` event.

## [0.2.5] - 2026-07-09

### Added

- Metadata on agent messages.

## [0.2.4] - 2026-06-28

### Added

- A mode parameter on the agent configuration.

## [0.2.3] - 2026-06-25

### Added

- Voice configuration.

## [0.2.0] - 2026-05-15

### Changed

- Server dependencies and the example package were removed from the distribution.

## [0.1.0] - 2026-04-10

### Added

- Initial SDK release.
