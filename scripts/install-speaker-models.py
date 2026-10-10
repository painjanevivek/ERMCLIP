"""Download pinned, public speaker assets only. No local media is uploaded."""
from pathlib import Path
import hashlib
import os
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
ASD = "ed38c232de5efe0261dbd68627c0ade7cdfe14eb"
YUNET = "47534e27c9851bb1128ccc0102f1145e27f23f98"
ASSETS = [
    (f"https://raw.githubusercontent.com/Junhua-Liao/Light-ASD/{ASD}/weight/finetuning_TalkSet.model",
     "light-asd-source/weight/finetuning_TalkSet.model", "efc375833887eefa9d209dc92810e18519b04c3c73ea35a549f2a7f40b7d94d5"),
    (f"https://raw.githubusercontent.com/Junhua-Liao/Light-ASD/{ASD}/LICENSE",
     "light-asd-source/LICENSE", "3c5b187c06d6c0fdcfe02ad73f51470eaa35045cc2e60749d805332d98441eb1"),
    (f"https://media.githubusercontent.com/media/opencv/opencv_zoo/{YUNET}/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
     "face_detection_yunet_2023mar.onnx", "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4"),
    (f"https://raw.githubusercontent.com/opencv/opencv_zoo/{YUNET}/models/face_detection_yunet/LICENSE",
     "YUNET-LICENSE", "c83b8120c50ccbd4c4f96edf53141bdd566ebb8f8e9227e415326aa1b1aba958"),
]


def main():
    for url, name, expected in ASSETS:
        dest = ROOT/"cache"/"speaker-models"/name
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == expected:
            print(f"Verified {name}")
            continue
        with urllib.request.urlopen(url, timeout=120) as response:
            data = response.read(8*1024*1024+1)
        if hashlib.sha256(data).hexdigest() != expected:
            raise RuntimeError(f"Checksum failed for {name}; existing file was preserved")
        temporary = dest.with_suffix(dest.suffix+".download")
        temporary.write_bytes(data)
        os.replace(temporary, dest)
        print(f"Installed {name} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
