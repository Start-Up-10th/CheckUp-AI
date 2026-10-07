# AI 배포 실패 분석 — 런타임 의존성 정리 — 2026-10-07

실패 실행: [Deploy AI run 37610526303](https://github.com/Start-Up-10th/CheckUp-AI/actions/runs/37610526303),
배포 job ID `112756409579`. 같은 main 커밋의 `AI CI`와 `Harness validation`은 통과했고,
`Deploy to school server`의 Docker 이미지 export에서 실패했다.

## 원인

서버의 루트 디스크는 20GB 중 15GB 사용, 5.2GB 여유였다. 이미지 export가
`/opt/venv/.../jaxlib/libjax_common.so`를 기록하던 중 `no space left on device`가 발생했다.
기존 workflow의 정수 GB 여유 공간 검사는 이 5.2GB 상태에서 공간 정리를 시작하지 않았다.
따라서 이번 실패는 얼굴 추론 코드 실행 오류가 아니라 이미지 빌드 중 디스크 고갈이다.

`mediapipe==0.10.21`의 패키지 메타데이터는 서비스에서 쓰지 않는 JAX/JAXlib, 오디오,
contrib OpenCV 의존성도 요구한다. AI 서비스는 MediaPipe Tasks의 FaceLandmarker만 사용하고,
`cv2`는 명시적으로 고정한 `opencv-python-headless`에서 제공한다. MediaPipe 패키지 초기화는
`matplotlib`을 import하므로 이미지에서 유지한다.

## 수정

Dockerfile의 `uv sync`에서 JAX/JAXlib 및 그 전용 의존성(`ml-dtypes`, `opt-einsum`, `scipy`),
오디오 의존성(`sounddevice`, `cffi`, `pycparser`), 중복 `opencv-contrib-python`을 설치하지 않도록 했다.
고정 lockfile은 그대로 유지하고, 개발 환경에는 기존 `pyproject.toml` 의존성을 유지한다.
실패를 완화하기 위해 앞서 추가했던 workflow 변경은 최종 변경에서 되돌렸다. 이번 수정은
실패 로그에서 마지막으로 쓰다 실패한 `libjax_common.so`를 런타임 이미지에서 제거한다.

## 검증과 남은 확인

- 생략 대상 의존성 import를 차단한 로컬 환경에서 실제 `InferenceModels` 초기화와 MediaPipe
  FaceLandmarker 실행을 확인했다. OpenVINO 초기화도 통과했고, 검은 합성 프레임에서 얼굴 0개를 반환했다.
- `matplotlib`은 차단하지 않았으며, 서비스 경로의 import에 필요함을 확인했다.
- Docker Desktop Engine 29.8.0에서 `docker build --progress=plain -t checkup-ai-runtime-deps:local .` 통과.
  결과 이미지 크기는 1,514,241,968 bytes(약 1.41 GiB)였다.
- 빌드된 Linux 컨테이너에서 `jax`, `jaxlib`, `scipy`, `sounddevice`가 설치되지 않았고,
  `matplotlib`과 `cv2`는 설치된 상태임을 확인했다. 실제 MediaPipe FaceLandmarker와 OpenVINO
  초기화 및 640×480 합성 빈 프레임 추론이 통과해 얼굴 0개를 반환했다.
- 운영 서버에 다시 배포하지 않았다. 서버 디스크에 여유 공간이 여전히 부족하면 이미지 크기 감축만으로
  빌드 성공을 보장하지 않으므로 새 배포 로그로 확인해야 한다.
- 실제 배포 workflow 파일은 변경하지 않았다.
