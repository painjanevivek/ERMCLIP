# Desktop editing sequence

The desktop window starts with no selected video. Import means open a local file, not send it to a server on the internet. There are five steps. Model inference and video processing stay on this PC.

```mermaid
sequenceDiagram
    actor User
    participant App as Desktop window (WebView2)
    participant Local as Loopback service
    participant Queue as Persistent local queue
    participant Engine as Local editing engine
    User->>App: 1. Import video with Windows file picker
    App->>Local: Check selected file and audio
    Local-->>App: Source preview and metadata
    User->>App: 2. Set count, duration, topics and language
    User->>App: 3. Select frame layout and caption style
    User->>App: 4. Check summary and select Start
    App->>Local: Submit explicit source and settings
    Local->>Queue: Save job before starting the engine
    Local->>Engine: Start worker and model on demand
    Engine->>Queue: Update stages and write local exports
    Queue-->>App: 5. Progress and review links
    User->>App: Watch exports and check captions
    opt User requests a revision
        User->>App: Describe the change
        App->>Queue: Save new revision job
        Queue->>Engine: Process revision; preserve earlier exports
    end
    Engine->>Engine: Release model after queue is idle
```

At sign-in, the small loopback service starts. An empty queue loads no model. Persisted pending work resumes after restart unless the queue is paused. The desktop shortcut opens one native window. The engine starts after a job is submitted or pending work is found. The reference gallery is available through its separate manual scripts and is not part of startup.
