import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

import face_api
from face_api import create_app
from face_config import Settings
from face_models import FaceObservation, ModelMetadata
from face_pipeline import CandidateGallery

SESSION = "session-private"
AUTH = {"Authorization": "Bearer synthetic-service-token"}


class MetadataModels:
    metadata = ModelMetadata()

    def __init__(self, vector_indices=(0,)):
        self.vector_indices = vector_indices
        self.brightness = [100] * len(vector_indices)
        self.images = []
        self.probes = []
        self.fail_detection = False
        self.fail_embedding = False

    def detect_faces(self, image):
        self.images.append(image)
        if self.fail_detection:
            raise RuntimeError("synthetic detection failure")
        return [
            FaceObservation(
                (0.1 + index * 0.4, 0.1, 0.2, 0.2),
                ((12.34567, 23.45678),),
                None,
                self.brightness[index],
                100,
                "frontal",
            )
            for index in range(len(self.vector_indices))
        ]

    def embed_face(self, image, observation):
        assert image.any()
        if self.fail_embedding:
            raise RuntimeError("synthetic embedding failure")
        index = round((observation.bbox[0] - 0.1) / 0.4)
        vector = np.zeros(256, dtype=np.float32)
        vector[self.vector_indices[index]] = 1
        self.probes.append(vector)
        return vector

    def close(self):
        pass


def settings(**overrides):
    values = {
        "landmarker_path": Path("missing-landmarker.task"),
        "embedding_model_path": Path("missing-embedding.xml"),
        "service_token": "synthetic-service-token",
        "match_threshold": 0.5,
        "match_margin": 0.1,
    }
    return Settings(**(values | overrides))


def payload(student_id="student-private", vector_index=0):
    vector = [0.0] * 256
    vector[vector_index] = 1.0
    return {
        "model": ModelMetadata().__dict__,
        "candidates": [{"student_id": student_id, "vectors": [vector]}],
    }


def encoded_image():
    _, encoded = cv2.imencode(".jpg", np.full((64, 64, 3), 127, dtype=np.uint8))
    return encoded.tobytes()


def send_frame(client, image):
    return client.post(
        f"/internal/v1/face/sessions/{SESSION}/frames",
        headers={"Content-Type": "image/jpeg", "X-Frame-Id": "frame-private"},
        content=image,
    )


def install_session(client):
    response = client.put(f"/internal/v1/face/sessions/{SESSION}", json=payload())
    assert response.status_code == 200


def test_only_eligible_third_good_observation_embeds_and_buffers_are_cleared():
    models = MetadataModels()
    app = create_app(settings(), models)
    image = encoded_image()
    with TestClient(app, headers=AUTH) as client:
        install_session(client)
        for expected_count in (1, 2):
            face = send_frame(client, image).json()["faces"][0]
            assert face["recognition"]["status"] == "NOT_ATTEMPTED"
            assert not models.probes
            assert app.state.sessions[SESSION].tracker.tracks[0].quality_observations == expected_count
        face = send_frame(client, image).json()["faces"][0]
        assert face["recognition"]["status"] == "KNOWN"
        assert face["recognition"]["studentId"] == "student-private"
        assert len(models.probes) == 1
        assert not models.probes[0].any()
        assert all(not frame.any() for frame in models.images)
        assert app.state.sessions[SESSION].tracker.tracks[0].quality_observations == 0


def test_poor_frames_do_not_advance_quality_or_decrement_failure_cooldown():
    models = MetadataModels(vector_indices=(1,))
    app = create_app(settings(), models)
    image = encoded_image()
    with TestClient(app, headers=AUTH) as client:
        install_session(client)
        send_frame(client, image)
        track = app.state.sessions[SESSION].tracker.tracks[0]
        assert track.quality_observations == 1
        models.brightness[0] = 20
        for _ in range(2):
            face = send_frame(client, image).json()["faces"][0]
            assert face["recognition"]["status"] == "NOT_ATTEMPTED"
            assert face["quality"]["issues"] == ["LOW_LIGHT"]
            assert track.quality_observations == 1
        assert not models.probes
        models.brightness[0] = 100
        send_frame(client, image)
        assert track.quality_observations == 2
        assert send_frame(client, image).json()["faces"][0]["attempts"] == 1
        assert track.quality_observations == 0 and track.cooldown_frames == 5
        models.brightness[0] = 20
        send_frame(client, image)
        assert track.cooldown_frames == 5
        assert len(models.probes) == 1
        models.brightness[0] = 100
        send_frame(client, image)
        assert track.cooldown_frames == 4


def test_missing_thresholds_advance_quality_counter_without_embedding():
    models = MetadataModels()
    app = create_app(settings(match_threshold=None, match_margin=None), models)
    with TestClient(app, headers=AUTH) as client:
        install_session(client)
        for _ in range(4):
            face = send_frame(client, encoded_image()).json()["faces"][0]
            assert face["recognition"]["status"] == "NOT_ATTEMPTED"
            assert face["attempts"] == 0
        assert not models.probes
        assert app.state.sessions[SESSION].tracker.tracks[0].quality_observations == 4


def test_failed_attempts_follow_five_quality_frame_cooldown_and_fourth_failure_qr():
    models = MetadataModels(vector_indices=(1,))
    app = create_app(settings(), models)
    image = encoded_image()
    with TestClient(app, headers=AUTH) as client:
        install_session(client)
        for failure in range(1, 5):
            if failure > 1:
                for remaining in range(4, -1, -1):
                    face = send_frame(client, image).json()["faces"][0]
                    assert face["recognition"]["status"] == "NOT_ATTEMPTED"
                    assert face["attempts"] == failure - 1
                    assert len(models.probes) == failure - 1
                    assert app.state.sessions[SESSION].tracker.tracks[0].cooldown_frames == remaining
            for _ in range(2):
                assert send_frame(client, image).json()["faces"][0]["recognition"]["status"] == "NOT_ATTEMPTED"
            face = send_frame(client, image).json()["faces"][0]
            assert face["recognition"]["status"] == "UNKNOWN"
            assert face["recognition"]["studentId"] is None
            assert face["attempts"] == failure
            assert face["qrRecommended"] is (failure == 4)
            assert len(models.probes) == failure
            assert app.state.sessions[SESSION].tracker.tracks[0].quality_observations == 0
        models.vector_indices = (0,)
        for _ in range(8):
            face = send_frame(client, image).json()["faces"][0]
        assert face["recognition"]["status"] == "KNOWN"
        assert face["attempts"] == 0 and not face["qrRecommended"]
        track = app.state.sessions[SESSION].tracker.tracks[0]
        assert track.quality_observations == 0 and track.cooldown_frames == 0


def test_multiple_faces_keep_attempts_and_embedding_gates_isolated():
    models = MetadataModels(vector_indices=(0, 1))
    app = create_app(settings(), models)
    image = encoded_image()
    with TestClient(app, headers=AUTH) as client:
        install_session(client)
        for _ in range(3):
            faces = send_frame(client, image).json()["faces"]
        assert faces[0]["recognition"]["status"] == "KNOWN"
        assert faces[0]["attempts"] == 0
        assert faces[1]["recognition"]["status"] == "UNKNOWN"
        assert faces[1]["attempts"] == 1
        assert faces[0]["trackId"] != faces[1]["trackId"]
        for _ in range(3):
            faces = send_frame(client, image).json()["faces"]
        assert faces[0]["recognition"]["status"] == "KNOWN"
        assert faces[1]["recognition"]["status"] == "NOT_ATTEMPTED"
        assert faces[1]["attempts"] == 1
        assert len(models.probes) == 3
        assert all(not probe.any() for probe in models.probes)


@pytest.mark.parametrize("failure", ["detect", "embed", "match"])
def test_inference_errors_clear_image_and_any_returned_probe(monkeypatch, failure):
    models = MetadataModels()
    app = create_app(settings(), models)
    image = encoded_image()
    with TestClient(app, headers=AUTH, raise_server_exceptions=False) as client:
        install_session(client)
        for _ in range(2):
            assert send_frame(client, image).status_code == 200
        models.fail_detection = failure == "detect"
        models.fail_embedding = failure == "embed"
        if failure == "match":
            def fail_match(*_args):
                raise RuntimeError("synthetic match failure")
            monkeypatch.setattr(CandidateGallery, "match", fail_match)
        response = send_frame(client, image)
        assert response.status_code == 500
        assert response.json()["detail"]["code"] == "INTERNAL_ERROR"
        assert all(not frame.any() for frame in models.images)
        assert all(not probe.any() for probe in models.probes)
        assert len(models.probes) == (1 if failure == "match" else 0)
        assert app.state.sessions[SESSION].in_flight == 0


def test_debug_timings_contain_only_fixed_stage_durations_counts_and_outcome(caplog):
    models = MetadataModels()
    app = create_app(settings(), models)
    with caplog.at_level(logging.DEBUG, logger="face_api"):
        with TestClient(app, headers=AUTH) as client:
            install_session(client)
            for _ in range(3):
                assert send_frame(client, encoded_image()).status_code == 200
    records = [record for record in caplog.records if record.name == "face_api"]
    assert len(records) == 3
    stages = {"read", "decode", "detect", "embed", "match", "cleanup", "total"}
    for index, record in enumerate(records):
        assert record.msg == "face_frame_timing_ms %s"
        fields = record.args
        assert set(fields) <= stages | {"faces", "embeddings", "outcome"}
        assert {"read", "decode", "detect", "cleanup", "total"} <= set(fields)
        assert fields["faces"] == 1
        assert fields["embeddings"] == (1 if index == 2 else 0)
        assert fields["outcome"] == "success"
        for stage in stages & fields.keys():
            assert isinstance(fields[stage], float) and np.isfinite(fields[stage])
            assert fields[stage] >= 0
        rendered = record.getMessage()
        for private_value in (SESSION, "student-private", "frame-private", "12.34567", "23.45678"):
            assert private_value not in rendered
        assert "score" not in rendered and "margin" not in rendered


@asynccontextmanager
async def async_client(app):
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=AUTH
        ) as client:
            yield client


async def async_frame(client, content):
    return await client.post(
        f"/internal/v1/face/sessions/{SESSION}/frames",
        headers={"Content-Type": "image/jpeg"}, content=content,
    )


@pytest.mark.parametrize("operation", ["replace", "delete"])
def test_in_flight_session_gallery_and_tracker_survive_until_request_release(operation):
    async def scenario():
        models = MetadataModels()
        app = create_app(settings(), models)
        image = encoded_image()
        async with async_client(app) as client:
            assert (await client.put(f"/internal/v1/face/sessions/{SESSION}", json=payload())).status_code == 200
            for _ in range(2):
                assert (await async_frame(client, image)).status_code == 200
            old = app.state.sessions[SESSION]
            old_track = old.tracker.tracks[0]
            entered, unblock = asyncio.Event(), asyncio.Event()

            async def streamed_body():
                yield image[:10]
                entered.set()
                await unblock.wait()
                yield image[10:]

            task = asyncio.create_task(async_frame(client, streamed_body()))
            try:
                await asyncio.wait_for(entered.wait(), timeout=3)
                assert old.in_flight == 1
                if operation == "replace":
                    response = await client.put(
                        f"/internal/v1/face/sessions/{SESSION}",
                        json=payload(student_id="replacement-student"),
                    )
                    replacement = app.state.sessions[SESSION]
                    assert replacement is not old
                else:
                    response = await client.delete(f"/internal/v1/face/sessions/{SESSION}")
                assert response.status_code == 200
                assert old.closing and not old.gallery.cleared and old.gallery.vectors.any()
                assert old.tracker.tracks == [old_track] and old_track.quality_observations == 2
                assert id(old) in app.state.retired_sessions
                if operation == "delete":
                    assert (await async_frame(client, image)).status_code == 404
                unblock.set()
                result = await asyncio.wait_for(task, timeout=3)
                assert result.status_code == 200
                assert result.json()["faces"][0]["recognition"]["studentId"] == "student-private"
                assert old.in_flight == 0 and old.gallery.cleared and not old.gallery.vectors.any()
                assert not old.tracker.tracks and id(old) not in app.state.retired_sessions
                if operation == "replace":
                    assert app.state.sessions[SESSION] is replacement
                    assert not replacement.gallery.cleared and replacement.gallery.vectors.any()
                    for _ in range(3):
                        result = await async_frame(client, image)
                    assert result.json()["faces"][0]["recognition"]["studentId"] == "replacement-student"
                else:
                    assert SESSION not in app.state.sessions
            finally:
                unblock.set()
                if not task.done():
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
    asyncio.run(scenario())


def test_cancelled_upload_scrubs_partial_body_and_releases_session(monkeypatch):
    buffers = []

    class RetainedBuffer(bytearray):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            buffers.append(self)

    monkeypatch.setattr(face_api, "bytearray", RetainedBuffer, raising=False)

    async def scenario():
        models = MetadataModels()
        app = create_app(settings(), models)
        async with async_client(app) as client:
            assert (await client.put(f"/internal/v1/face/sessions/{SESSION}", json=payload())).status_code == 200
            session = app.state.sessions[SESSION]
            entered = asyncio.Event()

            async def streamed_body():
                yield b"synthetic-partial-frame"
                entered.set()
                await asyncio.Event().wait()

            task = asyncio.create_task(async_frame(client, streamed_body()))
            await asyncio.wait_for(entered.wait(), timeout=3)
            assert session.in_flight == 1 and buffers and any(buffers[0])
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert session.in_flight == 0
            assert not session.gallery.cleared and session.gallery.vectors.any()
            assert not models.images and not models.probes
            assert all(not any(buffer) for buffer in buffers)
    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["duplicate", "zero"])
def test_rejected_session_payload_preserves_current_gallery_and_scrubs_partial_vectors(monkeypatch, invalid):
    models = MetadataModels()
    app = create_app(settings(), models)
    temporary = []
    real_normalize = face_api.normalize_vector

    def capture_normalize(vector):
        result = real_normalize(vector)
        temporary.append(result)
        return result

    with TestClient(app, headers=AUTH) as client:
        install_session(client)
        session = app.state.sessions[SESSION]
        monkeypatch.setattr(face_api, "normalize_vector", capture_normalize)
        invalid_payload = payload()
        if invalid == "duplicate":
            invalid_payload["candidates"].append(invalid_payload["candidates"][0].copy())
        else:
            invalid_payload["candidates"][0]["vectors"].append([0.0] * 256)
        response = client.put(f"/internal/v1/face/sessions/{SESSION}", json=invalid_payload)
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "MODEL_MISMATCH"
        assert app.state.sessions[SESSION] is session
        assert not session.closing and not session.gallery.cleared and session.gallery.vectors.any()
        assert temporary and all(not vector.any() for vector in temporary)


@pytest.mark.parametrize("replace_while_busy", [False, True], ids=["current", "retired"])
def test_lifespan_shutdown_waits_for_paused_upload_before_scrubbing_and_closing_runtime(
    monkeypatch, replace_while_busy
):
    models = MetadataModels()
    runtime_closed = []
    monkeypatch.setattr(models, "close", lambda: runtime_closed.append(True))
    monkeypatch.setattr(face_api, "InferenceModels", lambda *_args: models)
    # Existing harmless files enable owned-runtime initialization without loading a model.
    app = create_app(settings(landmarker_path=Path(__file__), embedding_model_path=Path(__file__)))

    async def scenario():
        lifespan = app.router.lifespan_context(app)
        await lifespan.__aenter__()
        shutdown_task = None
        upload_task = None
        entered, unblock = asyncio.Event(), asyncio.Event()
        image = encoded_image()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test", headers=AUTH
        ) as client:
            try:
                response = await client.put(f"/internal/v1/face/sessions/{SESSION}", json=payload())
                assert response.status_code == 200
                for _ in range(2):
                    assert (await async_frame(client, image)).status_code == 200
                busy = app.state.sessions[SESSION]
                busy_track = busy.tracker.tracks[0]

                async def streamed_body():
                    yield image[:10]
                    entered.set()
                    await unblock.wait()
                    yield image[10:]

                upload_task = asyncio.create_task(async_frame(client, streamed_body()))
                await asyncio.wait_for(entered.wait(), timeout=3)
                assert busy.in_flight == 1
                replacement = None
                if replace_while_busy:
                    response = await client.put(
                        f"/internal/v1/face/sessions/{SESSION}",
                        json=payload(student_id="replacement-student"),
                    )
                    assert response.status_code == 200
                    replacement = app.state.sessions[SESSION]
                    assert replacement is not busy and id(busy) in app.state.retired_sessions

                shutdown_task = asyncio.create_task(lifespan.__aexit__(None, None, None))

                async def wait_for_shutdown_retirement():
                    while app.state.sessions or not busy.closing:
                        await asyncio.sleep(0)

                await asyncio.wait_for(wait_for_shutdown_retirement(), timeout=3)
                assert not shutdown_task.done()
                assert not runtime_closed
                assert busy.in_flight == 1 and not busy.gallery.cleared
                assert busy.gallery.vectors.any()
                assert busy.tracker.tracks == [busy_track]
                assert busy_track.quality_observations == 2
                assert id(busy) in app.state.retired_sessions
                if replacement is not None:
                    assert replacement.gallery.cleared

                unblock.set()
                response = await asyncio.wait_for(upload_task, timeout=3)
                assert response.status_code == 200
                assert response.json()["faces"][0]["recognition"]["studentId"] == "student-private"
                await asyncio.wait_for(shutdown_task, timeout=3)
                assert runtime_closed == [True]
                assert busy.in_flight == 0 and busy.gallery.cleared
                assert not busy.gallery.vectors.any() and not busy.gallery.counts.any()
                assert not busy.tracker.tracks
                assert not app.state.sessions and not app.state.retired_sessions
                assert all(not frame.any() for frame in models.images)
                assert all(not probe.any() for probe in models.probes)
            finally:
                unblock.set()
                if upload_task is not None and not upload_task.done():
                    upload_task.cancel()
                    await asyncio.gather(upload_task, return_exceptions=True)
                if shutdown_task is None:
                    await lifespan.__aexit__(None, None, None)
                elif not shutdown_task.done():
                    await asyncio.wait_for(shutdown_task, timeout=3)

    asyncio.run(scenario())
