"""Narration with Kokoro-82M (Apache-2.0) through kokoro-onnx.

usage: python tts_kokoro.py JOB.json MODEL_DIR
  JOB.json   {"voice": "af_heart", "speed": 1.0, "lines": {id: text}, "out": dir}
  MODEL_DIR  holds kokoro-v1.0.onnx and voices-v1.0.bin
Writes <out>/<id>.raw.wav (mono, model sample rate) for every line.
"""
import json, os, shutil, sys, wave
import numpy as np
import espeakng_loader
from kokoro_onnx import Kokoro, EspeakConfig

job = json.load(open(sys.argv[1])); md = sys.argv[2]
# espeak-ng silently ignores a data path longer than ~160 characters (and the
# macOS wheel then falls back to its build machine's path), so keep a copy of
# the data beside the model, whose path is short.
ed = os.path.join(md, "espeak-ng-data")
if not os.path.isdir(ed): shutil.copytree(espeakng_loader.get_data_path(), ed)
assert len(ed) < 150, f"move MODEL_DIR to a shorter path: {ed}"
k = Kokoro(os.path.join(md, "kokoro-v1.0.onnx"), os.path.join(md, "voices-v1.0.bin"),
           espeak_config=EspeakConfig(data_path=ed))
for key, text in job["lines"].items():
    samples, sr = k.create(text, voice=job["voice"], speed=job["speed"], lang="en-us")
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    with wave.open(os.path.join(job["out"], key + ".raw.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    print(key, f"{len(samples) / sr:.2f}s", flush=True)
