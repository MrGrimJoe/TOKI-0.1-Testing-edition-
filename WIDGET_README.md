# TOKI Widget — Hotkey + Voice Edition

> **This is the current and permanent UI** — `main.py` launches
> `main_widget.py` directly, no chat window, and that's staying the
> long-term direction, not a transitional state. "toki_v22" below is
> just old folder-naming framing from an earlier drop-in-patch layout;
> ignore that and the "replaces app.py" framing (`app.py` doesn't exist
> in this codebase anymore) — the technical behavior described below is
> accurate and current.

Drop these three files into your `toki_v22/` folder and run `python main_widget.py`.

---

## Files

| File | Purpose |
|---|---|
| `toki_desktop_mark.py` | Desktop widget (replaces old version) |
| `voice_pipeline.py` | Ctrl+K voice capture (replaces old wake-word version) |
| `main_widget.py` | Entry point — replaces `app.py` for widget-only mode |

---

## Install

```
pip install pynput faster-whisper sounddevice onnxruntime
```

`openWakeWord` is no longer needed.

---

## How it works

### Idle
A tiny 56 px TOKI mark peeks 6 px below the top-centre of your screen.
Barely visible. No chat window anywhere.

### Hover (while idle)
The mark slides fully into view. A panel appears below it listing every
scheduled/timed command with a live countdown and a one-click **✕ cancel** button.
Mouse away → panel closes, mark slides back to notch.

### Ctrl+K — start / extend listening
- **First press**: mark expands to 128 px, slides fully into view, mood → `mysterious`.
  Microphone opens. Recording starts.
- **Press again while talking / paused**: resets the silence timer.
  You can press Ctrl+K as many times as you want to keep the session alive.
- **Stop pressing + silence for ~1.8 s**: recording ends, faster-whisper transcribes,
  command fires through the orchestrator, mark returns to idle notch.

### Active / Working
While the orchestrator is running the command, mood → `energetic` (red rings).
When done, mark shrinks back to idle.

---

## Behavior details

| Situation | What happens |
|---|---|
| Say nothing after Ctrl+K | 6 s timeout → no-speech, mark goes idle |
| Speak, pause, press Ctrl+K | Silence timer resets, keeps listening |
| Ctrl+K while working | Does nothing (session guards against double-trigger) |
| Orchestrator unavailable | Transcription prints to stdout, mark still works |
| sounddevice / pynput missing | `unavailable` signal fires, error in stdout, widget stays up |

---

## Wiring into orchestrator

`main_widget.py` does this automatically if your `orchestrator.py` is in the
same folder.  If it imports cleanly, speech goes through
`orchestrator.process_request()` just like a typed message.  If it doesn't import,
the widget still runs — transcriptions just print to stdout.

To wire the scheduler manually:

```python
from toki_desktop_mark import DesktopMark
mark = DesktopMark()
mark.set_scheduler(orchestrator.scheduler)  # hover panel reads from here
mark.show()
```
