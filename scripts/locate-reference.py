"""Locate a supplied short in the original podcast with local audio correlation."""
import json
from pathlib import Path
import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve
from scipy.ndimage import uniform_filter1d
from ermclip.util import run, atomic_json

root = Path(__file__).resolve().parents[1]
folder = root / 'output/reference-style'
source = Path(r'C:\Users\ASUS\Downloads\Startup Ideas Timing AI How To Build The Next Big Thing Sravanth Aluru FO572 Raj Shamani.mp4')
reference = Path(r'C:\Users\ASUS\Downloads\vidssave.com Every Entrepreneur Will Relate to This _ Sravanth Aluru - Raj Shamani #shorts 1080P.mp4')
for path, name in ((source, 'original'), (reference, 'reference')):
    wav = folder / (name + '-match.wav')
    if not wav.exists():
        run(['ffmpeg', '-v', 'error', '-y', '-i', str(path), '-vn', '-ac', '1', '-ar', '2000', str(wav)], timeout=600)
rate, raw = wavfile.read(folder / 'original-match.wav')
x = raw.astype(np.float32) / 32768
rate, raw = wavfile.read(folder / 'reference-match.wav')
r = raw.astype(np.float32) / 32768
results = []
for offset in (0, 10, 20, 30, 35):
    q = r[offset * rate:(offset + 3) * rate].copy()
    q -= q.mean()
    n = len(q)
    corr = fftconvolve(x, q[::-1], mode='valid')
    sums = np.concatenate(([0.], np.cumsum(x, dtype=np.float64)))
    squares = np.concatenate(([0.], np.cumsum(x*x, dtype=np.float64)))
    variance = np.maximum(1e-10, squares[n:]-squares[:-n]-(sums[n:]-sums[:-n])**2/n)
    corr /= np.sqrt(variance * np.sum(q*q))
    best = int(np.argmax(corr))
    results.append({'reference_seconds':offset, 'source_seconds':best/rate, 'correlation':float(corr[best])})
    print(results[-1], flush=True)
atomic_json(folder / 'reference-source-matches.json', {'source':str(source),'reference':str(reference),'matches':results})
