import random
import threading
import time
from collections import deque
from pathlib import Path
import logging
from typing import Dict, Any, List, Optional

try:
    from sense_hat import SenseHat, ACTION_PRESSED
except Exception:
    SenseHat = None
    ACTION_PRESSED = 'pressed'
    logging.getLogger(__name__).warning("sense_hat module not available — SenseHat features will be disabled")

logger = logging.getLogger(__name__)

# Colors
BLACK = (0, 0, 0)
GREEN = (0, 180, 0)
RED = (220, 0, 0)
WHITE = (180, 180, 180)
BLUE = (0, 0, 180)
YELLOW = (220, 180, 0)
PURPLE = (150, 0, 180)
ORANGE = (255, 100, 0)
WALL = (0, 80, 180)
SILVER = (150, 150, 150)
BROWN = (120, 70, 20)
MINION_YELLOW = (255, 210, 40)
DARK_EYE = (8, 8, 12)
COPPER = (140, 90, 55)
GOLD = (225, 175, 70)
ICE = (235, 245, 255)
BRIGHT_BLUE = (65, 175, 255)
HIGHLIGHT = (255, 255, 255)

# Game Rules
GRID = 8
BASE_TICK = 0.35
MIN_TICK = 0.10
LEVEL_UP_EVERY = 3
DIRECTIONS = {
    'up': (0, -1),
    'down': (0, 1),
    'left': (-1, 0),
    'right': (1, 0),
}
OPPOSITE = {
    'up': 'down',
    'down': 'up',
    'left': 'right',
    'right': 'left',
}


def current_tick(level: int) -> float:
    return max(MIN_TICK, BASE_TICK - ((level - 1) * 0.03))


def build_walls(level: int) -> set:
    walls = set()
    if level >= 2:
        for x in range(1, GRID - 1):
            walls.add((x, 0))
            walls.add((x, GRID - 1))
        for y in range(2, GRID - 2):
            walls.add((0, y))
            walls.add((GRID - 1, y))
    if level >= 3:
        for y in range(2, 6):
            if y != 4:
                walls.add((3, y))
    if level >= 4:
        for x in range(2, 6):
            if x != 4:
                walls.add((x, 3))
    return walls


def random_food(snake: deque, walls: set) -> Optional[tuple]:
    occupied = set(snake) | set(walls)
    free = [(x, y) for y in range(GRID) for x in range(GRID) if (x, y) not in occupied]
    return random.choice(free) if free else None


def render_pixel_art(rows: List[str], palette: Dict[str, tuple]) -> List[tuple]:
    return [palette[ch] for row in rows for ch in row]


def build_eye_frame(stage: str = 'open') -> List[tuple]:
    palette = {
        '.': BLACK,
        'D': DARK_EYE,
        'C': COPPER,
        'G': GOLD,
        'W': ICE,
        'B': BLUE,
        'L': BRIGHT_BLUE,
        'H': HIGHLIGHT,
    }

    if stage == 'closed':
        rows = [
            "........",
            ".CGGGGC.",
            "CDDDDDDC",
            "DDDDDDDD",
            "..HHHH..",
            "...WW...",
            "........",
            "........",
        ]
    elif stage == 'half':
        rows = [
            "........",
            ".CGGGGC.",
            "CDDDDDDC",
            "DDDDDDDD",
            ".HLLLLH.",
            "...BB...",
            "..C..C..",
            "........",
        ]
    else:
        rows = [
            "........",
            ".CGGGGC.",
            "CDDDDDDC",
            "DDDDDDDD",
            "HLLBBLLH",
            ".WLLLLW.",
            "..C..C..",
            "........",
        ]

    return render_pixel_art(rows, palette)


class SnakeMode:
    def __init__(self, sense: SenseHat, lock: threading.RLock, get_events_fn):
        self.sense = sense
        self.lock = lock
        self.get_events_fn = get_events_fn
        self._thread = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._state = {'state': 'idle', 'mode': 'snake'}

    def status(self) -> dict:
        with self._state_lock:
            return dict(self._state)

    def _set_state(self, **kwargs):
        with self._state_lock:
            self._state = kwargs

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> dict:
        if self.is_running():
            return self.status()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        deadline = time.time() + 2
        while time.time() < deadline:
            st = self.status()
            if st.get('state') != 'idle':
                return st
            time.sleep(0.05)
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        with self.lock:
            if self.sense:
                self.sense.clear()
        self._set_state(state='stopped', mode='snake')
        return self.status()

    def _draw(self, snake, food, walls, level):
        if not self.sense: return
        pixels = [BLACK] * 64
        for x, y in walls:
            pixels[y * GRID + x] = WALL
        for i, (x, y) in enumerate(snake):
            pixels[y * GRID + x] = WHITE if i == 0 else GREEN
        if food:
            fx, fy = food
            pixels[fy * GRID + fx] = RED
        pixels[level - 1] = YELLOW
        with self.lock:
            self.sense.set_pixels(pixels)

    def _flash(self, color, times=2, on=0.12, off=0.08):
        if not self.sense: return
        for _ in range(times):
            if self._stop.is_set(): return
            with self.lock:
                self.sense.clear(color)
            time.sleep(on)
            with self.lock:
                self.sense.clear()
            time.sleep(off)

    def _wait_start(self) -> bool:
        if not self.sense: return False
        with self.lock:
            self.sense.clear()
            self.sense.show_letter('S', text_colour=BLUE)
        self._set_state(state='waiting_start', mode='snake')
        while not self._stop.is_set():
            for event in self.get_events_fn():
                if event.action == ACTION_PRESSED:
                    return True
            time.sleep(0.05)
        return False

    def _game_over_animation(self, snake, walls):
        if not self.sense: return
        pixels = [BLACK] * 64
        for x, y in walls:
            pixels[y * GRID + x] = PURPLE
        for x, y in snake:
            pixels[y * GRID + x] = ORANGE
        with self.lock:
            self.sense.set_pixels(pixels)
        time.sleep(0.25)
        
        for _ in range(3):
            if self._stop.is_set(): return
            self._flash(RED, times=1, on=0.15, off=0.05)
            with self.lock:
                self.sense.set_pixels(pixels)
            time.sleep(0.1)
            
        for i in range(len(snake), 0, -1):
            if self._stop.is_set(): return
            pixels = [BLACK] * 64
            for x, y in walls:
                pixels[y * GRID + x] = PURPLE
            for x, y in list(snake)[:i]:
                pixels[y * GRID + x] = RED
            with self.lock:
                self.sense.set_pixels(pixels)
            time.sleep(0.06)
            
        self._flash(RED, times=2, on=0.12, off=0.08)

    def _game_loop(self):
        snake = deque([(3, 4), (2, 4), (1, 4)])
        direction = 'right'
        pending = direction
        score = 0
        level = 1
        walls = build_walls(level)
        food = random_food(snake, walls)
        last_tick = time.monotonic()
        self._set_state(state='playing', mode='snake', score=score, level=level)

        while not self._stop.is_set():
            for event in self.get_events_fn():
                if event.action != ACTION_PRESSED:
                    continue
                if event.direction in DIRECTIONS and event.direction != OPPOSITE[direction]:
                    pending = event.direction
                elif event.direction == 'middle':
                    return score, level, False, list(snake), set(walls)

            now = time.monotonic()
            tick = current_tick(level)
            if now - last_tick < tick:
                time.sleep(0.01)
                continue
            
            last_tick = now
            direction = pending
            dx, dy = DIRECTIONS[direction]
            hx, hy = snake[0]
            nx, ny = (hx + dx) % GRID, (hy + dy) % GRID

            if (nx, ny) in snake or (nx, ny) in walls:
                snake.appendleft((nx, ny))
                return score, level, True, list(snake), set(walls)

            snake.appendleft((nx, ny))
            if food and (nx, ny) == food:
                score += 1
                new_level = 1 + (score // LEVEL_UP_EVERY)
                if new_level != level:
                    level = new_level
                    walls = build_walls(level)
                    if any(segment in walls for segment in snake):
                        return score, level, True, list(snake), set(walls)
                    
                    if self.sense and not self._stop.is_set():
                        with self.lock:
                            self.sense.show_message(f'L{level}', text_colour=YELLOW, back_colour=BLACK, scroll_speed=0.06)
                            
                food = random_food(snake, walls)
                if food is None:
                    return score, level, True, list(snake), set(walls)
            else:
                snake.pop()

            self._set_state(state='playing', mode='snake', score=score, level=level)
            self._draw(snake, food, walls, level)

        return score, level, False, list(snake), set(walls)

    def _run(self):
        self._set_state(state='starting', mode='snake')
        try:
            while not self._stop.is_set():
                if not self._wait_start():
                    break
                score, level, crashed, snake, walls = self._game_loop()
                if self._stop.is_set():
                    break
                    
                if crashed:
                    self._game_over_animation(snake, walls)
                else:
                    self._flash(BLUE, times=1, on=0.2, off=0.05)
                    
                if self.sense and not self._stop.is_set():
                    with self.lock:
                        self.sense.show_message(f'Score {score} Lv {level}', text_colour=BLUE, scroll_speed=0.05)
        finally:
            if self.sense:
                with self.lock:
                    self.sense.clear()
            self._set_state(state='stopped', mode='snake')


class BlinkMode:
    def __init__(self, sense: SenseHat, lock: threading.RLock):
        self.sense = sense
        self.lock = lock
        self._thread = None
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._state = {'state': 'idle', 'mode': 'blink'}

    def status(self) -> dict:
        with self._state_lock:
            return dict(self._state)

    def _set_state(self, **kwargs):
        with self._state_lock:
            self._state = kwargs

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _draw(self, stage: str = 'open'):
        if not self.sense:
            return
        with self.lock:
            self.sense.set_pixels(build_eye_frame(stage=stage))

    def start(self) -> dict:
        if self.is_running():
            return self.status()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        deadline = time.time() + 2
        while time.time() < deadline:
            st = self.status()
            if st.get('state') != 'idle':
                return st
            time.sleep(0.05)
        return self.status()

    def stop(self) -> dict:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        if self.sense:
            with self.lock:
                self.sense.clear()
        self._set_state(state='stopped', mode='blink')
        return self.status()

    def _run(self):
        self._set_state(state='blinking', mode='blink')
        try:
            while not self._stop.is_set():
                self._draw(stage='open')
                if self._stop.wait(random.uniform(1.5, 2.8)):
                    break
                self._draw(stage='half')
                if self._stop.wait(0.12):
                    break
                self._draw(stage='closed')
                if self._stop.wait(0.11):
                    break
                self._draw(stage='half')
                if self._stop.wait(0.12):
                    break
                self._draw(stage='open')
                if self._stop.wait(0.10):
                    break
        finally:
            if self.sense:
                with self.lock:
                    self.sense.clear()
            self._set_state(state='stopped', mode='blink')


class SenseHatHandler:
    def __init__(self):
        self.sense = SenseHat() if SenseHat else None
        self.lock = threading.RLock()
        
        self.last_reading = None
        self.on_color = (255, 255, 255)
        
        # Debouncing
        self.debounce_time = 0.15
        self._last_event_time = 0.0

        # Display modes
        self.snake = SnakeMode(self.sense, self.lock, self.get_debounced_events) if self.sense else None
        self.blink = BlinkMode(self.sense, self.lock) if self.sense else None

        # Background Message Queue
        self._message_queue = deque()
        self._message_thread_event = threading.Event()
        self._stop_background = threading.Event()
        self._background_thread = threading.Thread(target=self._background_worker, daemon=True)
        self._background_thread.start()

    def _active_display_mode(self) -> Optional[str]:
        if self.snake and self.snake.is_running():
            return 'snake'
        if self.blink and self.blink.is_running():
            return 'blink'
        return None

    def get_debounced_events(self) -> List[Any]:
        """Provides debounced joystick events from SenseHAT."""
        if not self.sense:
            return []
            
        with self.lock:
            # We clear events and only yield if a certain amount of time passed
            events = self.sense.stick.get_events()
            
        debounced = []
        now = time.monotonic()
        for event in events:
            # Filter duplicates that occur too closely
            if event.action == ACTION_PRESSED:
                if now - self._last_event_time > self.debounce_time:
                    debounced.append(event)
                    self._last_event_time = now
            else:
                # We return released/held directly, or just ignore for game
                debounced.append(event)
                
        return debounced

    def _background_worker(self):
        """Worker thread to handle non-blocking text scrolling."""
        while not self._stop_background.is_set():
            self._message_thread_event.wait(0.5)
            if self._stop_background.is_set():
                break

            if self._active_display_mode():
                time.sleep(0.1)
                continue

            msg_data = None
            with self.lock:
                if self._message_queue:
                    msg_data = self._message_queue.popleft()
                else:
                    self._message_thread_event.clear()

            if msg_data and self.sense:
                text, kwargs = msg_data
                # Avoid scrolling if game is busy, but we pop it from queue 
                if not (self.snake and self.snake.is_running()):
                    with self.lock:
                        self.sense.show_message(text, **kwargs)

    def queue_message(self, text: str, **kwargs):
        """Queue a message to be shown asynchronously."""
        if not self.sense:
            return {'ok': False, 'error': 'sense_hat module unavailable'}

        mode = self._active_display_mode()
        if mode:
            return {'state': 'busy', 'mode': mode}
            
        with self.lock:
            self._message_queue.append((text, kwargs))
            self._message_thread_event.set()
        return {'ok': True, 'action': 'queued_text', 'text': text}

    def reading(self) -> Dict[str, Any]:
        """Gets current environment readings."""
        if not self.sense:
            return {'ok': False, 'error': 'sense_hat module unavailable'}
            
        with self.lock:
            orientation = self.sense.get_orientation_degrees()
            accel = self.sense.get_accelerometer_raw()
            gyro = self.sense.get_gyroscope_raw()
            
            reading = {
                'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
                'temperature_c': round(self.sense.get_temperature(), 2),
                'humidity_pct': round(self.sense.get_humidity(), 2),
                'pressure_hpa': round(self.sense.get_pressure(), 2),
                'orientation_deg': {
                    'pitch': round(float(orientation.get('pitch', 0.0)), 2),
                    'roll': round(float(orientation.get('roll', 0.0)), 2),
                    'yaw': round(float(orientation.get('yaw', 0.0)), 2),
                },
                'accelerometer': {
                    'x': round(float(accel.get('x', 0.0)), 4),
                    'y': round(float(accel.get('y', 0.0)), 4),
                    'z': round(float(accel.get('z', 0.0)), 4),
                },
                'gyroscope': {
                    'x': round(float(gyro.get('x', 0.0)), 4),
                    'y': round(float(gyro.get('y', 0.0)), 4),
                    'z': round(float(gyro.get('z', 0.0)), 4),
                },
            }
            self.last_reading = reading
            
        return reading

    def lights_on(self) -> Dict[str, Any]:
        if not self.sense:
            return {'ok': False, 'error': 'sense_hat module unavailable'}

        mode = self._active_display_mode()
        if mode:
            return {'state': 'busy', 'mode': mode}
            
        with self.lock:
            self.sense.clear(self.on_color)
            
        return {
            'state': 'lights_on', 
            'color': {'r': self.on_color[0], 'g': self.on_color[1], 'b': self.on_color[2]}
        }

    def lights_off(self) -> Dict[str, Any]:
        if not self.sense:
            return {'ok': False, 'error': 'sense_hat module unavailable'}
            
        if self.snake and self.snake.is_running():
            return self.snake.stop()
        if self.blink and self.blink.is_running():
            return self.blink.stop()
            
        with self.lock:
            self.sense.clear()
            
        return {'state': 'lights_off'}

    def start_blink(self) -> Dict[str, Any]:
        if not self.sense or not self.blink:
            return {'ok': False, 'error': 'sense_hat module unavailable'}

        if self.blink.is_running():
            return self.blink.status()

        if self.snake and self.snake.is_running():
            return {'state': 'busy', 'mode': 'snake'}

        return self.blink.start()

    def stop(self):
        """Cleanup worker threads."""
        self._stop_background.set()
        self._message_thread_event.set()
        if self.blink:
            self.blink.stop()
        if self.snake:
            self.snake.stop()

    def handle(self, payload: dict) -> dict:
        """Handle incoming command payloads (backward compatibility)."""
        action = payload.get('action')
        text = str(payload.get('text', payload.get('payload', ''))).strip().lower()

        if action == 'read_once':
            return {'state': 'reading', 'reading': self.reading()}
        if action == 'show_text':
            return self.queue_message(payload.get('text', ''))
        if action in ('blink', 'start_blink') or text == 'blink':
            return self.start_blink()
        if action in ('lights_on', 'led_on') or text in ('lights on', 'led on', 'on'):
            return self.lights_on()
        if action in ('lights_off', 'led_off', 'clear') or text in ('lights off', 'led off', 'off', 'clear'):
            return self.lights_off()
        if action in ('snake', 'start_snake') or text == 'snake':
            if not self.snake:
                return {'ok': False, 'error': 'sense_hat module unavailable'}
            if self.blink and self.blink.is_running():
                return {'state': 'busy', 'mode': 'blink'}
            return self.snake.start()
        if action in ('stop_snake',) or text == 'stop snake':
            if not self.snake:
                return {'ok': False, 'error': 'sense_hat module unavailable'}
            return self.snake.stop()
        if action == 'status' or text == 'status':
            if self.snake and self.snake.is_running():
                return self.snake.status()
            if self.blink and self.blink.is_running():
                return self.blink.status()
            return {'state': 'idle'}
            
        if 'text' in payload:
            return self.queue_message(str(payload.get('text', '')))
        if 'payload' in payload:
            return self.queue_message(str(payload.get('payload', '')))
            
        return {
            'state': 'placeholder',
            'message': 'Sense HAT command not recognized',
            'action': action,
            'text': text,
        }
