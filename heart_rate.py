
# Some ports need to import 'sleep' from 'time' module
from time import sleep
from machine import Pin, SoftI2C
from utime import ticks_diff, ticks_ms

from max30102 import MAX30102, MAX30105_PULSE_AMP_MEDIUM # type: ignore

class HeartRateMonitor:
    """A simple heart rate monitor that uses a moving window to smooth the signal and find peaks."""

    def __init__(self, sample_rate=100, window_size=10, smoothing_window=5):
        self.sample_rate = sample_rate
        self.window_size = window_size
        self.smoothing_window = smoothing_window
        self.samples = []
        self.timestamps = []
        self.filtered_samples = []

    def add_sample(self, sample):
        """Add a new sample to the monitor."""
        timestamp = ticks_ms()
        self.samples.append(sample)
        self.timestamps.append(timestamp)

        # Apply smoothing
        if len(self.samples) >= self.smoothing_window:
            smoothed_sample = (
                sum(self.samples[-self.smoothing_window :]) / self.smoothing_window
            )
            self.filtered_samples.append(smoothed_sample)
        else:
            self.filtered_samples.append(sample)

        # Maintain the size of samples and timestamps
        if len(self.samples) > self.window_size:
            self.samples.pop(0)
            self.timestamps.pop(0)
            self.filtered_samples.pop(0)

    def find_peaks(self):
        """Find peaks in the filtered samples."""
        peaks = []

        if len(self.filtered_samples) < 3:  # Need at least three samples to find a peak
            return peaks

        # Calculate dynamic threshold based on the min and max of the recent window of filtered samples
        recent_samples = self.filtered_samples
        min_val = min(recent_samples)
        max_val = max(recent_samples)
        threshold = (
            min_val + (max_val - min_val) * 0.5
        )  # 50% between min and max as a threshold

        # A normal heart beat is at least 300 ms apart (under 200 BPM).
        minimum_peak_interval = 300
        last_peak_time = None

        for i in range(1, len(self.filtered_samples) - 1):
            if (
                self.filtered_samples[i] > threshold
                and self.filtered_samples[i - 1] < self.filtered_samples[i]
                and self.filtered_samples[i] > self.filtered_samples[i + 1]
            ):
                peak_time = self.timestamps[i]
                if last_peak_time is None or ticks_diff(peak_time, last_peak_time) >= minimum_peak_interval:
                    peaks.append((peak_time, self.filtered_samples[i]))
                    last_peak_time = peak_time

        return peaks

    def calculate_heart_rate(self):
        """Calculate the heart rate in beats per minute (BPM)."""
        peaks = self.find_peaks()

        if len(peaks) < 2:
            return None  # Not enough peaks to calculate heart rate

        # Calculate the average interval between peaks in milliseconds
        intervals = []
        for i in range(1, len(peaks)):
            interval = ticks_diff(peaks[i][0], peaks[i - 1][0])
            intervals.append(interval)

        # The median is less sensitive to one incorrectly detected peak.
        intervals.sort()
        middle = len(intervals) // 2
        if len(intervals) % 2:
            median_interval = intervals[middle]
        else:
            median_interval = (intervals[middle - 1] + intervals[middle]) / 2

        # Convert intervals to heart rate in beats per minute (BPM)
        heart_rate = 60000 / median_interval

        return heart_rate


def main():
    i2c = SoftI2C(sda=Pin(10),  # Here, use your I2C SDA pin (GP.. number, so this is GP10)
                  scl=Pin(11),  # Here, use your I2C SCL pin (GP.. number)
                  freq=400000)  # Fast: 400kHz, slow: 100kHz

    print("Starting I2C scan...")
    i2c_devices = i2c.scan()
    print(i2c_devices)

    # Sensor instance
    sensor = MAX30102(i2c=i2c)  # An I2C instance is required

    # Scan I2C bus to ensure that the sensor is connected
    if sensor.i2c_address not in i2c_devices:
        print("Sensor", sensor.i2c_address, " not found.")
        return
    elif not (sensor.check_part_id()):
        # Check that the targeted sensor is compatible
        print("I2C device ID not corresponding to MAX30102 or MAX30105.")
        return
    else:
        print("Sensor connected and recognized.")

    # Load the default configuration
    print("Setting up sensor with default configuration.", "\n")
    sensor.setup_sensor()

    # Set the sample rate to 400: 400 samples/s are collected by the sensor
    sensor_sample_rate = 400
    sensor.set_sample_rate(sensor_sample_rate)

    # Set the number of samples to be averaged per each reading
    sensor_fifo_average = 8
    sensor.set_fifo_average(sensor_fifo_average)

    # Set LED brightness to a medium value
    sensor.set_active_leds_amplitude(MAX30105_PULSE_AMP_MEDIUM)

    # Expected acquisition rate: 400 Hz / 8 = 50 Hz
    actual_acquisition_rate = int(sensor_sample_rate / sensor_fifo_average)

    sleep(1)

    print(
        "Starting data acquisition from RED & IR registers...",
        "press Ctrl+C to stop.",
        "\n",
    )
    sleep(1)

    # Initialize the heart rate monitor
    hr_monitor = HeartRateMonitor(
        # Select a sample rate that matches the sensor's acquisition rate
        sample_rate=actual_acquisition_rate,
        # Select a significant window size to calculate the heart rate (2-5 seconds)
        window_size=int(actual_acquisition_rate * 3),
    )

    # Setup to calculate the heart rate every 2 seconds
    hr_compute_interval = 2  # seconds
    ref_time = ticks_ms()  # Reference time

    runAve = 0 # running average of the heart rate
    readings = 0 # number of readings

    while True:
        # The check() method has to be continuously polled, to check if
        # there are new readings into the sensor's FIFO queue. When new
        # readings are available, this function will put them into the storage.
        sensor.check()

        # Check if the storage contains available samples
        if sensor.available():
            # Access the storage FIFO and gather the readings (integers)
            red_reading = sensor.pop_red_from_storage()
            ir_reading = sensor.pop_ir_from_storage()

            # Add the IR reading to the heart rate monitor
            # Note: based on the skin color, the red, IR or green LED can be used
            # to calculate the heart rate with more accuracy.
            hr_monitor.add_sample(ir_reading)

        # Periodically calculate the heart rate every `hr_compute_interval` seconds
        if ticks_diff(ticks_ms(), ref_time) / 1000 > hr_compute_interval:
            # Calculate the heart rate
            heart_rate = hr_monitor.calculate_heart_rate()
            if heart_rate is not None:
                # Print the heart rate in beats per minute (BPM), with the running avarage after 10 readings
                runAve =9/10*runAve +1/10*heart_rate
                readings += 1
                if (readings > 10):
                    print("Heart Rate: {:.0f} BPM (Av. {:.0f})".format(heart_rate, runAve))
                else:
                    print("Heart Rate: {:.0f} BPM".format(heart_rate))
            else:
                print("Not enough data to calculate heart rate")
            # Reset the reference time
            ref_time = ticks_ms()


if __name__ == "__main__":
    main()
