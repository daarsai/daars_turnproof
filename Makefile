.PHONY: setup keys test lint smoke-sam smoke-spark smoke-asr frames serve demo replay verify tamper metrics

# SYS_PY is used once, to create the venv; everything else runs inside the venv.
SYS_PY ?= python3
VENV_PY = .venv/bin/python
PY ?= $(VENV_PY)

setup:
	$(SYS_PY) -m venv .venv && . .venv/bin/activate && pip install -U pip && pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	$(MAKE) keys

keys:
	.venv/bin/python scripts/gen_keys.py

lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .

test:
	$(PY) -m pytest -q

# ---- Day 0 smoke tests (need MODEL_API_KEY in .env) ----
frames:            # make frames CLIP=clips/clip1.mp4  -> data/frames/clip1/*.png (1 fps)
	$(PY) scripts/extract_frames.py $(CLIP) --fps 1

smoke-sam:         # make smoke-sam IMG=data/frames/clip1/f0000.png PROMPT="belt loader"
	$(PY) scripts/smoke_sam.py image $(IMG) "$(PROMPT)"

smoke-sam-video:   # make smoke-sam-video CLIP=clips/clip1_10s.mp4 PROMPT="belt loader"
	$(PY) scripts/smoke_sam.py video $(CLIP) "$(PROMPT)"

smoke-spark:       # make smoke-spark IMG="data/frames/clip1/f0010.png data/frames/clip1/f0020.png"
	$(PY) scripts/smoke_spark.py $(IMG)

smoke-asr:         # make smoke-asr WAV=fixtures/note.wav
	$(PY) scripts/smoke_asr.py $(WAV)

# ---- pipeline (Day 1+) ----
demo:              # make demo CLIP=clips/clip1
	$(PY) -m turnproof.cli run $(CLIP)

replay:            # make replay RUN=<run_id>   re-run that run's clip from the cache (no API spend)
	$(PY) -m turnproof.cli replay $(RUN)

serve:             # review console -> http://localhost:8080
	$(VENV_PY) -m uvicorn turnproof.review.app:app --host 127.0.0.1 --port 8080

verify:            # make verify PACKET=data/runs/<run>/packets/<id>.json
	$(PY) verify_packet.py $(PACKET)

tamper:            # make tamper PACKET=...
	$(PY) scripts/tamper_demo.py $(PACKET)

metrics:           # make metrics RUN=<run_id>
	cat data/runs/$(RUN)/run_metrics.json
