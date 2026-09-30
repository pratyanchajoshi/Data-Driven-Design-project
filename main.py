"""Quiet stress-cue prototype: Raspberry Pi Pico W + MAX30102 + OLED + vibration motor.

Flow: pulse -> beat intervals (RR) -> PRV as RMSSD -> compare with the wearer's OWN baseline
      -> encouragement on the OLED (no numbers) or, if RMSSD stays low, a breathing cue with vibration.
The serial monitor prints RMSSD for validation only; the wearer never sees it on the device.

Changes from the first version (see the notes in the chat):
 1. Sample times come from a fixed sample clock, not from ticks_ms() at read time.
 2. Peak detection: smoothing, +-150 ms local maximum, sub-sample interpolation.
 3. Artefact filter compares with the median of recent intervals, so it cannot lock onto a wrong cluster.
 4. The cue starts when RMSSD is LOW compared with a personal baseline (was: high vs a fixed 120 ms).
 5. Cue is time-limited (CUE_CYCLES) with a cool-down; IN / HOLD / OUT use different vibration strengths.
 6. Signal-quality states (no finger / weak / saturated) with matching OLED messages.
 7. Serial line now also prints BPM, interval count, measured sample rate and quality.
"""
from math import sqrt
import framebuf
import ssd1306
from machine import Pin, PWM, SoftI2C
from time import sleep_ms
from utime import ticks_add, ticks_diff, ticks_ms

from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM  # type: ignore

# ---- Pins and hardware
SDA_PIN = 10
SCL_PIN = 11
OLED_SDA_PIN = 2
OLED_SCL_PIN = 3
MOTOR_PIN = 28
MOTOR_PWM_FREQUENCY = 1000
MOTOR_HIGH_DUTY = 42000   # BREATHE OUT: strongest
MOTOR_MID_DUTY = 34000    # BREATHE IN: medium
MOTOR_LOW_DUTY = 26000    # HOLD: softest
OLED_WIDTH = 128
OLED_HEIGHT = 64

# ---- Signal
SAMPLE_RATE_HZ = 100      # sensor sample_rate=400 with sample_avg=4 gives 100 samples/s
SAMPLE_PERIOD_MS = 1000 / SAMPLE_RATE_HZ
SAMPLE_WINDOW = 200       # 2 seconds of samples for the adaptive peak threshold
SMOOTH = 3                # moving-average length
PEAK_HALF_WINDOW = 15     # a beat must be the highest point within +-150 ms (rejects the second bump)
PEAK_LEVEL = 0.55         # peak must be above this fraction of the recent min..max range
MIN_IR_FOR_FINGER = 5000  # adjust for your sensor module and LED current
SATURATION_IR = 250000    # 18-bit ADC tops out at 262143: pressing too hard
MIN_PULSE_AMPLITUDE = 50  # window max-min; raise it after looking at real values
MIN_RR_MS = 400           # reject intervals above 150 BPM (seated student)
MAX_RR_MS = 1500          # reject intervals below 40 BPM
RR_JUMP = 0.30            # reject an interval more than 30% away from the median of recent ones
RR_RESET_AFTER = 8        # this many rejections in a row: forget the interval list and start over
HRV_INTERVAL_COUNT = 60
MIN_INTERVALS = 20

# ---- Cue logic
FIXED_RMSSD_THRESHOLD = None  # e.g. 40 to demo with a fixed level; None = personal baseline
BASELINE_REPORTS = 12         # reports (5 s each) used to learn the resting baseline: about 1 minute
CUE_RATIO = 0.70              # cue when RMSSD is below this fraction of the baseline
CONFIRM_REPORTS = 2           # reports in a row below the level before a cue starts
CUE_CYCLES = 3                # breathing cycles per cue (16 s each)
COOLDOWN_MS = 3 * 60 * 1000   # quiet time after a cue
REPORT_INTERVAL_MS = 5000

ENCOURAGEMENTS = ("You've got this!", "Keep going!", "So locked in!")
BREATH_PHASE_DURATION_MS = 4000
BREATH_DISPLAY_INTERVAL_MS = 200
BREATH_PHASES = (
    (0, 1, "BREATHE IN", MOTOR_MID_DUTY),
    (1, 2, "HOLD", MOTOR_LOW_DUTY),
    (2, 3, "BREATHE OUT", MOTOR_HIGH_DUTY),
    (3, 0, "HOLD", MOTOR_LOW_DUTY),
)
BREATH_POINTS = ((12, 12), (116, 12), (116, 52), (12, 52))


def median(values):
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


# ---- Display helpers
def draw_large_lines(display, lines):
    """Draw centered lines using a scaled copy of MicroPython's built-in font."""
    font_buffer = bytearray(8)
    font = framebuf.FrameBuffer(font_buffer, 8, 8, framebuf.MONO_HLSB)
    total_height = sum(8 * scale + 2 for _, scale in lines) - 2
    y = (OLED_HEIGHT - total_height) // 2
    for text, scale in lines:
        text = text.upper()
        x = (OLED_WIDTH - len(text) * 8 * scale) // 2
        for character in text:
            font.fill(0)
            font.text(character, 0, 0, 1)
            for source_y in range(8):
                for source_x in range(8):
                    if font.pixel(source_x, source_y):
                        for dy in range(scale):
                            for dx in range(scale):
                                display.pixel(x + source_x * scale + dx, y + source_y * scale + dy, 1)
            x += 8 * scale
        y += 8 * scale + 2


def show_message(display, lines):
    display.fill(0)
    draw_large_lines(display, lines)
    display.show()


def show_encouragement(display, message):
    if message == ENCOURAGEMENTS[0]:
        lines = (("YOU'VE", 2), ("GOT", 2), ("THIS!", 2))
    elif message == ENCOURAGEMENTS[1]:
        lines = (("KEEP", 2), ("GOING!", 2))
    else:
        lines = (("SO", 2), ("LOCKED", 2), ("IN!", 2))
    show_message(display, lines)


def show_breathing_phase(display, phase_index, phase_elapsed):
    display.fill(0)
    display.text("1", 0, 0)
    display.text("2", OLED_WIDTH - 8, 0)
    display.text("3", OLED_WIDTH - 8, OLED_HEIGHT - 8)
    display.text("4", 0, OLED_HEIGHT - 8)
    start_index, end_index, label, _ = BREATH_PHASES[phase_index]
    start_x, start_y = BREATH_POINTS[start_index]
    end_x, end_y = BREATH_POINTS[end_index]
    progress = min(phase_elapsed / BREATH_PHASE_DURATION_MS, 1)
    delta_x = end_x - start_x
    delta_y = end_y - start_y
    length = sqrt(delta_x * delta_x + delta_y * delta_y)
    unit_x = delta_x / length
    unit_y = delta_y / length
    tip_x = int(start_x + delta_x * progress)
    tip_y = int(start_y + delta_y * progress)
    tail_x = int(tip_x - unit_x * 9)
    tail_y = int(tip_y - unit_y * 9)
    wing_base_x = tip_x - unit_x * 5
    wing_base_y = tip_y - unit_y * 5
    wing_offset_x = unit_y * 3
    wing_offset_y = -unit_x * 3
    display.framebuf.line(tail_x, tail_y, tip_x, tip_y, 1)
    display.framebuf.line(tip_x, tip_y, int(wing_base_x + wing_offset_x), int(wing_base_y + wing_offset_y), 1)
    display.framebuf.line(tip_x, tip_y, int(wing_base_x - wing_offset_x), int(wing_base_y - wing_offset_y), 1)
    label_x = (OLED_WIDTH - len(label) * 8) // 2
    display.framebuf.fill_rect(label_x - 2, 28, len(label) * 8 + 4, 10, 0)
    display.text(label, label_x, 29, 1)
    display.show()


# ---- Signal processing
class HRVMonitor:
    """Turns the IR signal into beat intervals and PRV metrics.

    Time is counted in samples (SAMPLE_PERIOD_MS each). Reading the clock when a sample is popped would
    give a whole batch the same time, because the FIFO is emptied in bursts (and the OLED update blocks
    the loop for tens of ms), which would ruin the RR intervals.
    """

    def __init__(self):
        self.t = 0.0
        self.saturated = False
        self.rejects = 0
        self.reset()

    def reset(self):
        self.finger = False
        self.raw = []
        self.samples = []
        self.sample_times = []
        self.rr_intervals = []
        self.last_beat_time = None

    def add_sample(self, ir_value):
        self.t += SAMPLE_PERIOD_MS
        if ir_value < MIN_IR_FOR_FINGER:
            self.reset()
            return
        self.finger = True
        if ir_value >= SATURATION_IR:
            self.saturated = True

        self.raw.append(ir_value)
        if len(self.raw) > SMOOTH:
            self.raw.pop(0)
        self.samples.append(sum(self.raw) // len(self.raw))
        self.sample_times.append(self.t)
        if len(self.samples) > SAMPLE_WINDOW:
            self.samples.pop(0)
            self.sample_times.pop(0)

        half = PEAK_HALF_WINDOW
        span = 2 * half + 1
        if len(self.samples) < span:
            return
        base = len(self.samples) - span
        candidate = self.samples[base + half]
        for i in range(span):  # candidate must be the maximum within +-half samples
            if i == half:
                continue
            value = self.samples[base + i]
            if (i < half and value > candidate) or (i > half and value >= candidate):
                return
        low = min(self.samples)
        high = max(self.samples)
        if candidate <= low + (high - low) * PEAK_LEVEL:
            return

        # Sub-sample position of the peak (parabola through three points): finer than 10 ms
        before = self.samples[base + half - 1]
        after = self.samples[base + half + 1]
        denominator = before - 2 * candidate + after
        offset = 0.5 * (before - after) / denominator if denominator else 0
        beat_time = self.sample_times[base + half] + offset * SAMPLE_PERIOD_MS

        if self.last_beat_time is None:
            self.last_beat_time = beat_time
            return
        interval = beat_time - self.last_beat_time
        if interval < MIN_RR_MS:
            return  # too soon: ignore this peak and keep the earlier beat
        self.last_beat_time = beat_time
        if interval > MAX_RR_MS:
            return

        recent = self.rr_intervals[-5:]
        if len(recent) >= 5:
            reference = median(recent)
            if abs(interval - reference) > RR_JUMP * reference:
                self.rejects += 1
                if self.rejects >= RR_RESET_AFTER:
                    self.rr_intervals = []
                    self.rejects = 0
                return
        self.rejects = 0
        self.rr_intervals.append(interval)
        if len(self.rr_intervals) > HRV_INTERVAL_COUNT:
            self.rr_intervals.pop(0)

    def quality(self):
        """One of: no_finger, saturated, weak, ok. Clears the saturation flag."""
        saturated = self.saturated
        self.saturated = False
        if not self.finger:
            return "no_finger"
        if saturated:
            return "saturated"
        if self.samples and max(self.samples) - min(self.samples) < MIN_PULSE_AMPLITUDE:
            return "weak"
        return "ok"

    def metrics(self):
        """Return (BPM, RMSSD, SDNN, min RR, max RR, interval count) or None."""
        intervals = self.rr_intervals
        if len(intervals) < MIN_INTERVALS:
            return None
        mean_rr = sum(intervals) / len(intervals)
        sdnn = sqrt(sum((v - mean_rr) ** 2 for v in intervals) / (len(intervals) - 1))
        diffs = [intervals[i] - intervals[i - 1] for i in range(1, len(intervals))]
        rmssd = sqrt(sum(d * d for d in diffs) / len(diffs))
        return 60000 / median(intervals), rmssd, sdnn, min(intervals), max(intervals), len(intervals)


class Cue:
    """State of the breathing cue: time-limited, then a cool-down. The wearer cannot dismiss it."""

    def __init__(self, now):
        self.active = False
        self.cooldown_until = now
        self.low_count = 0
        self._clear()

    def _clear(self):
        self.phase_index = 0
        self.phase_started = None
        self.cycles = 0
        self.last_phase = -1
        self.last_display = None

    def start(self, now):
        self._clear()
        self.active = True
        self.phase_started = now

    def stop(self, now, cooldown=True):
        self.active = False
        self._clear()
        self.low_count = 0
        if cooldown:
            self.cooldown_until = ticks_add(now, COOLDOWN_MS)


def setup_oled():
    oled_i2c = SoftI2C(sda=Pin(OLED_SDA_PIN), scl=Pin(OLED_SCL_PIN), freq=100000)
    devices = oled_i2c.scan()
    print("OLED scan GP2=SCL, GP3=SDA:", [hex(a) for a in devices])
    address = None
    for a in devices:
        if a in (0x3c, 0x3d):
            address = a
            break
    if address is None:  # SDA/SCL swapped?
        alternate = SoftI2C(sda=Pin(OLED_SCL_PIN), scl=Pin(OLED_SDA_PIN), freq=100000)
        devices = alternate.scan()
        print("OLED scan GP3=SCL, GP2=SDA:", [hex(a) for a in devices])
        for a in devices:
            if a in (0x3c, 0x3d):
                address, oled_i2c = a, alternate
                break
    if address is None:
        print("OLED not found. Check its power, ground, SDA, and SCL wiring.")
        return None
    return ssd1306.SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, oled_i2c, addr=address)


def main():
    display = setup_oled()
    if display is not None:
        show_message(display, (("INITIALIZING", 1), ("SENSOR", 2)))

    motor = PWM(Pin(MOTOR_PIN))
    motor.freq(MOTOR_PWM_FREQUENCY)
    motor.duty_u16(0)

    i2c = SoftI2C(sda=Pin(SDA_PIN), scl=Pin(SCL_PIN), freq=400000)
    sensor = MAX30102(i2c=i2c)
    if sensor.i2c_address not in i2c.scan():
        print("MAX30102 not found. Check I2C wiring and pin settings.")
        return
    if not sensor.check_part_id():
        print("Device ID is not a MAX30102/MAX30105.")
        return
    sensor.setup_sensor(sample_rate=400, sample_avg=4, led_power=MAX30105_PULSE_AMP_MEDIUM)  # 100 samples/s

    monitor = HRVMonitor()
    now = ticks_ms()
    cue = Cue(now)
    last_report = now
    rate_started = now
    sample_count = 0
    baseline_values = []
    baseline = None
    screen = None  # what the OLED shows: finger, reading, encourage, cue
    encouragement_index = 0
    last_encouragement = now

    print("Keep your finger still on the sensor. Press Ctrl+C to stop.")
    print("Output is pulse-rate variability (PRV), an estimate of HRV. Values here are for validation only.")

    while True:
        sensor.check()
        while sensor.available():
            sensor.pop_red_from_storage()
            monitor.add_sample(sensor.pop_ir_from_storage())
            sample_count += 1

        now = ticks_ms()
        if ticks_diff(now, last_report) >= REPORT_INTERVAL_MS:
            fs = sample_count * 1000 / max(1, ticks_diff(now, rate_started))
            sample_count = 0
            rate_started = now
            last_report = now
            quality = monitor.quality()
            result = monitor.metrics() if quality == "ok" else None

            if result is None:
                print("No reading | Q: {} | FS: {:.0f} Hz | intervals: {}".format(
                    quality, fs, len(monitor.rr_intervals)))
                cue.stop(now, cooldown=False)
                motor.duty_u16(0)
                wanted = "finger" if quality in ("no_finger", "saturated") else "reading"
                if display is not None and screen != wanted:
                    if wanted == "finger":
                        show_message(display, (("PLACE", 2), ("FINGER", 2)))
                    else:
                        show_message(display, (("READING", 2), ("STAY STILL", 1)))
                screen = wanted
            else:
                bpm, rmssd, sdnn, min_rr, max_rr, count = result
                print("Range: {:.0f}-{:.0f} ms | BPM: {:.0f} | RMSSD: {:.1f} ms | SDNN: {:.1f} ms | N: {} | FS: {:.0f} Hz | Q: {}".format(
                    min_rr, max_rr, bpm, rmssd, sdnn, count, fs, quality))
                print("RMSSD,{:.1f}".format(rmssd))  # for the serial monitor plotter

                # Threshold: fixed for demos, otherwise a share of this person's own resting baseline
                threshold = FIXED_RMSSD_THRESHOLD
                if threshold is None:
                    if baseline is None:
                        baseline_values.append(rmssd)
                        print("Calibrating baseline: {}/{}".format(len(baseline_values), BASELINE_REPORTS))
                        if len(baseline_values) >= BASELINE_REPORTS:
                            baseline = median(baseline_values)
                            print("Baseline RMSSD: {:.1f} ms, cue below {:.1f} ms".format(baseline, baseline * CUE_RATIO))
                            print("Baseline: {:.1f}".format(baseline))
                    else:
                        threshold = baseline * CUE_RATIO

                if threshold is not None and not cue.active:
                    cue.low_count = cue.low_count + 1 if rmssd < threshold else 0
                    if cue.low_count >= CONFIRM_REPORTS and ticks_diff(now, cue.cooldown_until) >= 0:
                        cue.start(now)
                        screen = "cue"
                        print("Cue started")
                        print("CUE")

                if not cue.active and (screen != "encourage" or ticks_diff(now, last_encouragement) >= 15000):
                    message = ENCOURAGEMENTS[encouragement_index % len(ENCOURAGEMENTS)]
                    encouragement_index += 1
                    last_encouragement = now
                    print(message)
                    if display is not None:
                        show_encouragement(display, message)
                    screen = "encourage"

        if cue.active:
            elapsed = ticks_diff(now, cue.phase_started)
            while elapsed >= BREATH_PHASE_DURATION_MS:
                cue.phase_index = (cue.phase_index + 1) % len(BREATH_PHASES)
                if cue.phase_index == 0:
                    cue.cycles += 1
                cue.phase_started = ticks_add(cue.phase_started, BREATH_PHASE_DURATION_MS)
                elapsed = ticks_diff(now, cue.phase_started)

            if cue.cycles >= CUE_CYCLES:  # cue ends by itself, then a cool-down
                motor.duty_u16(0)
                cue.stop(now)
                print("Cue finished")
                last_encouragement = now
                if display is not None:
                    show_encouragement(display, ENCOURAGEMENTS[encouragement_index % len(ENCOURAGEMENTS)])
                encouragement_index += 1
                screen = "encourage"
            else:
                if cue.phase_index != cue.last_phase:
                    motor.duty_u16(BREATH_PHASES[cue.phase_index][3])
                    cue.last_phase = cue.phase_index
                if display is not None and (
                    cue.last_display is None
                    or ticks_diff(now, cue.last_display) >= BREATH_DISPLAY_INTERVAL_MS
                ):
                    show_breathing_phase(display, cue.phase_index, elapsed)
                    cue.last_display = now

        sleep_ms(1)


if __name__ == "__main__":
    main()
