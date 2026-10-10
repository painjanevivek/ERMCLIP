"""Create our own narrated sample. No external copyrighted footage is used."""
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from ermclip.util import atomic_text,run
from ermclip.config import ROOT


TEXT="""How can artificial intelligence agents help a small team? The answer starts with a clear task and a reliable workflow. An agent can inspect information, make a plan, use software tools, and check the result. But a useful system also needs limits. It must stop when the evidence is weak. It must protect the original data. It must report errors instead of hiding them.

NVIDIA graphics processors can make local video processing faster. CUDA is one part of that software stack. A local transcription model converts spoken words into text with timestamps. The editor can then find a complete explanation, choose the source boundaries, and add readable captions. Hardware encoding can save time when the computer supports it. A CPU fallback keeps the workflow useful when GPU memory is limited.

Why does context matter? A short statement can change meaning when the editor removes the explanation before it. A good clip includes the problem, the useful point, and the conclusion. Longer compilations need a clear sequence. The editor should avoid repeated arguments and random footage. The goal is to help the viewer understand the source, not to fill an arbitrary duration.

Here is a practical example. Give the worker one source video and two output profiles. It creates one portrait clip and one square clip. Both use the same cached transcript. Each output has its own source timestamps, subtitles, quality evidence, and publishing notes. YouTube tags stay separate from description hashtags. No video is published automatically.

The final lesson is simple. Technical render success does not prove editorial quality. Inspect the real frames and audio. Check the opening and ending. Verify factual claims before publication. Keep the source unchanged and save the editing plan. These checks make a local editing workflow easier to trust."""


def main():
    folder=ROOT/"cache"/"sample-build"
    folder.mkdir(parents=True,exist_ok=True)
    atomic_text(folder/"narration.txt",TEXT)
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","flite=textfile=narration.txt:voice=slt","-ar","48000","narration.wav"],cwd=folder,timeout=120)
    source=ROOT/"input"/"ermclip_demo.mp4"
    run(["ffmpeg","-hide_banner","-loglevel","error","-y","-f","lavfi","-i","testsrc2=size=640x360:rate=30","-i",str(folder/"narration.wav"),"-c:v","libx264","-preset","fast","-threads","4","-c:a","aac","-b:a","160k","-shortest","-movflags","+faststart",str(source)],timeout=300)
    print(source)


if __name__=="__main__": main()
