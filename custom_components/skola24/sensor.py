"""
Get data from Skola24 and write an .ics file.

"""

import logging
import json
import requests
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.components.sensor import PLATFORM_SCHEMA
from homeassistant.const import CONF_NAME

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Skola24"

# Run every 28 days (user preference)
SCAN_INTERVAL = timedelta(days=28)

# Default scope seen in Skola24 timetable viewer requests (not a personal secret)
DEFAULT_SCOPE = "8a22163c-8662-4535-9050-bc5e1923df48"

CONF_URL = "url"
CONF_SCHOOL = "school"
CONF_SSN = "pin"
CONF_CLASSNAME = "class"
CONF_LOCALPATH = "path"
CONF_SENSORNAME = "name"
CONF_EXCLUDE = "exclude"
CONF_INCLUDE_LOCATION = "include_location"
CONF_SCOPE = "scope"  # optional override for X-Scope

TZ = ZoneInfo("Europe/Stockholm")

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_SCHOOL, default=0): cv.string,
        vol.Optional(CONF_CLASSNAME): cv.string,
        vol.Optional(CONF_SSN): cv.string,
        vol.Optional(CONF_EXCLUDE): cv.ensure_list,
        vol.Optional(CONF_INCLUDE_LOCATION, default=True): cv.boolean,
        vol.Optional(CONF_SCOPE, default=DEFAULT_SCOPE): cv.string,
        vol.Required(CONF_URL, default=0): cv.string,
        vol.Required(CONF_LOCALPATH, default=0): cv.string,
        vol.Required(CONF_SENSORNAME, default=0): cv.string,
        # (kept for compatibility if someone has it in their config)
        vol.Optional(CONF_NAME): cv.string,
    }
)


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    async_add_devices([Skola24Entity(hass, config)], True)


class Skola24Entity(Entity):
    def __init__(self, hass, config):
        self.hass = hass

        self._name = "skola24_" + config.get(CONF_SENSORNAME)
        self._unit = "time"
        self._state = "Unavailable"
        self._attributes = {}

        self._school = config.get(CONF_SCHOOL)
        self._className = config.get(CONF_CLASSNAME) if config.get(CONF_CLASSNAME) else None
        self._SSN = config.get(CONF_SSN) if config.get(CONF_SSN) else None

        self._exclude = config.get(CONF_EXCLUDE) if config.get(CONF_EXCLUDE) else []
        self._include_location = config.get(CONF_INCLUDE_LOCATION)

        self._apiHost = config.get(CONF_URL)
        self._localPath = config.get(CONF_LOCALPATH)

        # Build headers per instance so X-Scope can be overridden in YAML
        scope = config.get(CONF_SCOPE) or DEFAULT_SCOPE
        self._headers = {
            "X-Scope": scope,
            "Content-Type": "application/json",
        }

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def icon(self):
        return "mdi:code"

    def errorCheck(self, r):
        try:
            if r.status_code != requests.codes.ok:
                _LOGGER.error("SKOLA24: HTTP %s from %s", r.status_code, r.url)

            js = r.json()
            if js.get("error") is not None:
                _LOGGER.error("SKOLA24: API error from %s : %s", r.url, json.dumps(js.get("error")))
            if js.get("validation"):
                _LOGGER.error("SKOLA24: Validation error from %s : %s", r.url, json.dumps(js.get("validation")))
            if js.get("exception") is not None:
                _LOGGER.error("SKOLA24: Exception from %s : %s", r.url, json.dumps(js.get("exception")))
        except Exception as e:
            _LOGGER.error("SKOLA24: errorCheck failed: %s", e)

    def makeRequest(self, url, data=None):
        if data is None:
            data = "null"
        return requests.post(url, json=data, headers=self._headers, timeout=10)

    async def getSchool(self, hass):
        match = None
        listOfSchools = []

        data = {"getTimetableViewerUnitsRequest": {"hostname": self._apiHost}}
        schools = await hass.async_add_executor_job(
            self.makeRequest,
            "https://web.skola24.se/api/services/skola24/get/timetable/viewer/units",
            data,
        )
        self.errorCheck(schools)

        try:
            units = schools.json()["data"]["getTimetableViewerUnitsResponse"]["units"]
            for s in units:
                listOfSchools.append(s["unitId"])
                if self._school == s["unitId"]:
                    match = s["unitGuid"]  # original code used unitGuid here
        except Exception as e:
            _LOGGER.error("SKOLA24: Failed parsing schools response: %s", e)
            return None

        if match:
            return match

        if listOfSchools:
            _LOGGER.error("SKOLA24: Could not match school unitId. Provide one of these unitId values:")
            for s in listOfSchools:
                _LOGGER.error("SKOLA24: unitId=%s", s)
        return None

    async def getClass(self, hass, guid):
        match = None
        listOfClasses = []

        data = {
            "hostname": self._apiHost,
            "unitGuid": guid,
            "filters": {"class": "true"},
        }
        classes = await hass.async_add_executor_job(
            self.makeRequest,
            "https://web.skola24.se/api/get/timetable/selection",
            data,
        )
        self.errorCheck(classes)

        try:
            for c in classes.json()["data"]["classes"]:
                listOfClasses.append(c["groupName"])
                if self._className == c["groupName"]:
                    match = c["groupGuid"]
        except Exception as e:
            _LOGGER.error("SKOLA24: Failed parsing classes response: %s", e)
            return None

        if match:
            return match

        if listOfClasses:
            _LOGGER.error("SKOLA24: Could not match class. Provide one of these:")
            for c in listOfClasses:
                _LOGGER.error("SKOLA24: class=%s", c)
        return None

    async def getEncryptedSelection(self, hass, studentId):
        data = {"signature": studentId}
        response = await hass.async_add_executor_job(
            self.makeRequest,
            "https://web.skola24.se/api/encrypt/signature",
            data,
        )
        self.errorCheck(response)
        try:
            return response.json()["data"]["signature"]
        except Exception as e:
            _LOGGER.error("SKOLA24: Failed parsing encrypted signature: %s", e)
            return None

    async def getRenderKey(self, hass):
        response = await hass.async_add_executor_job(
            self.makeRequest,
            "https://web.skola24.se/api/get/timetable/render/key",
        )
        self.errorCheck(response)
        try:
            return response.json()["data"]["key"]
        except Exception as e:
            _LOGGER.error("SKOLA24: Failed parsing render key: %s", e)
            return None

    async def getActiveSchoolYears(self, hass):
        data = {"hostName": self._apiHost, "checkSchoolYearsFeatures": "false"}
        response = await hass.async_add_executor_job(
            self.makeRequest,
            "https://web.skola24.se/api/get/active/school/years",
            data,
        )
        self.errorCheck(response)
        try:
            return response.json()["data"]["activeSchoolYears"][0]["guid"]
        except Exception as e:
            _LOGGER.error("SKOLA24: Failed parsing active school years: %s", e)
            return None

    def _weeks_window(self):
        """Return list of (iso_year, iso_week) for 2 weeks back .. 3 weeks ahead."""
        today = date.today()
        iso_year, iso_week, _ = today.isocalendar()
        weeks = []

        for offset in range(-2, 4):  # -2, -1, 0, +1, +2, +3
            monday = date.fromisocalendar(iso_year, iso_week, 1)
            d = monday + timedelta(weeks=offset)
            y, w, _ = d.isocalendar()
            weeks.append((y, w))

        return weeks

    async def getTimeTable(self, hass, renderKey, selection, selectionTypeId, unitGuid, schoolYear):
        lessons = []
        weeks = self._weeks_window()

        for (iso_year, iso_week) in weeks:
            data = {
                "renderKey": renderKey,
                "host": self._apiHost,
                "unitGuid": unitGuid,
                "startDate": "null",
                "endDate": "null",
                "scheduleDay": 0,
                "blackAndWhite": "false",
                "width": 1223,
                "height": 550,
                "schoolYear": schoolYear,
                "selectionType": selectionTypeId,
                "selection": selection,
                "showHeader": "false",
                "periodText": "",
                "week": iso_week,
                "year": iso_year,
                "privateFreeTextMode": "false",
                "privateSelectionMode": "null",
                "customerKey": "",
            }

            response = await hass.async_add_executor_job(
                self.makeRequest,
                "https://web.skola24.se/api/render/timetable",
                data,
            )
            self.errorCheck(response)

            try:
                responseJson = response.json()["data"]["lessonInfo"]
            except Exception as e:
                _LOGGER.error("SKOLA24: Failed parsing timetable render response: %s", e)
                responseJson = None

            if responseJson:
                for lesson in responseJson:
                    lesson["weekOfYear"] = iso_week
                    lesson["isoYear"] = iso_year
                    lessons.append(lesson)

        return lessons

    def _should_exclude(self, lesson_name: str) -> bool:
        if not self._exclude:
            return False
        ln = (lesson_name or "").lower()
        for bad_word in self._exclude:
            if str(bad_word).lower() in ln:
                return True
        return False

    def _ics_escape(self, s: str) -> str:
        """Basic ICS escaping: backslash, semicolon, comma, newline."""
        if s is None:
            return ""
        s = str(s)
        s = s.replace("\\", "\\\\")
        s = s.replace(";", r"\;")
        s = s.replace(",", r"\,")
        s = s.replace("\n", r"\n")
        return s

    def icsLetter(self, data):
        numberOfEvents = 0

        try:
            f = open(self._localPath, "w", encoding="utf-8", newline="\n")
        except Exception as e:
            _LOGGER.error("SKOLA24: Cannot open ICS path '%s' for writing: %s", self._localPath, e)
            return 0

        f.write("BEGIN:VCALENDAR\n")
        f.write("VERSION:2.0\n")
        f.write("CALSCALE:GREGORIAN\n")

        unique_hashes = set()

        for lesson in data:
            try:
                if lesson.get("timeStart") is None:
                    continue

                lesson_name = ""
                try:
                    lesson_name = lesson["texts"][0] if lesson.get("texts") else ""
                except Exception:
                    lesson_name = ""

                # EXCLUDE FILTER
                if self._should_exclude(lesson_name):
                    continue

                # DEDUPE: week + day + start + subject (ignore location)
                unique_string = (
                    f"{lesson.get('isoYear')}-"
                    f"{lesson.get('weekOfYear')}-"
                    f"{lesson.get('dayOfWeekNumber')}-"
                    f"{lesson.get('timeStart')}-"
                    f"{lesson_name}"
                )
                if unique_string in unique_hashes:
                    continue
                unique_hashes.add(unique_string)

                event_text = self.createEventText(lesson)
                if event_text:
                    f.write(event_text)
                    numberOfEvents += 1

            except Exception as e:
                _LOGGER.warning("SKOLA24: Skipping broken lesson. Error: %s", e)

        f.write("END:VCALENDAR\n")
        f.close()
        return numberOfEvents

    def createEventText(self, lesson):
        if lesson.get("timeStart") is None:
            return ""

        texts = lesson.get("texts") or []
        summary = texts[0] if len(texts) > 0 else ""
        location = texts[2] if len(texts) > 2 else ""

        iso_year = lesson.get("isoYear")
        iso_week = lesson.get("weekOfYear")
        dow = lesson.get("dayOfWeekNumber")

        start_time = self.getDateTime(iso_year, iso_week, dow, lesson.get("timeStart"))
        end_time = self.getDateTime(iso_year, iso_week, dow, lesson.get("timeEnd"))

        if not start_time or not end_time:
            return ""

        lines = []
        lines.append("BEGIN:VEVENT\n")
        lines.append(f"SUMMARY:{self._ics_escape(summary)}\n")
        lines.append(f"DTSTART;TZID=Europe/Stockholm:{start_time}\n")
        lines.append(f"DTEND;TZID=Europe/Stockholm:{end_time}\n")

        if self._include_location and location:
            lines.append(f"LOCATION:{self._ics_escape(location)}\n")

        lines.append(f"DESCRIPTION:{self._ics_escape(summary)}\n")
        lines.append("STATUS:CONFIRMED\n")
        lines.append("SEQUENCE:3\n")
        lines.append("END:VEVENT\n")
        return "".join(lines)

    def getDateTime(self, iso_year, iso_week, dow, timestr):
        """
        Build an ISO-week-based datetime string for ICS: YYYYMMDDTHHMMSS
        Skola24's dayOfWeekNumber is assumed to be 1..7 (Mon..Sun).
        If it comes as 0..6 (Sun..Sat), we normalize.
        """
        if not (iso_year and iso_week and dow is not None and timestr):
            return None

        try:
            dow_int = int(dow)
            if dow_int == 0:
                iso_dow = 7
            elif 1 <= dow_int <= 7:
                iso_dow = dow_int
            else:
                iso_dow = max(1, min(7, dow_int))
        except Exception:
            return None

        try:
            hh, mm, ss = [int(x) for x in str(timestr).split(":")]
            day = date.fromisocalendar(int(iso_year), int(iso_week), int(iso_dow))
            dt = datetime.combine(day, dtime(hh, mm, ss), tzinfo=TZ)
            return dt.strftime("%Y%m%dT%H%M%S")
        except Exception as e:
            _LOGGER.error(
                "SKOLA24: Failed building datetime (y=%s w=%s dow=%s t=%s): %s",
                iso_year,
                iso_week,
                dow,
                timestr,
                e,
            )
            return None

    async def async_update(self):
        hass = self.hass

        if not self._SSN and not self._className:
            _LOGGER.error("SKOLA24: You must define one of 'pin' or 'class'.")
            self._state = "Unavailable"
            return

        guid = await self.getSchool(hass)
        if not guid:
            self._state = "Unavailable"
            return

        if self._SSN:
            selection = await self.getEncryptedSelection(hass, self._SSN)
            selectionTypeId = 4
        else:
            selection = await self.getClass(hass, guid)
            selectionTypeId = 0

        if not selection:
            self._state = "Unavailable"
            return

        renderKey = await self.getRenderKey(hass)
        if not renderKey:
            self._state = "Unavailable"
            return

        schoolYear = await self.getActiveSchoolYears(hass)
        if not schoolYear:
            self._state = "Unavailable"
            return

        schedule = await self.getTimeTable(hass, renderKey, selection, selectionTypeId, guid, schoolYear)
        numberOfEvents = self.icsLetter(schedule)

        self._state = datetime.now(TZ).isoformat()
        self._attributes.update({"numberOfEvents": numberOfEvents})
        self._attributes.update({"ics_path": self._localPath})
        self._attributes.update({"include_location": self._include_location})
        self._attributes.update({"weeks_window": "weekNow-2 .. weekNow+3 (ISO weeks)"})
        # expose scope (useful for debugging; not a secret)
        self._attributes.update({"x_scope": self._headers.get("X-Scope")})

