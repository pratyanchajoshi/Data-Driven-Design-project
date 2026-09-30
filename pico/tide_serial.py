# Tide – example of what the band (Raspberry Pi Pico, MicroPython) should print
# so the website can read it over USB.
#
# The website listens for one message per line:
#   RMSSD,<ms>      an RMSSD value for the last window (e.g. every 10–30 s)   <- main one
#   IBI,<ms>        OR raw inter-beat intervals; the website computes RMSSD itself
#   BASELINE,<ms>   the wearer's resting RMSSD, once the band has learned it (optional)
#   CUE             the band just started a breathing cue (optional; draws the ring)
# Anything else (debug prints, errors) is ignored but shown in the site's serial log.
#
# Copy the three send_* helpers into your own main.py and call them where your code
# already has these values. Set SIMULATE = True to test the website without a sensor.

import time
import random

SIMULATE = True


def send_rmssd(ms):
    print("RMSSD,{:.1f}".format(ms))


def send_baseline(ms):
    print("BASELINE,{:.1f}".format(ms))


def send_cue():
    print("CUE")


def rmssd(ibis):
    """RMSSD (ms) from a list of inter-beat intervals in ms."""
    if len(ibis) < 2:
        return None
    sq = 0
    for a, b in zip(ibis, ibis[1:]):
        sq += (b - a) ** 2
    return (sq / (len(ibis) - 1)) ** 0.5


def simulate():
    """Fake band: a calm baseline around 52 ms with a stressful stretch now and then."""
    base = 52.0
    send_baseline(base)
    t = 0
    while True:
        stressed = (t // 30) % 4 == 3          # every 4th half-minute block is tense
        ratio = random.uniform(0.5, 0.7) if stressed else random.uniform(0.85, 1.15)
        value = base * ratio
        send_rmssd(value)
        if value < base * 0.65:
            send_cue()
        t += 2
        time.sleep(2)


if SIMULATE:
    simulate()
