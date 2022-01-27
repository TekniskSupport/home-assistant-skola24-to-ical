# skola24 to ics

Creates a file: /config/schedule.ics

To be used with ical sensor integration fork:
[https://github.com/TekniskSupport/ical-sensor-homeassistant](https://github.com/TekniskSupport/ical-sensor-homeassistant)

with the config: 
file:///configuration/schedule.ics

Configuration example:
```yaml
- platform: skola24
  school: Ankeborgsskolan
  class: 9A
  url: ankeborg.skola24.se
```
