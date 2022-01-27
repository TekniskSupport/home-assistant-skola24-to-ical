"""
Get data from skola24
"""

import logging
import json
import requests
from datetime import datetime, timedelta

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.components.sensor import PLATFORM_SCHEMA
#from homeassistant.components.rest import RestData
from homeassistant.const import (CONF_NAME)

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME            = 'Skola24'
DEFAULT_INTERVAL        = 86000
HEADERS                 = {"X-Scope": "8a22163c-8662-4535-9050-bc5e1923df48", "Content-Type":"application/json"}
CONF_URL                = 'url'
CONF_SCHOOL             = 'school'
CONF_CLASSNAME          = 'class'

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_SCHOOL, default=0): cv.string,
    vol.Required(CONF_CLASSNAME, default=0): cv.string,
    vol.Required(CONF_URL, default=0): cv.string,
})
SCAN_INTERVAL = timedelta(minutes=DEFAULT_INTERVAL)

async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    school    = config.get(CONF_SCHOOL)
    className = config.get(CONF_CLASSNAME)
    apiHost   = config.get(CONF_URL)

    await add_sensors(
        hass,
        config,
        async_add_devices,
        school,
        className,
        apiHost,
        discovery_info
    )

async def add_sensors(
        hass,
        config,
        async_add_devices,
        school,
        className,
        apiHost,
        discovery_info=None
    ):
    sensors = []
    sensors.append(entityRepresentation(hass, school, className, apiHost))
    async_add_devices(sensors, True)

class entityRepresentation(Entity):
    def __init__(self, hass, school, className, apiHost):
        self._name        = "skola24_to_icalendar"
        self._unit        = "time"
        self._state       = "Unavailable"
        self._attributes  = {}

        self.hass         = hass
        self._school      = school
        self._className   = className
        self._apiHost     = apiHost

        weekNow   = datetime.today().isocalendar()[1]
        self.week = range(weekNow-2, weekNow+4)
        self.year = datetime.today().year

        self.selection = None

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        if self._state is not None:
            return self._state
        return None

    @property
    def extra_state_attributes(self):
        return self._attributes

    @property
    def unit_of_measurement(self):
        return self._unit

    @property
    def icon(self):
        return 'mdi:code'

    def errorCheck(self, r):
        if(r.status_code != requests.codes.ok):
            exit("[ERROR]\tGot response "+str(r.status_code)+" from "+r.url)
        if (r.json()["error"] != None):
            exit("[ERROR]\tGot the following error from "+r.url+" : "+ json.dumps(r.json()["error"]))
        if(r.json()["validation"]):
            exit("[ERROR]\tGot error from "+r.url+", error: "+json.dumps(r.json()["validation"]))
        if(r.json()["exception"] != None):
            exit("[ERROR]\tGot exception from "+r.url+", error: "+json.dumps(r.json()["exception"]))

    def makeRequest(self, url, data=None):
        if data is None:
            return requests.post(url, json="null", headers=HEADERS)
        else:
            return requests.post(url, json=data, headers=HEADERS)

    async def getSchool(self, hass):
        match = None
        listOfSchools = []
        data = {
            "getTimetableViewerUnitsRequest": {
                "hostname": self._apiHost
            }
        }
        schools = await hass.async_add_executor_job(self.makeRequest,
            "https://web.skola24.se/api/services/skola24/get/timetable/viewer/units",
            data
        )
        self.errorCheck(schools)
        for s in schools.json()["data"]["getTimetableViewerUnitsResponse"]["units"]:
            listOfSchools.append(s["unitId"])
            if self._school == s["unitId"]:
                match=s["unitGuid"]

        if match:
            return match;
        else:
            if len(listOfSchools) > 0:
                print('Please provide one if following')
                for s in listOfSchools:
                    print(s)
            exit("ERROR: could not match school")

    async def getClass(self, hass, guid):
        match = None
        listOfClasses = []
        data = {
            "hostname": self._apiHost,
            "unitGuid": guid,
            "filters": {
                "class": "true"
            }
        }
        classes = await hass.async_add_executor_job(self.makeRequest,
            "https://web.skola24.se/api/get/timetable/selection",
            data
        )
        self.errorCheck(classes)
        for c in classes.json()["data"]["classes"]:
            listOfClasses.append(c["groupName"])
            if self._className == c["groupName"]:
                match=c["groupGuid"]

        if match:
            return match;
        else:
            if len(listOfClasses) > 0:
                print('Please provide one of the following:')
                for c in listOfClasses:
                    print(c)
            exit("ERROR: could not match class")

    async def getRenderKey(self, hass):
        response = await hass.async_add_executor_job(self.makeRequest,
                "https://web.skola24.se/api/get/timetable/render/key"
        )
        self.errorCheck(response)
        return response.json()["data"]["key"]

    async def getTimeTable(self, hass, renderKey, selection, guid):
        lessons = []
        for w in self.week:
            data={
                "renderKey":renderKey,
                "host":self._apiHost,
                "unitGuid":guid,
                "startDate":"null",
                "endDate":"null",
                "scheduleDay":0,
                "blackAndWhite":"false",
                "width":1223,
                "height":550,
                "selectionType":0,
                "selection":selection,
                "showHeader":"false",
                "periodText":"",
                "week":w,
                "year":self.year,
                "privateFreeTextMode":"false",
                "privateSelectionMode":"null",
                "customerKey":""
            }
            response = await hass.async_add_executor_job(self.makeRequest,
                    "https://web.skola24.se/api/render/timetable",
                    data
            )
            self.errorCheck(response)
            responseJson = response.json()["data"]["lessonInfo"]
            if responseJson is not None:
                for lesson in responseJson:
                    lesson["weekOfYear"] = w
                    print(lesson)
                    lessons.append(lesson)
        return lessons

    def icsLetter(self, data):
        f = open("schedule.ics", "w")
        f.write('BEGIN:VCALENDAR'+"\n")
        f.write('VERSION:2.0'+"\n")
        f.write('CALSCALE:GREGORIAN'+"\n")
        for lesson in data:
          self.icsEvent(lesson, f)
        f.write('END:VCALENDAR')
        f.close()

    def icsEvent(self, lesson, f):
        if lesson['timeStart'] is not None:
            f.write('BEGIN:VEVENT'+"\n")
            f.write('SUMMARY:' + lesson['texts'][0]+"\n")
            f.write('DTSTART;TZID=Europe/Berlin:' +
                self.getDateTime(lesson['dayOfWeekNumber'], lesson['timeStart'], lesson["weekOfYear"])+"\n")
            f.write('DTEND;TZID=Europe/Berlin:' +
                self.getDateTime(lesson['dayOfWeekNumber'], lesson['timeEnd'], lesson["weekOfYear"])+"\n")
            f.write('LOCATION:' + lesson['texts'][2]+"\n")
            f.write('DESCRIPTION:' + lesson['texts'][0]+"\n")
            f.write('STATUS:CONFIRMED'+"\n")
            f.write('SEQUENCE:3'+"\n")
            f.write('END:VEVENT'+"\n")

    def getDateTime(self, dow, time, week):
        return datetime.strftime(
            datetime.strptime(
                f"{self.year} {week} {dow} {time}",
                "%Y %W %w %H:%M:%S"
            ),
            "%Y%m%dT%H%M%S"
        )

    async def async_update(self):
        hass = self.hass
        guid = await self.getSchool(hass)
        selection = await self.getClass(hass, guid)
        renderKey = await self.getRenderKey(hass)
        schedule = await self.getTimeTable(hass, renderKey, selection, guid)
        self.icsLetter(schedule)

        self._state = datetime.now()
        #self._attributes.update({attribute: data[attribute]})
