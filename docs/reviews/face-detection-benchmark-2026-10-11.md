# 얼굴 프레임 지연시간 및 실행 모드 비교 — 2026-10-11

이번 측정은 현재 AI 프레임 API와 MediaPipe `IMAGE`/`VIDEO` 모드를 비교한다.
실학생 데이터 대신 코드로 그린 비사진 합성 프레임과 무작위 256차원 벡터만 사용했다.
프레임·랜드마크·학생 ID는 파일에 저장하거나 출력하지 않았다.

## 프레임 API 단계 지연시간

[`face_api_synthetic.py`](../../benchmarks/face_api_synthetic.py)는 실제 FastAPI 라우트,
MediaPipe 태스크, OpenVINO 임베더를 구동하고 기존 `face_frame_timing_ms` 로그를 집계한다.
60개 합성 JPEG 요청 중 10개를 워밍업으로 제외했다. 비교 갤러리는 합성 학생 50명,
학생당 벡터 20개였다. 로컬 환경은 Windows, Python 3.12.0, OpenCV 4.11.0,
MediaPipe 0.10.21, OpenVINO 2026.3.1, 논리 CPU 16개다.

| 단계 | 표본 수 | 중앙값 | p95 |
| --- | ---: | ---: | ---: |
| read | 50 | 0.202 ms | 0.272 ms |
| decode | 50 | 0.437 ms | 0.567 ms |
| detect | 50 | 11.319 ms | 11.805 ms |
| embed | 7 | 2.858 ms | 3.398 ms |
| match | 7 | 0.211 ms | 0.222 ms |
| cleanup | 50 | 0.045 ms | 0.053 ms |
| total | 50 | 12.164 ms | 15.363 ms |

측정 요청마다 합성 얼굴 1개가 검출됐다. 품질·쿨다운 조건을 통과해 임베딩을 시도한
요청은 7개다. 따라서 embed/match 표본은 7개뿐이고, 실제 카메라·네트워크·서버 운영
환경의 지연시간으로 해석하면 안 된다. 이 합성 API 실행에서는 detect가 가장 큰 단계였다.

## IMAGE와 VIDEO 비교

[`face_detection_modes.py`](../../benchmarks/face_detection_modes.py)는 같은 합성 프레임을
두 독립 태스크에 전달한다. 첫 비교는 120프레임 중 워밍업 10개, 재비교는 600프레임 중
워밍업 30개를 제외했다. 표의 시간은 MediaPipe 검출 호출만 측정한다.

| 실행 | 모드 | 표본 | 중앙값 | p95 |
| --- | --- | ---: | ---: | ---: |
| 120프레임 | IMAGE | 110 | 9.340 ms | 10.091 ms |
| 120프레임 | VIDEO | 110 | 9.283 ms | 10.205 ms |
| 600프레임 | IMAGE | 570 | 9.197 ms | 10.098 ms |
| 600프레임 | VIDEO | 570 | 9.143 ms | 10.078 ms |

600프레임 실행에서 VIDEO 중앙값은 약 0.6%, p95는 약 0.2% 낮았다. 짧은 실행에서는
p95가 반대로 VIDEO에서 높았다. 합성 입력에서 얼굴 수 불일치 프레임은 없었고 좌표도
같았지만, 이는 실제 영상의 검출 품질이나 오인식률을 검증한 결과가 아니다.

## 결정과 제한

이 결과만으로 서비스 기본 실행 모드를 바꾸지 않는다. 측정된 차이가 작고 실행마다
방향이 일정하지 않다. 또한 MediaPipe VIDEO 모드는 프레임마다 단조 증가하는 타임스탬프를
요구한다. 세션 사이 추적 상태가 섞이지 않게 하려면 현재 공유 Landmarker를 세션별 상태로
바꾸고 세션 생성·종료·동시 요청을 함께 다뤄야 한다. [FaceLandmarker 공식 API 문서](https://ai.google.dev/edge/api/mediapipe/python/mp/tasks/vision/FaceLandmarker)
는 `detect_for_video`와 단조 타임스탬프 조건을 설명한다.

AI 서비스에는 `face_frame_timing_ms` DEBUG 단계 로거가 이미 있으나 이번 실행에는 실제
운영 요청 로그가 제공되지 않았다. 실제 승인된 테스트 영상이 있으면 아래 명령으로 같은
두 모드를 비교할 수 있다. 스크립트는 경로·이미지·랜드마크를 출력하지 않는다.

```powershell
.\.venv\Scripts\python.exe benchmarks\face_detection_modes.py --video "C:\path\to\test.mp4"
```

현재 확정한 것은 합성 입력에서 detect가 큰 단계라는 진단뿐이다. VIDEO 전환은 보류한다.
다음 최적화 후보는 얼굴 크기와 검출 결과를 함께 비교하는 입력 해상도 단계별 측정이다.
256차원 임베딩, 벡터 형식, 임계값, 인식 로직은 변경하지 않았다.
