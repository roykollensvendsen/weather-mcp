# Changelog

Every release, what changed in it, and why. Dates are the tag's date. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and
versions follow [semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- The walking skeleton: the thinnest path through the whole system, end to
  end, green in CI on the first commit.
- The forecast for any day MET covers, said as a weekday, a date or "i morgen",
  and `weather_week` for the coming days in a few short lines.
- `weather_hours` for one clock time or the hours between two, said as "15",
  "kl. 15" or "3 pm", on any day the forecast covers.
- `weather_detail` for one detail Yr's app shows beyond the basics: the UV index,
  humidity, dew point, fog, or the wind with its gusts and direction.
- Rain from MET's radar in `weather_now`, in plain words: no rain for the next
  two hours, light rain in about 25 minutes or any minute now, or moderate rain
  until about a time with how many millimetres.
