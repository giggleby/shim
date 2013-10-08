#!/usr/bin/env python
# pylint: disable=C0301
#
# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# This is a required test to check all VPD related information.


"""Collection of valid VPD values for ChromeOS."""

# keyboard_layout:https://code.google.com/p/chromium/codesearch#chromium/src/chromeos/ime/input_methods.txt&q=input_methods.txt&sq=package:chromium&type=cs
KEYBOARD_LAYOUT = [
  'xkb:us::eng',
  'xkb:us:intl:eng',
  'xkb:us:altgr-intl:eng',
  'xkb:us:dvorak:eng',
  'xkb:us:colemak:eng',
  'xkb:be::nld',
  'xkb:fr::fra',
  'xkb:be::fra',
  'xkb:ca::fra',
  'xkb:ch:fr:fra',
  'xkb:ca:multix:fra',
  'xkb:de::ger',
  'xkb:de:neo:ger',
  'xkb:be::ger',
  'xkb:ch::ger',
  'xkb:jp::jpn',
  'xkb:ru::rus',
  'xkb:ru:phonetic:rus',
  'xkb:br::por',
  'xkb:bg::bul',
  'xkb:bg:phonetic:bul',
  'xkb:ca:eng:eng',
  'xkb:cz::cze',
  'xkb:cz:qwerty:cze',
  'xkb:ee::est',
  'xkb:es::spa',
  'xkb:es:cat:cat',
  'xkb:dk::dan',
  'xkb:gr::gre',
  'xkb:il::heb',
  'xkb:latam::spa',
  'xkb:lt::lit',
  'xkb:lv:apostrophe:lav',
  'xkb:hr::scr',
  'xkb:gb:extd:eng',
  'xkb:gb:dvorak:eng',
  'xkb:fi::fin',
  'xkb:hu::hun',
  'xkb:it::ita',
  'xkb:is::ice',
  'xkb:no::nob',
  'xkb:pl::pol',
  'xkb:pt::por',
  'xkb:ro::rum',
  'xkb:se::swe',
  'xkb:sk::slo',
  'xkb:si::slv',
  'xkb:rs::srp',
  'xkb:tr::tur',
  'xkb:ua::ukr',
  'xkb:by::bel',
  'xkb:am:phonetic:arm',
  'xkb:ge::geo',
  'xkb:mn::mon',
  ]

# initial_locale: https://code.google.com/p/chromium/codesearch#chromium/src/ui/base/l10n/l10n_util.cc&q=l10n_util.cc&sq=package:chromium&type=cs
INITIAL_LOCALE = [
  "af",     # Afrikaans
  "am",     # Amharic
  "ar",     # Arabic
  "az",     # Azerbaijani
  "be",     # Belarusian
  "bg",     # Bulgarian
  "bh",     # Bihari
  "bn",     # Bengali
  "br",     # Breton
  "bs",     # Bosnian
  "ca",     # Catalan
  "co",     # Corsican
  "cs",     # Czech
  "cy",     # Welsh
  "da",     # Danish
  "de",     # German
  "de-AT",  # German (Austria)
  "de-CH",  # German (Switzerland)
  "de-DE",  # German (Germany)
  "el",     # Greek
  "en",     # English
  "en-AU",  # English (Australia)
  "en-CA",  # English (Canada)
  "en-GB",  # English (UK)
  "en-NZ",  # English (New Zealand)
  "en-US",  # English (US)
  "en-ZA",  # English (South Africa)
  "eo",     # Esperanto
  "es",     # Spanish
  "es-419", # Spanish (Latin America)
  "et",     # Estonian
  "eu",     # Basque
  "fa",     # Persian
  "fi",     # Finnish
  "fil",    # Filipino
  "fo",     # Faroese
  "fr",     # French
  "fr-CA",  # French (Canada)
  "fr-CH",  # French (Switzerland)
  "fr-FR",  # French (France)
  "fy",     # Frisian
  "ga",     # Irish
  "gd",     # Scots Gaelic
  "gl",     # Galician
  "gn",     # Guarani
  "gu",     # Gujarati
  "ha",     # Hausa
  "haw",    # Hawaiian
  "he",     # Hebrew
  "hi",     # Hindi
  "hr",     # Croatian
  "hu",     # Hungarian
  "hy",     # Armenian
  "ia",     # Interlingua
  "id",     # Indonesian
  "is",     # Icelandic
  "it",     # Italian
  "it-CH",  # Italian (Switzerland)
  "it-IT",  # Italian (Italy)
  "ja",     # Japanese
  "jw",     # Javanese
  "ka",     # Georgian
  "kk",     # Kazakh
  "km",     # Cambodian
  "kn",     # Kannada
  "ko",     # Korean
  "ku",     # Kurdish
  "ky",     # Kyrgyz
  "la",     # Latin
  "ln",     # Lingala
  "lo",     # Laothian
  "lt",     # Lithuanian
  "lv",     # Latvian
  "mk",     # Macedonian
  "ml",     # Malayalam
  "mn",     # Mongolian
  "mo",     # Moldavian
  "mr",     # Marathi
  "ms",     # Malay
  "mt",     # Maltese
  "nb",     # Norwegian (Bokmal)
  "ne",     # Nepali
  "nl",     # Dutch
  "nn",     # Norwegian (Nynorsk)
  "no",     # Norwegian
  "oc",     # Occitan
  "om",     # Oromo
  "or",     # Oriya
  "pa",     # Punjabi
  "pl",     # Polish
  "ps",     # Pashto
  "pt",     # Portuguese
  "pt-BR",  # Portuguese (Brazil)
  "pt-PT",  # Portuguese (Portugal)
  "qu",     # Quechua
  "rm",     # Romansh
  "ro",     # Romanian
  "ru",     # Russian
  "sd",     # Sindhi
  "sh",     # Serbo-Croatian
  "si",     # Sinhalese
  "sk",     # Slovak
  "sl",     # Slovenian
  "sn",     # Shona
  "so",     # Somali
  "sq",     # Albanian
  "sr",     # Serbian
  "st",     # Sesotho
  "su",     # Sundanese
  "sv",     # Swedish
  "sw",     # Swahili
  "ta",     # Tamil
  "te",     # Telugu
  "tg",     # Tajik
  "th",     # Thai
  "ti",     # Tigrinya
  "tk",     # Turkmen
  "to",     # Tonga
  "tr",     # Turkish
  "tt",     # Tatar
  "tw",     # Twi
  "ug",     # Uighur
  "uk",     # Ukrainian
  "ur",     # Urdu
  "uz",     # Uzbek
  "vi",     # Vietnamese
  "xh",     # Xhosa
  "yi",     # Yiddish
  "yo",     # Yoruba
  "zh",     # Chinese
  "zh-CN",  # Chinese (Simplified)
  "zh-TW",  # Chinese (Traditional)
  "zu",     # Zulu
  ]

# initial_timezone: http://git.chromium.org/gitweb/?p=chromium.git;a=blob;f=chrome/browser/chromeos/system/timezone_settings.cc
INITIAL_TIMEZONE = [
  "Pacific/Midway",
  "Pacific/Honolulu",
  "America/Anchorage",
  "America/Los_Angeles",
  "America/Vancouver",
  "America/Tijuana",
  "America/Phoenix",
  "America/Denver",
  "America/Edmonton",
  "America/Chihuahua",
  "America/Regina",
  "America/Costa_Rica",
  "America/Chicago",
  "America/Mexico_City",
  "America/Winnipeg",
  "America/Bogota",
  "America/New_York",
  "America/Toronto",
  "America/Caracas",
  "America/Barbados",
  "America/Halifax",
  "America/Manaus",
  "America/Santiago",
  "America/St_Johns",
  "America/Sao_Paulo",
  "America/Araguaina",
  "America/Argentina/Buenos_Aires",
  "America/Argentina/San_Luis",
  "America/Montevideo",
  "America/Godthab",
  "Atlantic/South_Georgia",
  "Atlantic/Cape_Verde",
  "Atlantic/Azores",
  "Africa/Casablanca",
  "Europe/London",
  "Europe/Dublin",
  "Europe/Amsterdam",
  "Europe/Belgrade",
  "Europe/Berlin",
  "Europe/Brussels",
  "Europe/Madrid",
  "Europe/Paris",
  "Europe/Rome",
  "Europe/Stockholm",
  "Europe/Sarajevo",
  "Europe/Vienna",
  "Europe/Warsaw",
  "Europe/Zurich",
  "Africa/Windhoek",
  "Africa/Lagos",
  "Africa/Brazzaville",
  "Africa/Cairo",
  "Africa/Harare",
  "Africa/Maputo",
  "Africa/Johannesburg",
  "Europe/Helsinki",
  "Europe/Athens",
  "Asia/Amman",
  "Asia/Beirut",
  "Asia/Jerusalem",
  "Europe/Minsk",
  "Asia/Baghdad",
  "Asia/Riyadh",
  "Asia/Kuwait",
  "Africa/Nairobi",
  "Asia/Tehran",
  "Europe/Moscow",
  "Asia/Dubai",
  "Asia/Tbilisi",
  "Indian/Mauritius",
  "Asia/Baku",
  "Asia/Yerevan",
  "Asia/Kabul",
  "Asia/Karachi",
  "Asia/Ashgabat",
  "Asia/Oral",
  "Asia/Calcutta",
  "Asia/Colombo",
  "Asia/Katmandu",
  "Asia/Yekaterinburg",
  "Asia/Almaty",
  "Asia/Dhaka",
  "Asia/Rangoon",
  "Asia/Bangkok",
  "Asia/Jakarta",
  "Asia/Omsk",
  "Asia/Novosibirsk",
  "Asia/Shanghai",
  "Asia/Hong_Kong",
  "Asia/Kuala_Lumpur",
  "Asia/Singapore",
  "Asia/Manila",
  "Asia/Taipei",
  "Asia/Makassar",
  "Asia/Krasnoyarsk",
  "Australia/Perth",
  "Australia/Eucla",
  "Asia/Irkutsk",
  "Asia/Seoul",
  "Asia/Tokyo",
  "Asia/Jayapura",
  "Australia/Adelaide",
  "Australia/Darwin",
  "Australia/Brisbane",
  "Australia/Hobart",
  "Australia/Sydney",
  "Asia/Yakutsk",
  "Pacific/Guam",
  "Pacific/Port_Moresby",
  "Asia/Vladivostok",
  "Asia/Sakhalin",
  "Asia/Magadan",
  "Pacific/Auckland",
  "Pacific/Fiji",
  "Pacific/Majuro",
  "Pacific/Tongatapu",
  "Pacific/Apia",
  "Pacific/Kiritimati",
  ]

KNOWN_VPD_FIELD_DATA = {
  'keyboard_layout': KEYBOARD_LAYOUT,
  'initial_locale': INITIAL_LOCALE,
  'initial_timezone': INITIAL_TIMEZONE,
  }
