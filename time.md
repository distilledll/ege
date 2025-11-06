``` python
# capture.py — исправлённая версия
import threading
import queue
import cv2
import time
import os
from loguru import logger
from typing import Dict, List
from .models import FramePacket
from .utils import now_ts, resize_keep_aspect
from .config import Settings


class CaptureWorker(threading.Thread):
    def __init__(self, url: str, out_q: queue.Queue, cfg: Settings):
        super().__init__(daemon=False, name=f"Capture-{url}")
        self.url = url
        self.out_q = out_q
        self.cfg = cfg
        self._stop_event = threading.Event()
        self._cap = None
        self.seq = 0

    def open_cap(self):
        """Open VideoCapture. Try FFmpeg backend first, then fallback."""
        if self._cap:
            return True

        # resolve local files
        if not (self.url.startswith("rtsp://") or self.url.startswith("http://") or self.url.startswith("https://")):
            if not os.path.isabs(self.url):
                candidate = os.path.join(os.getcwd(), self.url)
            else:
                candidate = self.url
            if not os.path.exists(candidate):
                logger.warning("Capture file not found: {} (cwd={})", self.url, os.getcwd())
                return False
            open_path = candidate
        else:
            open_path = self.url

        # Try with FFmpeg backend first (if OpenCV was built with it)
        try:
            self._cap = cv2.VideoCapture(open_path, cv2.CAP_FFMPEG)
        except Exception:
            self._cap = None

        # If not opened, fallback to default backend
        if not self._cap or not self._cap.isOpened():
            if self._cap:
                try:
                    self._cap.release()
                except Exception:
                    pass
            self._cap = cv2.VideoCapture(open_path)

        # Optionally tweak buffer size to reduce latency (if supported)
        try:
            # small buffersize reduces delay for live streams
            if hasattr(cv2, "CAP_PROP_BUFFERSIZE"):
                self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 2)
        except Exception:
            pass

        ok = False
        try:
            ok = self._cap is not None and self._cap.isOpened()
        except Exception:
            ok = False

        if not ok:
            logger.warning("Failed to open capture: {} (tried {})", self.url, open_path)
            try:
                if self._cap:
                    self._cap.release()
            except Exception:
                pass
            self._cap = None
            return False

        logger.info("Opened capture: {} (backend OK)", self.url)
        return True

    def run(self):
        backoff = self.cfg.reconnect_delay_initial
        while not self._stop_event.is_set():
            if not self.open_cap():
                # exponential backoff
                time.sleep(backoff)
                backoff = min(backoff * 2, self.cfg.reconnect_delay_max)
                continue
            backoff = self.cfg.reconnect_delay_initial

            # Try to read with small retry loop to handle transient decode failures
            read_attempts = 0
            max_attempts = 3
            ret = False
            frame = None
            while read_attempts < max_attempts and not self._stop_event.is_set():
                try:
                    ret, frame = self._cap.read()
                except Exception as e:
                    logger.debug("Exception during cap.read() for {}: {}", self.url, e)
                    ret = False
                    frame = None
                if ret and frame is not None and getattr(frame, "size", 0) > 0:
                    break
                read_attempts += 1
                # small sleep to let buffer refill
                time.sleep(0.05)

            if not ret or frame is None or getattr(frame, "size", 0) == 0:
                logger.warning("No frame from {} after {} attempts — releasing cap and retrying", self.url, read_attempts)
                try:
                    self._cap.release()
                except Exception:
                    pass
                self._cap = None
                # short pause before retrying open
                time.sleep(0.1)
                continue

            # Resize safely
            try:
                frame = resize_keep_aspect(frame, self.cfg.frame_width)
            except Exception as e:
                logger.exception("resize_keep_aspect failed for {}: {}", self.url, e)
                # still send original frame if resize fails
                # but guard against None
                if frame is None or getattr(frame, "size", 0) == 0:
                    logger.warning("Frame invalid after resize failure for {}", self.url)
                    time.sleep(0.01)
                    continue

            # Final sanity check
            if frame is None or getattr(frame, "size", 0) == 0:
                logger.warning("Empty frame (after resize) from {}", self.url)
                time.sleep(0.01)
                continue

            pkt = FramePacket(url=self.url, seq=self.seq, ts=now_ts(), frame=frame)
            self.seq += 1
            try:
                if self.out_q.full():
                    try:
                        _ = self.out_q.get_nowait()
                    except queue.Empty:
                        pass
                self.out_q.put_nowait(pkt)
            except queue.Full:
                logger.debug("Drop packet (full) {}", self.url)

            # small yield to avoid busy loop
            time.sleep(0.001)

    def stop(self):
        self._stop_event.set()
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass


class CaptureManager:
    def __init__(self, urls: List[str], cfg: Settings):
        self.cfg = cfg
        self.urls = urls
        self.queues: Dict[str, queue.Queue] = {}
        self.workers: Dict[str, CaptureWorker] = {}
        for u in urls:
            q = queue.Queue(maxsize=self.cfg.frame_queue_maxsize)
            self.queues[u] = q
            self.workers[u] = CaptureWorker(url=u, out_q=q, cfg=cfg)

    def start_all(self):
        for w in self.workers.values():
            w.start()

    def stop_all(self):
        for w in self.workers.values():
            w.stop()
            w.join(timeout=2.0)

    def get_queue(self, url: str) -> queue.Queue:
        return self.queues[url]

```
