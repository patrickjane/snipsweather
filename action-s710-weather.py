#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# -----------------------------------------------------------------------------
# Snips Weather + DarkSky
# -----------------------------------------------------------------------------
# Copyright 2019 Patrick Fial
# -----------------------------------------------------------------------------
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and 
# associated documentation files (the "Software"), to deal in the Software without restriction, 
# including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, 
# and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, 
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or substantial 
# portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT 
# LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. 
# IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, 
# WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE 
# SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

# -----------------------------------------------------------------------------
# Imports
# -----------------------------------------------------------------------------

import io
import toml
import requests
import logging
import json
import time
from datetime import datetime, timedelta

from os import environ

from snipsTools import SnipsConfigParser
from hermes_python.hermes import Hermes
from hermes_python.ontology import *
from geopy.geocoders import Nominatim

# -----------------------------------------------------------------------------
# global definitions (home assistant service URLs)
# -----------------------------------------------------------------------------

FORECAST_URL = "https://api.darksky.net/forecast/"
APP_ID = "snips-skill-s710-wetter"

# -----------------------------------------------------------------------------
# class App
# -----------------------------------------------------------------------------

class App(object):

    # -------------------------------------------------------------------------
    # ctor

    def __init__(self):

        self.logger = logging.getLogger(APP_ID)
        self.geolocator = Nominatim(user_agent = APP_ID)

        # parameters

        self.mqtt_host = "localhost:1883"
        self.mqtt_user = None
        self.mqtt_pass = None

        self.api_key = None
        self.home_location = None
        self.weekdays = ['montag', 'dienstag', 'mittwoch', 'donnerstag', 'freitag', 'samstag', 'sonntag']
        self.day_range_symbols = ['früh', 'vormittag', 'mittag', 'nachmittag', 'abend', 'nacht']

        self.known_intents = ['s710:getForecast','s710:getTemperature','s710:hasRain','s710:hasSun','s710:hasSnow']

        homecity = None
        
        # read config.ini (HASS host + token)

        try:
            self.config = SnipsConfigParser.read_configuration_file("config.ini")
        except Exception as e:
            self.logger.error("Failed to read config.ini ({})".format(e))
            self.config = None

        try:
            self.read_toml()
        except Exception as e:
            self.logger.error("Failed to read /etc/snips.toml ({})".format(e))

        if 'api_key' in self.config['secret']:
            self.api_key = self.config['secret']['api_key']

        if 'homecity' in self.config['global']:
            homecity = self.config['global']['homecity']

        self.http_headers = { 'Accept-Encoding': 'deflate, gzip' }

        self.logger.debug("Debug: Connecting to {}@{} ...".format(self.mqtt_user, self.mqtt_host))

        try:
            loc = self.geolocator.geocode(homecity)
            self.home_location = (loc.latitude, loc.longitude)
        except Exception as e:
            self.logger.error("Error: Failed to determine homecity coordinates for '{}' ({})".format(homecity, e))

        self.start()

    # -----------------------------------------------------------------------------
    # read_toml

    def read_toml(self):
        snips_config = toml.load('/etc/snips.toml')
    
        if 'mqtt' in snips_config['snips-common'].keys():
            self.mqtt_host = snips_config['snips-common']['mqtt']

        if 'mqtt_username' in snips_config['snips-common'].keys():
            self.mqtt_user = snips_config['snips-common']['mqtt_username']

        if 'mqtt_password' in snips_config['snips-common'].keys():
            self.mqtt_pass = snips_config['snips-common']['mqtt_password']

    # -------------------------------------------------------------------------
    # start

    def start(self):
        with Hermes(mqtt_options = MqttOptions(broker_address = self.mqtt_host, username = self.mqtt_user, password = self.mqtt_pass)) as h:
            h.subscribe_intents(self.on_intent).start()

    # -------------------------------------------------------------------------
    # on_intent

    def on_intent(self, hermes, intent_message):
        city = None
        time = None

        # extract slots (time, location)

        try:
            if len(intent_message.slots):
                if len(intent_message.slots.time):
                    time = intent_message.slots.time.first().value
                    time = time.lower()
                if len(intent_message.slots.location):
                    city = intent_message.slots.location.first().value
        except:
            pass

        # ignore unknown/unexpected intents

        if intent_message.intent_name not in self.known_intents:
            return

        self.logger.debug("Intent {} with city {} and time {}".format(intent_message.intent.intent_name, city if city else '-', time if time else '-'))

        try:
            self.query_weather(hermes, intent_message, intent_message.intent.intent_name, city, time)
        except Exception as e:
            self.logger.error("Failed to query weather ({})".format(e))

    # -------------------------------------------------------------------------
    # query_weather

    def query_weather(self, hermes, intent_message, intent_name, city, time):

        # get corresponding home assistant service-url + payload

        try:
            req_url = self.get_request_url(city, self.home_location)
        except Exception as e:
            self.logger.error("Failed to execute location HTTP request ({})".format(e))
            return None

        if not req_url:
            self.logger.error("Failed to determine forecast URL/parameters, cannot query weather")
            return None

        self.logger.debug("Debug: Querying URL [{}]".format(req_url.replace(self.api_key, "API_KEY")))

        try:
            req = requests.get(req_url, headers = self.http_headers, params = { 'units': 'si', 'lang': 'de', 'exclude': 'flags,alerts,minutely', 'extend': 'hourly' })
        except Exception as e:
            self.logger.error("Failed to execute weather HTTP request ({})".format(e))
            return None

        if req.status_code != 200:
            self.logger.error("Failed to query dark sky forecast (HTTP {} / {})".format(req.status_code, req.content.decode('utf-8')[:80] if req.content else "-"))
            return None

        try:
            response_content = json.loads(req.content.decode('utf-8'))
        except Exception as e:
            self.logger.error("Failed to parse response content from dark sky ({})".format(e))
            return None

        try:
            response_message = self.process_response(hermes, intent_name, response_content, time)
        except Exception as e:
            self.logger.error("Failed to parse response content from dark sky ({})".format(e))
            return None

        self.done(hermes, intent_message, response_message)

    # -------------------------------------------------------------------------
    # get_request_url

    def get_request_url(self, city = None, coordinates = None):
        location = coordinates

        if city is not None:
            try:
                loc = self.geolocator.geocode(city)
                location = (loc.latitude, loc.longitude)
            except Exception as e:
                self.logger.error("Failed to query coordinates for city '{}' ({})".format(city, e))
                return None

        if not location:
            return None

        return FORECAST_URL + self.api_key + "/" + str(location[0]) + "," + str(location[1])

    # -------------------------------------------------------------------------
    # process_response

    def process_response(self, hermes, intent_name, response_content, time):
        scale, tme_from, tme_to, prefix = self.get_timerange(time)
        weather = self.select_weather(response_content, scale, tme_from, tme_to)

        if not weather or not weather[0] or (scale == 'daily' and not weather[1]):
            self.logger.warning('Failed to get weather info for requested range ({} - {})'.format(tme_from, tme_to))
            return None

        self.logger.debug("Check weather with scale {} and prefix {}".format(scale, prefix))

        if intent_name == 's710:getForecast':
            return self.process_forecast(hermes, intent_name, response_content, scale, weather, prefix)

        if intent_name == 's710:getTemperature':
            return self.process_temperature(hermes, intent_name, response_content, scale, weather, prefix)

        if intent_name == 's710:hasRain':
            return self.process_has(hermes, intent_name, 'rain', response_content, scale, weather, prefix)

        if intent_name == 's710:hasSun':
            return self.process_has(hermes, intent_name, 'sun', response_content, scale, weather, prefix)

        if intent_name == 's710:hasSnow':
            return self.process_has(hermes, intent_name, 'snow', response_content, scale, weather, prefix)

        self.logger.error("Intent {}/parameters not recognized, ignoring".format(intent_name))
        return None

    # -------------------------------------------------------------------------
    # process_forecast

    def process_forecast(self, hermes, intent_name, response_content, scale, weather_hours_and_days, prefix):
        def get_summary(wx_object, remove_dot = False):
            sum = wx_object['summary']

            if not remove_dot and not sum.endswith('.'):
                sum = sum + '.'

            if remove_dot and sum.endswith('.'):
                sum = sum[:-1]

            return sum

        def get_wx_on(what, data):
            if len(data) == 1:
                return ' Vermutlich ' + what + ' am ' + data[0] + '.'

            return ' Vermutlich ' + what + ' am ' + ', '.join(data[:-1]) + ' und ' + data[-1] + '.' if data else ''

        if scale == 'currently':
            return 'Das Wetter ist aktuell ' + get_summary(weather_hours_and_days[0]) + ' Temperatur liegt bei ' + str(round(weather_hours_and_days[0]['temperature'])) + ' Grad.'

        elif scale == 'daily':
            days = weather_hours_and_days[1]
            temps_max = [w['temperatureMax'] for w in days]
            temps_min = [w['temperatureMin'] for w in days]

            if len(days) == 1:
                return 'Wetter ' + prefix + ': ' + get_summary(days[0]) + ' Temperaturen zwischen ' + str(round(days[0]['temperatureMin'])) + ' und ' + str(round(days[0]['temperatureMax'])) + ' Grad.'

            if len(days) == 2:
                day1 = datetime.fromtimestamp(days[0]['time']).weekday()
                day2 = datetime.fromtimestamp(days[1]['time']).weekday()

                if days[0]['summary'] == days[1]['summary']:
                    res1 = 'Wetter am ' + self.weekdays[day1].capitalize() + ' und ' + self.weekdays[day2].capitalize() + ': ' + get_summary(days[0]) + ' '
                    res2 = ''
                    resTemp = ' Die Temperaturen liegen zwischen ' + str(round(min(temps_min))) + ' und ' + str(round(max(temps_max))) +  ' Grad.'
                else:
                    res1 = 'Wetter am ' + self.weekdays[day1].capitalize() + ': ' + get_summary(days[0]) + ' '
                    res2 = self.weekdays[day2].capitalize() + ' ' + get_summary(days[1])
                    resTemp = ' Die Temperaturen liegen zwischen ' + str(round(min(temps_min))) + ' und ' + str(round(max(temps_max))) +  ' Grad.'

                return res1 + res2 + resTemp

            # more than 2 multiple days ('diese Woche', 'nächste Woche')

            day1 = self.weekdays[datetime.fromtimestamp(days[0]['time']).weekday()].capitalize()

            rain_days = [self.weekdays[datetime.fromtimestamp(w['time']).weekday()].capitalize() for w in days if w['icon'] == 'rain' and w['time'] != days[0]['time']]
            snow_days = [self.weekdays[datetime.fromtimestamp(w['time']).weekday()].capitalize() for w in days if w['icon'] == 'snow' and w['time'] != days[0]['time']]
            thunder_days = [self.weekdays[datetime.fromtimestamp(w['time']).weekday()].capitalize() for w in days if w['icon'] == 'thunderstorm' and w['time'] != days[0]['time']]

            rain_on =  get_wx_on('Regen', rain_days)
            snow_on = get_wx_on('Schnee', snow_days)
            thunder_on = get_wx_on('Gewitter', thunder_days)

            res1 = 'Wetter am ' + day1 + ': ' + get_summary(days[0]) 
            temp = ' Temperaturen zwischen ' + str(round(min(temps_min))) + ' und ' + str(round(max(temps_max))) + ' Grad.'

            return res1 + rain_on + snow_on + thunder_on + temp
        else:
            hours = weather_hours_and_days[0]
            temps = [w['temperature'] for w in hours]

            if hours[0]['summary'] == hours[-1]['summary']:
                return 'Wetter ' + prefix + ': ' + get_summary(hours[0]) + ' Temperaturen zwischen ' + str(round(min(temps))) + ' und ' + str(round(max(temps))) + ' Grad.'

            return 'Wetter ' + prefix + ': ' + get_summary(hours[0], True) + ' bis ' + get_summary(hours[-1]) + ' Temperaturen zwischen ' + str(round(min(temps))) + ' und ' + str(round(max(temps))) + ' Grad.'
            
        return None

    # -------------------------------------------------------------------------
    # process_temperature

    def process_temperature(self, hermes, intent_name, response_content, scale, weather_hours_and_days, prefix):
        weather = weather_hours_and_days[0]

        if scale == 'currently' and 'temperature' in weather:
            return 'Es sind gerade ' + str(round(weather['temperature'])) + ' Grad.'
        
        else:
            weather = weather_hours_and_days[0]

            if len(weather) == 1:
                return prefix + ' wird es etwa ' + str(round(weather[0]['temperature'])) + ' Grad warm.'

            temps = [w['temperature'] for w in weather]

            return prefix + ' wird es zwischen ' + str(round(min(temps))) + ' und ' + str(round(max(temps))) +  ' Grad warm.'

        return None

    # -------------------------------------------------------------------------
    # process_has

    def process_has(self, hermes, intent_name, what, response_content, scale, weather_hours_and_days, prefix):
        weather = weather_hours_and_days[0]
        weather_days = weather_hours_and_days[1]

        if scale == 'currently':
            if what == 'sun':
                if 'icon' in weather and weather['icon'] == 'clear-day':
                    return 'Ja, es ist gerade sonnig.'

                if 'icon' in weather and 'cloudy' in weather['icon']:
                    return 'Nein, ist ist gerade ' + ('eher ' if weather['icon'] is not 'cloudy' else '') + 'bewölkt.'

                return 'Nein, ich denke nicht.'
            else:
                if 'precipType' not in weather or weather['precipType'] is not what or 'precipProbability' not in weather or weather['precipProbability'] < 0.3:
                    return 'Ich denke nicht, dass es gerade ' + ('regnet.' if what == 'rain' else 'schneit.')
            
                if weather['precipProbability'] < 0.75:
                    return 'Ja, es ' + ('regnet gerade' if what == 'rain' else 'schneit gerade') + ' vermutlich.'

                return 'Ja, es ' + ('regnet gerade.' if what == 'rain' else 'schneit gerade.')
        else:
            if what == 'sun':
                hasSun = [w for w in weather if w['icon'] == 'clear-day']
                hasPartly = [w for w in weather if w['icon'] == 'partly-cloudy-day']

                if not hasSun and not hasPartly:
                    return 'Nein, ich denke nicht.'

                w = hasSun[0] if hasSun else hasPartly[0]
                dt = datetime.fromtimestamp(w['time'])
                day = self.weekdays[dt.weekday()]
                when = dt.strftime("%H:%M Uhr")

                if scale == 'hourly':
                    return 'Gegen ' + when + ' wird es ' + ('sonnig.' if hasSun else ('ein bisschen Sonne geben.'))
                elif len(weather_days) == 1:
                    return prefix + ' wird es gegen ' + when + ' ' + ('sonnig.' if hasSun else ('ein bisschen Sonne geben.'))

                return 'Am ' + day.capitalize() + ' wird es gegen ' + when + ' ' + ('sonnig.' if hasSun else ('ein bisschen Sonne geben.'))
            else:
                hasRain = [w for w in weather if w['icon'] == 'rain' or ('precipType' in w and w['precipType'] == what and 'precipProbability' in w and w['precipProbability'] > 0.3)]
                hasHail = [w for w in weather if w['icon'] == 'hail' or ('precipType' in w and w['precipType'] == what and 'precipProbability' in w and w['precipProbability'] > 0.3)]
                hasThunder = [w for w in weather if w['icon'] == 'thunderstorm' or ('precipType' in w and w['precipType'] == what and 'precipProbability' in w and w['precipProbability'] > 0.3)]

                if not hasRain and not hasHail and not hasThunder:
                    return 'Nein, ich denke nicht.'

                w = hasRain[0] if hasRain else (hasHail[0] if hasHail else hasThunder[0])
                dt = datetime.fromtimestamp(w['time'])
                day = self.weekdays[dt.weekday()]
                prob = ''
                when = dt.strftime("%H:%M Uhr")

                if w['precipProbability'] < 0.3:
                    return 'Nein, ich denke nicht.'

                if w['precipProbability'] < 0.75:
                    prob = ' vermutlich'

                if scale == 'hourly':
                    return 'Gegen ' + when + ' wird es ' + ('regnen.' if hasRain else ('hageln.' if hasHail else 'Gewitter geben.'))
                elif len(weather_days) == 1:
                    return prefix + ' wird es ' + ('regnen.' if hasRain else ('hageln.' if hasHail else 'Gewitter geben.'))

                return 'Am ' + day.capitalize() + ' wird es' + prob + ' gegen ' + when + ' ' + ('regnen.' if hasRain else ('hageln.' if hasHail else 'Gewitter geben.'))

        return None

    # -------------------------------------------------------------------------
    # select_weather

    def select_weather(self, weather, scale, tme_from, tme_to):
        res = None

        try:
            if scale == 'currently':
                return (weather['currently'], None)

            hours = [hour for hour in weather['hourly']['data'] if hour['time'] >= tme_from and hour['time'] <= tme_to]
            days = [day for day in weather['daily']['data'] if day['time'] >= tme_from and day['time'] <= tme_to]

            return (hours, days)

        except Exception as e:
            self.logger.error('Failed to parse response contents ({})'.format(e))
            return None

        return res

    # -------------------------------------------------------------------------
    # get_timerange

    def get_timerange(self, time_string):
        if not time_string:
            return ('currently', None, None, 'Jetzt')

        # single weekdays

        contained_weekdays = [day for day in self.weekdays if day in time_string]
        contained_day_range_symbols = [sym for sym in self.day_range_symbols if sym in time_string]

        if contained_weekdays:
            return self.get_weekday(self.weekdays.index(contained_weekdays[0]))

        # week-ends (sat+sun)

        if 'wochenende' in time_string or ('woche' in time_string and 'ende' in time_string):
            return self.get_weekend_range()

        # whole week

        if 'woche' in time_string:
            return self.get_week_range(time_string)

        # whole day for specific day

        if time_string == 'heute':
            return self.get_day_range(time.time(), 'Heute')

        if time_string == 'morgen':
            return self.get_day_range(time.time() + 1 * 24 * 60 * 60, 'Morgen')

        if time_string.endswith('bermorgen'):
            return self.get_day_range(time.time() + 2 * 24 * 60 * 60, 'Übermorgen')

        # hour range of specific day

        if contained_day_range_symbols:
            if 'bermorgen' in time_string:
                return self.get_subrange(time_string, time.time() + 2 * 24 * 60 * 60, 'Übermorgen')

            if 'morgen' in time_string:
                return self.get_subrange(time_string, time.time() + 1 * 24 * 60 * 60, 'Morgen')

            return self.get_subrange(time_string, time.time(), 'Heute')

        return ('currently', None, None, 'Jetzt')

    # -------------------------------------------------------------------------
    # timerange helpers
    
    def get_day_range(self, epoch, prefix):
        dt1 = datetime.fromtimestamp(epoch).replace(minute = 0, hour = 0, second = 0, microsecond= 0)
        dt2 = datetime.fromtimestamp(epoch).replace(minute = 59, hour = 23, second = 59, microsecond= 0)

        return ('daily', dt1.timestamp(), dt2.timestamp(), prefix)

    def get_subrange(self, time_string, epoch, prefix):
        if 'früh' in time_string:
            return self.get_hour_range(epoch, 6, 10, prefix + ' früh')

        if 'vormittag' in time_string:
            return self.get_hour_range(epoch, 9, 12, prefix + ' vormittag')

        if 'nachmittag' in time_string:
            return self.get_hour_range(epoch, 14, 17, prefix + ' nachmittag')

        if 'mittag' in time_string:
            return self.get_hour_range(epoch, 11, 14, prefix + ' mittag')

        if 'abend' in time_string:
            return self.get_hour_range(epoch, 17, 22, prefix + ' abend')

        if 'nacht' in time_string:
            return self.get_hour_range(epoch, 22, -1, prefix + ' nacht')

    def get_hour_range(self, epoch, hours_from, hours_to, prefix):
        dt1 = datetime.fromtimestamp(epoch).replace(minute = 0, hour = hours_from, second = 0, microsecond= 0)
        dt2 = dt1

        if hours_to == -1: # nasty, i know -> next day 3:00
            dt2 = datetime.fromtimestamp(epoch + 1 * 24 * 60 * 60).replace(minute = 0, hour = 3, second = 0, microsecond= 0)
        else:
            dt2 = datetime.fromtimestamp(epoch).replace(minute = 0, hour = hours_to, second = 0, microsecond= 0)

        return ('hourly', dt1.timestamp(), dt2.timestamp(), prefix)

    def get_weekend_range(self):
        dt = datetime.fromtimestamp(time.time()).replace(minute = 0, hour = 0, second = 0, microsecond = 0)
        offset = 5 - dt.weekday()

        dt1 = dt + timedelta(days = offset)
        dt2 = dt1 + timedelta(days = 1)

        return ('daily', dt1.timestamp(), dt2.timestamp(), "Am Wochenende")

    def get_week_range(self, time_string):
        dt = datetime.fromtimestamp(time.time()).replace(minute = 0, hour = 0, second = 0, microsecond = 0)

        monday = dt + timedelta(days = 0 - dt.weekday())
        sunday = monday + timedelta(days = 6)

        if 'nächste' in time_string:
            dt1 = monday + timedelta(days = 7)
            dt2 = sunday + timedelta(days = 7)

            return ('daily', dt1.timestamp(), dt2.timestamp(), "Nächste Woche")

        return ('daily', monday.timestamp(), sunday.timestamp(), "Diese Woche")

    def get_weekday(self, day):
        dt1 = datetime.fromtimestamp(time.time()).replace(minute = 0, hour = 0, second = 0, microsecond = 0)
        offset = day - dt1.weekday()

        if offset <= 0:
            offset = offset + 7

        dt1 = dt1 + timedelta(days = offset)
        dt2 = dt1.replace(minute = 59, hour = 23, second = 59, microsecond = 0)

        return ('daily', dt1.timestamp(), dt2.timestamp(), "am " + self.weekdays[day].capitalize())

    # -------------------------------------------------------------------------
    # done

    def done(self, hermes, intent_message, response):
        if not hermes or not intent_message:
            self.logger.error('Response: ' + response if response else '')
            return None

        hermes.publish_end_session(intent_message.session_id, response)

# -----------------------------------------------------------------------------
# main
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    app = App()

    # app.query_weather(None, None, "s710:getForecast", "Hamburg", "morgen nachmittag")
    # app.query_weather(None, None, "s710:getTemperature", None, "jetzt")
    # app.query_weather(None, None, "s710:hasSun", None, "übermorgen")
    # app.query_weather(None, None, "s710:hasSnow", "Helsinki", None)

