# Light-ASD

Architecture copied from Junhua Liao and coauthors' MIT-licensed Light-ASD,
commit ed38c232de5efe0261dbd68627c0ade7cdfe14eb.
Source: https://github.com/Junhua-Liao/Light-ASD

Model.py imports were changed to package-relative imports. Encoder.py and
Classifier.py are unchanged. ERMCLIP uses CPU inference, restricted tensor-only
checkpoint loading, and the authors' TalkSet fine-tuned weights. The upstream demo,
training scripts, and shell commands are not executed.
