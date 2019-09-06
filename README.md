# Snips + DarkSky Weather

App zur Abfrage von Wetterinformationen von DarkSky (www.darksky.net). Es sind Abfragen bis zu 7 Tage in die Zukunft möglich.

## Installation

#### 1) DarkSky API Key

Für die Nutzung der API von DarkSky ist ein API-Key nötig, welcher kostenlos bei Registrierung erhältlich ist. Registrierung unter: https://darksky.net/dev

In der kostenlosen Version sind 1000 Aufrufe pro Tag möglich.

#### 2) Installation der Snips-App

Installation der Weather App aus dem Store: https://console.snips.ai/store/de/XXXXXXXXXX

#### 3) Assistant via `sam` installieren/aktualisieren

# Parameter

Die App bentöigt die folgenden Parameter:

- `api_key`: Der in Installation/1) erstellte API-Key von DarkSky
- `homecity`: Die Stadt für die Wetter abgefragt wird, wenn kein Ort genannt wird ("Wie wird das Wetter morgen?")

# Funktionen

Die App umfasst folgende Intents:

- `s710:getForecast` - Wetterbericht für einen Zeitpunkt/Ort abfragen
- `s710:getTemperature` - Temperatur für einen Zeitpunkt/Ort abfragen
- `s710:hasRain` - Abfragen ob es zu einem Zeitpunkt/an einem Ort regnet/regnen wird
- `s710:hasSun` - Abfragen ob es zu einem Zeitpunkt/an einem Ort sonnig ist/sonnig wird
- `s710:hasSnow` - Abfragen ob es zu einem Zeitpunkt/an einem Ort schneit/schneien wird

Die Angabe des Orts und der Zeit ist optional. Ohne Angabe einer Zeit gilt "jetzt", ohne Angabe des Ortes wird  `homecity` verwendet.

Folgende Zeitbereiche sind abfragbar:

- aktueller Zeitpunkt ('jetzt', 'gerade', ...)
- Zeitraum an einem Tag ('Morgen früh', 'heute Abend', 'übermorgen Nachmittag', ...)
- einzelner Tag ('heute', 'morgen', 'Dienstag', ...)
- Wochenende ('am Wochenende')
- Mehrere Tage ('diese Woche', 'nächste Woche')

Bei der Abfrage von ganzen Zeitbereichen versucht die App die Wetterinformationen so gut als möglich zu beschreiben. Bei der Abfrage einzelner Tage/des aktuellen Zeitpunkts wird als Wetterbericht die Summary von DarkSky verwendet.
Bei der Abfrage des Wochenendes wird die Summary von DarkSky für Samstag und Sonntag verwendet.
