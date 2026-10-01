"""English <-> Nepali translation helpers built on NLLB-200.

Used by query expansion in `pgs_search.query.normalizer.expand_query_terms` to
add a cross-language variant of single-language queries. Not wired into
retrieval, ranking, or indexing.
"""

from functools import lru_cache

import torch
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

MODEL_NAME = "facebook/nllb-200-distilled-600M"
NEPALI_LANG_CODE = "npi_Deva"
ENGLISH_LANG_CODE = "eng_Latn"
MAX_TOKENS = 256


@lru_cache(maxsize=1)
def get_model_and_tokenizer() -> tuple[AutoModelForSeq2SeqLM, AutoTokenizer]:
    """Load the NLLB model and tokenizer once and cache them."""
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_NAME)
    model.eval()
    return model, tokenizer


def _translate(text: str, source_lang_code: str, target_lang_code: str) -> str:
    """Translate text between two NLLB language codes.

    The tokenizer is shared and cached, so src_lang is always set explicitly
    for the requested source language rather than relying on whatever the
    previous call left behind.
    """
    model, tokenizer = get_model_and_tokenizer()
    tokenizer.src_lang = source_lang_code
    inputs = tokenizer(text, return_tensors="pt")
    forced_bos_token_id = tokenizer.convert_tokens_to_ids(target_lang_code)
    with torch.inference_mode():
        output = model.generate(
            **inputs,
            forced_bos_token_id=forced_bos_token_id,
            max_length=MAX_TOKENS,
        )
    return tokenizer.batch_decode(output, skip_special_tokens=True)[0].strip()


def translate_to_nepali(text: str) -> str:
    """Translate an English sentence into Nepali (Devanagari)."""
    return _translate(text, ENGLISH_LANG_CODE, NEPALI_LANG_CODE)


def translate_to_english(text: str) -> str:
    """Translate a Nepali (Devanagari) sentence into English."""
    return _translate(text, NEPALI_LANG_CODE, ENGLISH_LANG_CODE)
