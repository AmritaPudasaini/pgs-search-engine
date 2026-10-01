"""Query normalization helpers for the search engine."""

import json
import logging
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

from nltk.stem import PorterStemmer

from pgs_search.query.translation import translate_to_english, translate_to_nepali

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")

_PLACE_MAP_FILE = Path(__file__).parent / "data" / "en_ne_places.json"
_NEPALI_PIPELINE_FILE = Path(__file__).parent / "nepali_lemma" / "nepali_hmm_pipeline.pkl"


@lru_cache(maxsize=1)
def get_place_map() -> dict[str, str]:
    with _PLACE_MAP_FILE.open(encoding="utf-8") as file:
        return json.load(file)


@lru_cache(maxsize=1)
def get_reverse_place_map() -> dict[str, str]:
    return {value: key for key, value in get_place_map().items()}


@lru_cache(maxsize=1)
def get_romanized_ne_words() -> frozenset[str]:
    return frozenset(get_place_map()) | {
        "namaste",
        "dhanyavad",
        "dhanyabad",
        "khana",
        "pani",
        "momo",
        "momos",
        "chowmein",
        "thakali",
        "newa",
        "sherpa",
        "tamang",
        "gurung",
        "magar",
        "limbu",
        "tharu",
        "nepali",
    }


@lru_cache(maxsize=1)
def get_nepali_pipeline():
    """Load the pickled Nepali lemmatization pipeline once and cache it."""
    import sys

    import joblib

    from pgs_search.query.nepali_lemma import nepali_pipeline as nepali_module

    sys.modules["nepali_pipeline"] = nepali_module
    return joblib.load(_NEPALI_PIPELINE_FILE)


def _is_latin_script(text: str) -> bool:
    latin = sum(1 for ch in text if _is_latin(ch))
    other = sum(1 for ch in text if not _is_latin(ch) and unicodedata.category(ch).startswith("L"))
    if latin + other == 0:
        return True
    return latin >= other


def _is_latin(ch: str) -> bool:
    try:
        return unicodedata.name(ch).startswith("LATIN")
    except ValueError:
        return False


def normalize_query(query: str) -> str:
    """Normalize a raw search query."""
    normalized = _WHITESPACE_RE.sub(" ", query.strip())
    normalized = unicodedata.normalize("NFC", normalized)
    if _is_latin_script(normalized):
        return normalized.lower()
    return normalized


def lemmatize_query(text: str) -> str:
    """Stem English words in a query, preserving non-Latin tokens.

    Nepali lemmatization is handled separately by lemmatize_nepali_query().
    Note: the reused Nepali pipeline also strips Nepali stopwords because
    NepaliStopWordRemover is already part of the pickled pipeline; that is a
    side effect of reusing the trained pipeline, not a new processing step.
    """
    stemmer = PorterStemmer()
    return " ".join(
        stemmer.stem(token) if _is_latin_script(token) else token
        for token in text.split()
    )


def lemmatize_nepali_query(text: str) -> list[str]:
    """Lemmatize a Nepali (Devanagari) query into lemma tokens.

    Returns an empty list for empty or non-Devanagari input.
    """
    if not text:
        return []
    if not _DEVANAGARI_RE.search(text):
        return []
    sentences = get_nepali_pipeline().transform([text])
    if not sentences:
        return []
    first = sentences[0]
    if not isinstance(first, list):
        return []
    return [str(token) for token in first]


def lemmatize(text: str) -> list[str]:
    """Lemmatize a query, dispatching by script.

    Latin-script text is handled by the English Porter stemmer; Devanagari
    text by the Nepali lemmatization pipeline.
    """
    if not text.strip():
        return []
    if _DEVANAGARI_RE.search(text) and not _is_latin_script(text):
        return lemmatize_nepali_query(text)
    if _is_latin_script(text):
        return [lemmatize_query(text)]
    return []


def detect_language(query: str) -> str:
    """Detect the language used by a search query."""
    text = normalize_query(query)
    if not text:
        return "unknown"

    has_latin = any(_is_latin(ch) for ch in text)
    has_devanagari = bool(_DEVANAGARI_RE.search(text))

    if has_latin and has_devanagari:
        return "mixed"
    if has_devanagari:
        return "ne"
    if not has_latin:
        return "unknown"

    if _is_romanized_nepali(text):
        return "ne"
    return "en"


def _is_romanized_nepali(text: str) -> bool:
    if text in get_place_map() or text in get_romanized_ne_words():
        return True
    tokens = text.split()
    return bool(tokens) and all(token in get_romanized_ne_words() for token in tokens)


def _translate_query(query: str, language: str) -> str:
    """Translate the full original query into the other language.

    Only unambiguous single-language queries are translated; "mixed" and
    "unknown" queries are left alone. Each direction is guarded separately so a
    translation failure degrades to an empty result instead of propagating.
    """
    if language == "en":
        try:
            return translate_to_nepali(query)
        except Exception:
            logger.warning("Nepali translation failed for query: %s", query, exc_info=True)
    elif language == "ne":
        try:
            return translate_to_english(query)
        except Exception:
            logger.warning("English translation failed for query: %s", query, exc_info=True)
    return ""


def expand_query_terms(query: str) -> list[str]:
    """Expand a query into search terms and variants."""
    normalized = normalize_query(query)
    terms = [normalized]
    lemma_variant = " ".join(lemmatize(normalized))
    if lemma_variant and lemma_variant != normalized:
        terms.append(lemma_variant)
    place_map = get_place_map()
    reverse_place_map = get_reverse_place_map()
    candidates = [normalized, lemma_variant, *normalized.split()]
    for candidate in candidates:
        equivalent = place_map.get(candidate) or reverse_place_map.get(candidate)
        if equivalent:
            terms.append(equivalent)
    translated = _translate_query(query, detect_language(query))
    if translated:
        terms.append(translated)
    return list(dict.fromkeys(terms))
