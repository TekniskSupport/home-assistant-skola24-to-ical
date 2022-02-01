# skola24 to ics

Creates a file: /config/schedule.ics

To be used with ical sensor integration fork:
[https://github.com/TekniskSupport/ical-sensor-homeassistant](https://github.com/TekniskSupport/ical-sensor-homeassistant)

with the config:
`file:///config/schedule.ics`

Configuration example:
```yaml
- platform: skola24
  school: Ankeborgsskolan
  class: 9A
  url: ankeborg.skola24.se
  name: mysensor
  path: /config/schedule.ics
```

Configuration example using a personal identification number:
```yaml
- platform: skola24
  school: Ankeborgsskolan
  pin: 991231-1234
  url: ankeborg.skola24.se
  name: mysensor
  path: /config/schedule.ics
```
