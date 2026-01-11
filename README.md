# robloxAuto

Windows-only helper that sends key presses and mouse clicks to a Roblox window even while it is in the background.

## Setup

1. Copy the example config:

```bash
copy config.example.json config.json
```

2. Adjust key and click timing/coordinates in `config.json`.

## Run

```bash
python src/roblox_auto.py --title "Roblox" --config config.json
```

### Config format

```json
{
  "key_cycle": [
    {"key": "W", "delay_s": 0.4},
    {"key": "D", "delay_s": 0.4},
    {"key": "S", "delay_s": 0.4},
    {"key": "A", "delay_s": 0.4}
  ],
  "click_cycle": [
    {"x": 960, "y": 540, "delay_s": 1.5}
  ]
}
```

- `key_cycle` entries send a key press, then wait `delay_s` seconds.
- `click_cycle` entries click screen coordinates, then wait `delay_s` seconds.
- Screen coordinates are absolute pixels; the script converts them to the Roblox window's client coordinates.
