from dataclasses import dataclass

import pytest

from face_tracker import TrackManager

BOX = (0.0, 0.0, 100.0, 100.0)
DISTANT_BOX = (300.0, 0.0, 100.0, 100.0)


@dataclass
class Clock:
    now: float = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def manager(clock):
    return TrackManager(monotonic=clock)


def test_first_attempt_still_requires_three_quality_observations(manager):
    track = manager.assign([BOX])[0]

    assert [manager.observe_quality(track) for _ in range(3)] == [False, False, True]


def test_success_suppresses_attempts_without_extending_deadline(manager, clock):
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    deadline = track.success_recheck_at

    for now in (0.1, 0.2, 0.3, 0.9, 0.999):
        clock.now = now
        assert manager.assign([BOX])[0] is track
        assert not manager.observe_quality(track)
        assert track.success_recheck_at == deadline
        assert track.failures == 0

    assert track.quality_observations == 3
    clock.now = 1.0
    assert manager.observe_quality(track)


def test_expiry_alone_does_not_replace_three_quality_observations(manager, clock):
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    clock.now = 2.0

    assert [manager.observe_quality(track) for _ in range(3)] == [False, False, True]


def test_next_actual_success_starts_a_new_deadline(manager, clock):
    track = manager.assign([BOX])[0]
    manager.record_failure(track)
    manager.record_success(track)
    assert track.failures == track.quality_observations == track.cooldown_frames == 0

    clock.now = 1.25
    assert [manager.observe_quality(track) for _ in range(3)] == [False, False, True]
    manager.record_success(track)

    assert track.success_recheck_at == 2.25
    assert track.quality_observations == 0
    assert not manager.observe_quality(track)


def test_disabling_success_recheck_preserves_legacy_quality_and_misses(clock):
    manager = TrackManager(success_recheck_seconds=0, monotonic=clock)
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    assert track.success_recheck_at is None
    assert not manager.observe_quality(track)

    manager.reject_quality(track)
    manager.assign([])
    assert manager.assign([(50.0, 0.0, 100.0, 100.0)])[0] is track
    assert track.quality_observations == 1
    assert not manager.observe_quality(track)
    assert manager.observe_quality(track)


def test_one_missed_frame_invalidates_success_even_if_track_survives(manager):
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    manager.observe_quality(track)

    manager.assign([])

    assert track.missed_frames == 1
    assert track.success_recheck_at is None
    assert track.quality_observations == 0
    assert manager.assign([BOX])[0] is track
    assert [manager.observe_quality(track) for _ in range(3)] == [False, False, True]


@pytest.mark.parametrize("after_expiry", [False, True])
def test_low_quality_invalidates_success_and_quality_count(manager, clock, after_expiry):
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    for _ in range(3):
        manager.observe_quality(track)
    if after_expiry:
        clock.now = 2.0

    manager.reject_quality(track)

    assert track.success_recheck_at is None
    assert track.quality_observations == 0
    assert [manager.observe_quality(track) for _ in range(3)] == [False, False, True]


@pytest.mark.parametrize("failed", [False, True])
def test_low_quality_preserves_legacy_state_without_prior_success(manager, failed):
    track = manager.assign([BOX])[0]
    if failed:
        manager.record_failure(track)
    manager.observe_quality(track)
    previous = (track.failures, track.quality_observations, track.cooldown_frames)

    manager.reject_quality(track)
    manager.assign([])

    assert (track.failures, track.quality_observations, track.cooldown_frames) == previous


@pytest.mark.parametrize("after_expiry", [False, True])
def test_abrupt_movement_invalidates_success_without_replacing_track(manager, clock, after_expiry):
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    for _ in range(3):
        manager.observe_quality(track)
    if after_expiry:
        clock.now = 2.0

    assert manager.assign([(50.0, 0.0, 100.0, 100.0)])[0] is track

    assert track.success_recheck_at is None
    assert track.quality_observations == 0
    assert not manager.observe_quality(track)


def test_current_face_ambiguous_between_previous_tracks_invalidates_success(manager):
    tracks = manager.assign([BOX, (20.0, 0.0, 100.0, 100.0)])
    for track in tracks:
        manager.record_success(track)
        manager.observe_quality(track)

    matched = manager.assign([(10.0, 0.0, 100.0, 100.0)])[0]

    assert matched in tracks
    assert all(track.success_recheck_at is None for track in tracks)
    assert all(track.quality_observations == 0 for track in tracks)


def test_previous_track_ambiguous_between_current_faces_invalidates_success(manager):
    track = manager.assign([BOX])[0]
    manager.record_success(track)
    manager.observe_quality(track)

    matches = manager.assign([BOX, (10.0, 0.0, 100.0, 100.0)])

    assert matches[0] is track
    assert matches[1] is not track
    assert all(match.success_recheck_at is None for match in matches)
    assert track.quality_observations == 0


def test_greedy_second_choice_cannot_reuse_success_from_a_nonbest_track(manager):
    tracks = manager.assign([BOX, (20.0, 0.0, 100.0, 100.0)])
    for track in tracks:
        manager.record_success(track)
        manager.observe_quality(track)

    matches = manager.assign([BOX, (1.0, 0.0, 100.0, 100.0)])

    assert matches == tracks
    assert all(track.success_recheck_at is None for track in tracks)
    assert all(track.quality_observations == 0 for track in tracks)


def test_new_face_is_eligible_independently_of_successful_face(manager):
    known = manager.assign([BOX])[0]
    manager.record_success(known)
    matches = manager.assign([BOX, DISTANT_BOX])

    assert matches[0] is known
    assert not manager.observe_quality(known)
    assert matches[1].success_recheck_at is None
    assert [manager.observe_quality(matches[1]) for _ in range(3)] == [False, False, True]


def test_multiple_successful_faces_keep_independent_deadlines_and_tracking(manager, clock):
    first, second = manager.assign([BOX, DISTANT_BOX])
    manager.record_success(first)
    clock.now = 0.25
    manager.record_success(second)

    assert manager.assign([DISTANT_BOX, BOX]) == [second, first]
    for _ in range(3):
        assert not manager.observe_quality(first)
        assert not manager.observe_quality(second)

    clock.now = 1.0
    assert manager.observe_quality(first)
    assert not manager.observe_quality(second)
    assert second.success_recheck_at == 1.25


def test_failure_clears_success_and_keeps_five_good_frames_before_three_observations(manager):
    track = manager.assign([BOX])[0]
    manager.record_success(track)

    assert manager.record_failure(track) == 1
    assert track.success_recheck_at is None
    assert [manager.observe_quality(track) for _ in range(8)] == [False] * 7 + [True]
    assert manager.record_failure(track) == 2


def test_reset_and_new_tracks_do_not_inherit_success(manager):
    old = manager.assign([BOX])[0]
    manager.record_success(old)
    manager.reset()

    new = manager.assign([BOX])[0]

    assert new.track_id != old.track_id
    assert new.success_recheck_at is None
    assert [manager.observe_quality(new) for _ in range(3)] == [False, False, True]


def test_out_of_range_face_creates_new_track_without_success(manager):
    old = manager.assign([BOX])[0]
    manager.record_success(old)

    new = manager.assign([DISTANT_BOX])[0]

    assert new is not old
    assert old.success_recheck_at is None
    assert new.success_recheck_at is None


@pytest.mark.parametrize("seconds", [-0.1, 1.1, float("inf"), float("-inf"), float("nan")])
def test_invalid_recheck_settings_are_rejected(seconds):
    with pytest.raises(ValueError, match="success_recheck_seconds"):
        TrackManager(success_recheck_seconds=seconds)
