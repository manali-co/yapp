"""Who is talking? A local speaker embedding compared with the user's enrolled voiceprint.

Model: WeSpeaker ResNet34 (VoxCeleb, ONNX, 26 MB) from Hugging Face, run with onnxruntime,
fed Kaldi-style 80-bin log-mel filterbanks computed here in numpy (no torchaudio). Used for
spoken approvals only: a "yes" counts when it sounds like the enrolled user.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np

Embedder = Callable[[np.ndarray], np.ndarray | None]  # 16 kHz float32 -> unit vector

HF_REPO = "Wespeaker/wespeaker-voxceleb-resnet34-LM"
HF_FILE = "voxceleb_resnet34_LM.onnx"
HF_REVISION = "f0c48c298fd835726c27956a5d617bad7115627e"  # pinned: the file we validated
SAMPLE_RATE = 16_000
MIN_SECONDS = 1.0
DEFAULT_PATH = Path.home() / ".yapp" / "voice.npy"


def _mel(f: np.ndarray) -> np.ndarray:
    return 1127.0 * np.log1p(f / 700.0)


def mel_filters(n_bins: int = 80, n_fft: int = 512, sr: int = SAMPLE_RATE) -> np.ndarray:
    """Kaldi-style triangular mel filterbank over the FFT bins (excluding Nyquist)."""
    low, high = 20.0, sr / 2.0
    edges = np.linspace(_mel(np.array(low)), _mel(np.array(high)), n_bins + 2)
    freqs = np.arange(n_fft // 2) * sr / n_fft
    mels = _mel(freqs)
    out = np.zeros((n_bins, n_fft // 2), dtype=np.float32)
    for b in range(n_bins):
        left, centre, right = edges[b], edges[b + 1], edges[b + 2]
        up = (mels - left) / (centre - left)
        down = (right - mels) / (right - centre)
        out[b] = np.clip(np.minimum(up, down), 0.0, None)
    return out


_FILTERS: dict[tuple[int, int], np.ndarray] = {}


def fbank(samples: np.ndarray, n_bins: int = 80) -> np.ndarray:
    """(frames, 80) log-mel features: 25 ms Hamming frames every 10 ms, mean-normalised."""
    x = np.asarray(samples, dtype=np.float32).ravel() * 32768.0  # Kaldi works on int16 scale
    frame, hop, n_fft = 400, 160, 512
    if x.size < frame:
        return np.zeros((0, n_bins), dtype=np.float32)
    n = 1 + (x.size - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)  # remove DC offset
    frames = np.concatenate([frames[:, :1], frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    frames = frames * np.hamming(frame).astype(np.float32)
    power = np.abs(np.fft.rfft(frames, n=n_fft)[:, : n_fft // 2]) ** 2
    key = (n_bins, n_fft)
    if key not in _FILTERS:
        _FILTERS[key] = mel_filters(n_bins, n_fft)
    feats = np.log(np.maximum(power @ _FILTERS[key].T, np.finfo(np.float32).eps))
    normalised: np.ndarray = (feats - feats.mean(axis=0, keepdims=True)).astype(np.float32)
    return normalised


def onnx_embedder(model_path: str | None = None) -> Embedder:
    """Lazy WeSpeaker session; the model file is fetched from Hugging Face on first use."""
    import onnxruntime as ort

    if model_path is None:
        from huggingface_hub import hf_hub_download

        model_path = hf_hub_download(HF_REPO, HF_FILE, revision=HF_REVISION)
    session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name

    def embed(samples: np.ndarray) -> np.ndarray | None:
        feats = fbank(samples)
        if feats.shape[0] < 50:  # under half a second of frames
            return None
        out = session.run(None, {name: feats[None, :, :]})[0][0]
        return unit(np.asarray(out, dtype=np.float32))

    return embed


def unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(unit(a), unit(b)))


def windows(samples: np.ndarray, seconds: float = 3.0, hop: float = 1.5) -> list[np.ndarray]:
    n, h = int(seconds * SAMPLE_RATE), int(hop * SAMPLE_RATE)
    if samples.size <= n:
        return [samples]
    return [samples[i : i + n] for i in range(0, samples.size - n + 1, h)]


class Verifier:
    """Enrol once, then `matches(samples)` says whether a clip sounds like the enrolled user."""

    def __init__(
        self, embed: Embedder | None = None, path: Path = DEFAULT_PATH, threshold: float = 0.55
    ) -> None:
        self._embed = embed
        self.path = path
        self.threshold = threshold
        self.voiceprint: np.ndarray | None = None
        if path.exists():
            try:
                self.voiceprint = np.load(path)
            except (OSError, ValueError):
                self.voiceprint = None

    @property
    def enrolled(self) -> bool:
        return self.voiceprint is not None

    def embedder(self) -> Embedder:
        if self._embed is None:
            self._embed = onnx_embedder()
        return self._embed

    def enroll(self, samples: np.ndarray) -> tuple[float, float]:
        """Average embedding over 3 s windows. Returns (min, mean) self-similarity."""
        embs = [e for w in windows(samples) if (e := self.embedder()(w)) is not None]
        if not embs:
            raise ValueError("not enough audio to enrol (speak for at least 5 seconds)")
        print_ = unit(np.mean(np.stack(embs), axis=0))
        sims = [cosine(e, print_) for e in embs]
        self.voiceprint = print_
        self.path.parent.mkdir(parents=True, exist_ok=True)
        np.save(self.path, print_)
        return min(sims), float(np.mean(sims))

    def matches(self, samples: np.ndarray) -> tuple[bool, float]:
        """(matched, similarity). Without a voiceprint every clip matches (nothing to check)."""
        if self.voiceprint is None:
            return True, 1.0
        if samples.size < MIN_SECONDS * SAMPLE_RATE:
            return False, 0.0
        e = self.embedder()(samples)
        if e is None:
            return False, 0.0
        sim = cosine(e, self.voiceprint)
        return sim >= self.threshold, sim
