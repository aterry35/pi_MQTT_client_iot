import os
import signal
import subprocess
import time
import threading
import logging
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from config import SystemConfig, SmartcamConfig

logger = logging.getLogger(__name__)

class SmartcamHandler:
    def __init__(self, config: SystemConfig, publish_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.config = config.smartcam
        self.publish_callback = publish_callback
        
        self.log_dir = Path(self.config.log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        self.mtx_log = self.log_dir / 'mediamtx.log'
        self.ffmpeg_log = self.log_dir / 'stream.log'
        self.mediamtx_bin = Path(self.config.mediamtx_bin)
        self.mediamtx_cfg = Path(self.config.mediamtx_cfg)
        
        self.publish_url = self.config.rtsp.publishUrl
        self.rtsp_url = f"rtsp://{self.config.rtsp.host}:{self.config.rtsp.port}/{self.config.rtsp.path}"
        self.rtsp_port = self.config.rtsp.port
        
        self.mediamtx_proc = None
        self.ffmpeg_proc = None
        self._mtx_log_fh = None
        self._ffmpeg_log_fh = None
        
        self.lock = threading.RLock()
        self._action_thread = None
        self._cancel_start = threading.Event()

    def set_publish_callback(self, cb: Callable[[Dict[str, Any]], None]):
        """Useful to inject callback after instantiation."""
        self.publish_callback = cb

    def _running(self, proc):
        return proc is not None and proc.poll() is None

    def _stop_proc(self, proc):
        if proc is None:
            return
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                try:
                    proc.terminate()
                except Exception:
                    pass
            try:
                proc.wait(timeout=5)
            except Exception:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

    def _find_pids(self, pattern: str) -> List[int]:
        try:
            out = subprocess.check_output(['pgrep', '-f', pattern], text=True)
        except subprocess.CalledProcessError:
            return []
        pids = []
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                pid = int(line)
            except ValueError:
                continue
            if pid != os.getpid():
                pids.append(pid)
        return pids

    def _kill_pid(self, pid: int):
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                return
            except Exception:
                pass
            time.sleep(0.4)

    def _cleanup_stale_processes(self) -> List[int]:
        patterns = [
            str(self.mediamtx_bin),
            rf'ffmpeg.*{self.publish_url}',
            r'ffmpeg.*-i /dev/video0',
        ]
        killed = []
        seen = set()
        for pattern in patterns:
            for pid in self._find_pids(pattern):
                if pid in seen:
                    continue
                seen.add(pid)
                self._kill_pid(pid)
                killed.append(pid)
        return killed

    def _port_listening(self, port: int) -> bool:
        cmd = ['bash', '-lc', f"ss -ltn 2>/dev/null | awk 'NR>1 {{print $4}}' | grep -q ':{port}$'"]
        return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0

    def _tail_error(self, path: Path, lines: int = 40) -> Optional[str]:
        if not path.exists():
            return None
        try:
            text = path.read_text(errors='ignore').splitlines()
        except Exception:
            return None
        for line in reversed(text[-lines:]):
            low = line.lower()
            if 'device or resource busy' in low:
                return 'camera_busy'
            if 'error opening input' in low:
                return 'camera_open_failed'
            if 'broken pipe' in low:
                return 'rtsp_broken_pipe'
        return None

    def start_stream(self) -> Dict[str, Any]:
        """Returns immediate status and forks a thread if starting."""
        with self.lock:
            if self._running(self.mediamtx_proc) and self._running(self.ffmpeg_proc) and self._port_listening(self.rtsp_port):
                return {'state': 'already_running', 'rtsp': self.rtsp_url}
                
            if self._action_thread and self._action_thread.is_alive():
                return {'state': 'busy', 'action': 'start_stream'}

            self._cancel_start.clear()
            self._action_thread = threading.Thread(target=self._start_stream_worker, daemon=True)
            self._action_thread.start()
            
        return {'state': 'starting', 'action': 'start_stream'}

    def _start_cancelled(self) -> bool:
        return self._cancel_start.is_set()

    def _start_stream_worker(self):
        current_thread = threading.current_thread()
        try:
            with self.lock:
                self.stop_stream_internal()
                stale = self._cleanup_stale_processes()
                if self._start_cancelled():
                    return

                self._mtx_log_fh = open(self.mtx_log, 'ab')
                self.mediamtx_proc = subprocess.Popen(
                    [str(self.mediamtx_bin), str(self.mediamtx_cfg)],
                    stdout=self._mtx_log_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )

            # Wait for mediamtx without holding the lock for long
            deadline = time.time() + 6
            mediamtx_ready = False
            while time.time() < deadline:
                with self.lock:
                    if self._start_cancelled():
                        self.stop_stream_internal()
                        return
                    if self._running(self.mediamtx_proc) and self._port_listening(self.rtsp_port):
                        mediamtx_ready = True
                        break
                    if not self._running(self.mediamtx_proc):
                        break
                if self._cancel_start.wait(0.3):
                    with self.lock:
                        self.stop_stream_internal()
                    return

            result = None
            with self.lock:
                if self._start_cancelled():
                    self.stop_stream_internal()
                    return
                if not mediamtx_ready:
                    reason = self._tail_error(self.mtx_log) or 'mediamtx_failed'
                    self.stop_stream_internal()
                    result = {'state': 'failed', 'rtsp': self.rtsp_url, 'reason': reason, 'staleKilled': stale}
                else:
                    self._ffmpeg_log_fh = open(self.ffmpeg_log, 'ab')
                    self.ffmpeg_proc = subprocess.Popen([
                        '/usr/bin/ffmpeg',
                        '-hide_banner', '-loglevel', 'warning', '-fflags', '+genpts',
                        '-f', 'v4l2', '-input_format', 'mjpeg', '-video_size', '320x240', '-framerate', '5', '-i', '/dev/video0',
                        '-an',
                        '-vf', 'fps=5,scale=320:240:flags=fast_bilinear,format=yuv420p',
                        '-pix_fmt', 'yuv420p',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
                        '-profile:v', 'baseline', '-level', '3.0', '-g', '5', '-keyint_min', '5', '-sc_threshold', '0', '-bf', '0', '-refs', '1', '-threads', '1',
                        '-x264-params', 'slice-max-size=1200:sync-lookahead=0',
                        '-f', 'rtsp', '-rtsp_transport', 'tcp', self.publish_url
                    ], stdout=self._ffmpeg_log_fh, stderr=subprocess.STDOUT, start_new_session=True)

            if result is not None:
                if not self._start_cancelled():
                    self._publish(result)
                return

            deadline = time.time() + 8
            while time.time() < deadline:
                with self.lock:
                    if self._start_cancelled():
                        self.stop_stream_internal()
                        return
                    if not self._running(self.ffmpeg_proc):
                        break
                err = self._tail_error(self.ffmpeg_log)
                if err == 'camera_busy':
                    break
                if self._cancel_start.wait(0.4):
                    with self.lock:
                        self.stop_stream_internal()
                    return
                
            with self.lock:
                if self._start_cancelled():
                    self.stop_stream_internal()
                    return
                if not self._running(self.ffmpeg_proc):
                    reason = self._tail_error(self.ffmpeg_log) or 'ffmpeg_exited'
                    self.stop_stream_internal()
                    result = {'state': 'failed', 'rtsp': self.rtsp_url, 'reason': reason, 'staleKilled': stale}
                else:
                    result = {
                        'state': 'running',
                        'rtsp': self.rtsp_url,
                        'mediamtxPid': self.mediamtx_proc.pid,
                        'ffmpegPid': self.ffmpeg_proc.pid,
                        'staleKilled': stale,
                    }

            if not self._start_cancelled():
                self._publish(result)
                
        except Exception as e:
            logger.error(f"Error in start stream worker: {e}")
            if not self._start_cancelled():
                self._publish({'state': 'failed', 'reason': str(e)})
        finally:
            with self.lock:
                if self._action_thread is current_thread:
                    self._action_thread = None
                self._cancel_start.clear()


    def _publish(self, payload: dict, action: str = 'start_stream'):
        if self.publish_callback:
            payload['async_result'] = True
            payload['action'] = action
            self.publish_callback(payload)

    def stop_stream_internal(self):
        """Stops streams; assumes lock is held by caller where necessary."""
        self._stop_proc(self.ffmpeg_proc)
        self._stop_proc(self.mediamtx_proc)
        self.mediamtx_proc = None
        self.ffmpeg_proc = None
        for fh in (self._ffmpeg_log_fh, self._mtx_log_fh):
            if fh:
                try:
                    fh.close()
                except Exception:
                    pass
        self._ffmpeg_log_fh = None
        self._mtx_log_fh = None

    def stop_stream(self) -> Dict[str, Any]:
        action_thread = None
        with self.lock:
            self._cancel_start.set()
            action_thread = self._action_thread
            self.stop_stream_internal()
            stale = self._cleanup_stale_processes()
        if action_thread and action_thread.is_alive() and action_thread is not threading.current_thread():
            action_thread.join(timeout=10)
            with self.lock:
                self.stop_stream_internal()
                stale = self._cleanup_stale_processes()
                if not action_thread.is_alive() and self._action_thread is action_thread:
                    self._action_thread = None
        return {'state': 'stopped', 'rtsp': self.rtsp_url, 'staleKilled': stale}

    def stop(self):
        """Uniform shutdown interface — stops streams and cleans up."""
        return self.stop_stream()

    def handle(self, payload: dict) -> dict:
        action = payload.get('action')
        if action in ('start_stream', 'start_all'):
            return self.start_stream()
        if action in ('stop_stream', 'stop_all'):
            return self.stop_stream()
        return {'state': 'ignored', 'action': action}
