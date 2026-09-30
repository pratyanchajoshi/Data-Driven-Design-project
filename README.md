# Data-Driven-Design-project – Tide

Tide is a quiet stress wearable plus a reflective diary website. The band (Raspberry Pi Pico)
measures heart-rate variability (RMSSD). When RMSSD drops clearly below the wearer's own baseline,
it offers a breathing cue through its screen and vibration. The website turns the readings into soft
shapes per 15-minute moment: warmer and bigger means tenser than *your* usual. You can tap a moment,
tag what you were doing and add a note, and the site shows hints about what tends to sit behind
tense moments. The diary never shows a stress score.

## Folder layout

| Path | What it is |
| --- | --- |
| `website/` | The diary site (plain HTML/CSS/JS, no build step, no server needed) |
| `pico/tide_serial.py` | Example MicroPython code showing what the band should print, plus a simulator |

## Running the website

1. Open `website/index.html` in **Chrome or Edge** on a laptop or desktop. Web Serial (USB) only works
   in these browsers, not in Firefox, Safari or on phones. To host it, put the `website/` folder on
   GitHub Pages (Settings → Pages). Hosting needs HTTPS, which GitHub Pages provides.
2. It opens on the **Demo profile** (simulated data, same as the mockup) so you can explore it right away.
3. Plug the Pico into the computer with USB. **Close Thonny** (or any other serial program), because
   only one program can use the port at a time.
4. Click **Connect band**, choose the Pico in the browser's list, and wear the band. Readings are
   grouped into 15-minute moments and the page switches to **My band** automatically.

All data stays in that browser (localStorage). Use *Behind the scenes → Download backup / data (.csv)*
to keep it or analyse it. The CSV has one row per moment, with average RMSSD, ratio to baseline,
cue flag, tag and note.

## What the Pico must print (one message per line over USB serial)

```
RMSSD,48.2      RMSSD in ms for the last window (e.g. every 10–30 s)          ← main message
IBI,812         or raw inter-beat intervals in ms; the site computes RMSSD itself
BASELINE,52.0   the wearer's resting RMSSD once the band has learned it       (optional)
CUE             the band just started a breathing cue                         (optional)
```

In MicroPython that is just `print("RMSSD,{:.1f}".format(value))`. Separators `,` `:` `=` or a space
all work, and JSON lines such as `{"rmssd": 48.2, "cue": true}` are accepted too. Other lines
(debug prints) are ignored but shown in the site's serial log. See `pico/tide_serial.py`. With
`SIMULATE = True` it streams fake data, so you can test the site without a sensor.

- **Baseline:** if the band sends `BASELINE`, that value is used. Otherwise the site uses the median of
  all stored moments, or a fixed value you type in under *Behind the scenes*.
- **Breathing rings:** once the band has sent any `CUE`, rings mark the real cues. Before that, a ring
  is drawn wherever a moment averaged below 0.65 × baseline (you can change this).

### Offline logs

If the band logs to its flash instead of streaming, import the file under *Behind the scenes → Import*.
Use a CSV with columns `timestamp,rmssd[,cue]`, where `timestamp` is ISO text (`2026-09-30T10:15:00`)
or unix seconds. The Pico has no clock of its own, so it only knows the real time if Thonny or your
code sets it.
