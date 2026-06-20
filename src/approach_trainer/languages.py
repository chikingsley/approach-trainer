"""Canonical language reference for the providers Superwhisper routes to.

The pain this solves: the cloud STT providers each accept a specific set of
language codes, and guessing (e.g. ``cmn`` vs ``zho`` for Mandarin) wastes a
400 every time. This module bakes in the authoritative supported set so callers
resolve a human name / ISO-639-1 / ISO-639-3 to the exact code a provider wants.

Source of truth: ElevenLabs Scribe v1/v2 supported languages (ISO-639-3), per
https://elevenlabs.io/docs/overview/capabilities/speech-to-text
(the exact set is ``ELEVENLABS_SCRIBE`` below).

Usage::

    from approach_trainer.languages import scribe_code, language_name, script_of
    scribe_code("Mandarin Chinese")  # -> "zho"   (NOT "cmn")
    scribe_code("zh")         # -> "zho"
    scribe_code("Russian")    # -> "rus"
    language_name("fas")      # -> "Persian"
    script_of("rus")          # -> "Cyrillic"
"""

from __future__ import annotations

from dataclasses import dataclass

# ISO-639-3 code -> English name. The exact set ElevenLabs Scribe accepts as its
# `language_code`. ISO-639-3 is also what the audio CLI's --language hint expects.
SCRIBE_NAMES: dict[str, str] = {
    "afr": "Afrikaans", "amh": "Amharic", "ara": "Arabic", "hye": "Armenian",
    "asm": "Assamese", "ast": "Asturian", "aze": "Azerbaijani", "bel": "Belarusian",
    "ben": "Bengali", "bos": "Bosnian", "bul": "Bulgarian", "mya": "Burmese",
    "yue": "Cantonese", "cat": "Catalan", "ceb": "Cebuano", "nya": "Chichewa",
    "hrv": "Croatian", "ces": "Czech", "dan": "Danish", "nld": "Dutch",
    "eng": "English", "est": "Estonian", "fil": "Filipino", "fin": "Finnish",
    "fra": "French", "ful": "Fulah", "glg": "Galician", "lug": "Ganda",
    "kat": "Georgian", "deu": "German", "ell": "Greek", "guj": "Gujarati",
    "hau": "Hausa", "heb": "Hebrew", "hin": "Hindi", "hun": "Hungarian",
    "isl": "Icelandic", "ibo": "Igbo", "ind": "Indonesian", "gle": "Irish",
    "ita": "Italian", "jpn": "Japanese", "jav": "Javanese", "kea": "Kabuverdianu",
    "kan": "Kannada", "kaz": "Kazakh", "khm": "Khmer", "kor": "Korean",
    "kur": "Kurdish", "kir": "Kyrgyz", "lao": "Lao", "lav": "Latvian",
    "lin": "Lingala", "lit": "Lithuanian", "luo": "Luo", "ltz": "Luxembourgish",
    "mkd": "Macedonian", "msa": "Malay", "mal": "Malayalam", "mlt": "Maltese",
    "zho": "Mandarin Chinese", "mri": "Maori", "mar": "Marathi", "mon": "Mongolian",
    "nep": "Nepali", "nso": "Northern Sotho", "nor": "Norwegian", "oci": "Occitan",
    "ori": "Odia", "pus": "Pashto", "fas": "Persian", "pol": "Polish",
    "por": "Portuguese", "pan": "Punjabi", "ron": "Romanian", "rus": "Russian",
    "srp": "Serbian", "sna": "Shona", "snd": "Sindhi", "slk": "Slovak",
    "slv": "Slovenian", "som": "Somali", "spa": "Spanish", "swa": "Swahili",
    "swe": "Swedish", "tam": "Tamil", "tgk": "Tajik", "tel": "Telugu",
    "tha": "Thai", "tur": "Turkish", "ukr": "Ukrainian", "umb": "Umbundu",
    "urd": "Urdu", "uzb": "Uzbek", "vie": "Vietnamese", "cym": "Welsh",
    "wol": "Wolof", "xho": "Xhosa", "yor": "Yoruba", "zul": "Zulu",
}

# Dominant writing system per language, useful for formatting/transliteration hints.
# Anything not listed defaults to "Latin".
_SCRIPT_GROUPS: dict[str, tuple[str, ...]] = {
    "Cyrillic": ("rus", "ukr", "bul", "srp", "mkd", "bel", "kaz", "kir", "mon", "tgk"),
    "Arabic": ("ara", "fas", "urd", "pus", "snd", "kur"),
    "Devanagari": ("hin", "mar", "nep"),
    "Han": ("zho", "yue"),
    "Bengali": ("ben", "asm"),
    "Japanese": ("jpn",), "Hangul": ("kor",), "Greek": ("ell",), "Hebrew": ("heb",),
    "Armenian": ("hye",), "Georgian": ("kat",), "Thai": ("tha",), "Lao": ("lao",),
    "Khmer": ("khm",), "Myanmar": ("mya",), "Ethiopic": ("amh",), "Tamil": ("tam",),
    "Telugu": ("tel",), "Kannada": ("kan",), "Malayalam": ("mal",), "Gujarati": ("guj",),
    "Gurmukhi": ("pan",), "Odia": ("ori",),
}
_SCRIPT_OF: dict[str, str] = {
    code: script for script, codes in _SCRIPT_GROUPS.items() for code in codes
}

# ISO-639-1 (2-letter) -> ISO-639-3, for the languages where a 639-1 exists.
# Lets callers pass the common short codes (en, ru, zh, es, fa, ...).
_ISO1_TO_3: dict[str, str] = {
    "af": "afr", "am": "amh", "ar": "ara", "hy": "hye", "as": "asm", "az": "aze",
    "be": "bel", "bn": "ben", "bs": "bos", "bg": "bul", "my": "mya", "ca": "cat",
    "ny": "nya", "hr": "hrv", "cs": "ces", "da": "dan", "nl": "nld", "en": "eng",
    "et": "est", "fi": "fin", "fr": "fra", "ff": "ful", "gl": "glg", "lg": "lug",
    "ka": "kat", "de": "deu", "el": "ell", "gu": "guj", "ha": "hau", "he": "heb",
    "hi": "hin", "hu": "hun", "is": "isl", "ig": "ibo", "id": "ind", "ga": "gle",
    "it": "ita", "ja": "jpn", "jv": "jav", "kn": "kan", "kk": "kaz", "km": "khm",
    "ko": "kor", "ku": "kur", "ky": "kir", "lo": "lao", "lv": "lav", "ln": "lin",
    "lt": "lit", "lb": "ltz", "mk": "mkd", "ms": "msa", "ml": "mal", "mt": "mlt",
    "zh": "zho", "mi": "mri", "mr": "mar", "mn": "mon", "ne": "nep", "no": "nor",
    "oc": "oci", "or": "ori", "ps": "pus", "fa": "fas", "pl": "pol", "pt": "por",
    "pa": "pan", "ro": "ron", "ru": "rus", "sr": "srp", "sn": "sna", "sd": "snd",
    "sk": "slk", "sl": "slv", "so": "som", "es": "spa", "sw": "swa", "sv": "swe",
    "ta": "tam", "tg": "tgk", "te": "tel", "th": "tha", "tr": "tur", "uk": "ukr",
    "ur": "urd", "uz": "uzb", "vi": "vie", "cy": "cym", "wo": "wol", "xh": "xho",
    "yo": "yor", "zu": "zul",
}

@dataclass(frozen=True)
class Language:
    """A language with the codes/script callers need."""

    name: str
    iso639_3: str
    iso639_1: str | None
    script: str


_ISO3_TO_1: dict[str, str] = {v: k for k, v in _ISO1_TO_3.items()}


def _build() -> dict[str, Language]:
    out = {}
    for code, name in SCRIBE_NAMES.items():
        out[code] = Language(
            name=name,
            iso639_3=code,
            iso639_1=_ISO3_TO_1.get(code),
            script=_SCRIPT_OF.get(code, "Latin"),
        )
    return out


#: ISO-639-3 code -> Language, for every language ElevenLabs Scribe supports.
LANGUAGES: dict[str, Language] = _build()

#: Codes accepted by ElevenLabs Scribe (its `language_code` parameter).
ELEVENLABS_SCRIBE: frozenset[str] = frozenset(SCRIBE_NAMES)


def resolve(query: str) -> Language:
    """Resolve an exact language name / ISO-639-1 / ISO-639-3 to a Language.

    Raises ValueError (listing close options) if the language is not supported.
    """
    q = query.strip().lower()
    if q in LANGUAGES:
        return LANGUAGES[q]
    if q in _ISO1_TO_3:
        return LANGUAGES[_ISO1_TO_3[q]]
    for lang in LANGUAGES.values():
        if lang.name.lower() == q:
            return lang
    hits = sorted(c for c, lang in LANGUAGES.items() if q in lang.name.lower())
    hint = f" Did you mean: {', '.join(hits)}?" if hits else ""
    raise ValueError(f"Unsupported/unknown language {query!r}.{hint}")


def scribe_code(query: str) -> str:
    """ISO-639-3 code to pass to Scribe's --language / language_code."""
    return resolve(query).iso639_3


def language_name(query: str) -> str:
    """English language name (for compile_down's ``language=``)."""
    return resolve(query).name


def script_of(query: str) -> str:
    """Dominant script name for a supported language."""
    return resolve(query).script
