# i2c_web
simple i2c (lcd 16x2) displayer for IoT purposes

- You can either send payloads to display to either http or an mqtt broker
- The second line can be scrollable if `scrollable` gets a `true` (soft limit 40 chars)
- You can load custom char with `|charName|` it will be replaced by his corresponding substitute

Syntax Usage:
```
{
  "l1": "my |music| string",
  "l2": "my superb long |wifi|fill| scrollable string",
  "scrollable": true
}
```
