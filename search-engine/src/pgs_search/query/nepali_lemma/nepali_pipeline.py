import json
import math
import re
from collections import defaultdict
from pathlib import Path
from sklearn.base import BaseEstimator, TransformerMixin

LEMMA_DICT_PATH = Path(__file__).resolve().parent / "nepali_lemma_dict.json"


def load_lemma_dict(path: Path = LEMMA_DICT_PATH) -> dict:
    """Flatten the categorized word->lemma dictionary (pronouns/irregular_verbs/verbs) into one lookup."""
    with open(path, encoding="utf-8") as fh:
        categories = json.load(fh)
    flat = {}
    for mapping in categories.values():
        flat.update(mapping)
    return flat

# 1. Stop Words Definition
NEPALI_STOP_WORDS = set([
    "म", "मेरो", "मलाई", "हामी", "हाम्रो", "हामीलाई", "तँ", "तँलाई", "तेरो", "तिमी", "तिम्रो", "तिमीलाई", "तपाईं", "तपाईंको", "तपाईंलाई", "उ", "उसको", "उसलाई", "उसले", "उनी", "उनको", "उनलाई", "उनले", "उनीहरु", "उनीहरुको", "उनीहरुलाई", "यिनीहरु", "तिनीहरु", "आफू", "आफ्नो",
    "र", "पनि", "तर", "कि", "वा", "अथवा", "तथा", "भने", "यदि", "यद्यपि", "तथापि", "किनभने", "किनकि", "बरु", "त्यसैले", "तसर्थ", "अतः",
    "को", "का", "की", "लाई", "ले", "बाट", "द्वारा", "मा", "माथि", "तल", "भित्र", "बाहिर", "सँग", "सित", "बिना", "बाहेक", "लागि", "निम्ति", "तर्फ", "तिर", "भन्दा",
    "छ", "छन्", "छु", "छौं", "छस्", "छौ", "हो", "हुन्", "हुँ", "हौं", "होस्", "हौ", "थियो", "थिए", "थिइन्", "थिएँ", "थियौं", "हुनेछ", "भयो", "भए", "भएन", "गर्छ", "गर्छन्", "गर्छु", "गर्छौं",
    "के", "को", "कुन", "किन", "कसरी", "कस्तो", "कहाँ", "कहिले", "कति", "कसको", "कसलाई", "कसले",
    "अझै", "अधिक", "अन्य", "अन्यत्र", "अन्यथा", "अब", "अरु", "अर्को", "अर्थात्", "अलग", "आज", "हिजो", "भोलि", "अघि", "पछि", "सधैं", "कहिल्यै", "अक्सर", "धेरै", "थोरै", "कम", "सबै", "केही", "कोही", "जहाँ", "त्यहाँ", "यहाँ", "यसो", "त्यसो", "यस्तो", "त्यस्तो", "जस्तो", "उस्तो",
    "यस", "त्यस", "यी", "ती", "जुन", "कुरा", "एकदम", "ज्यादै", "अति", "अनि", "लौ", "पो", "नि", "त", "नै", "मात्र", "भरि", "सम्म", "एउटा", "दुइटा", "आदि", "इत्यादि"
])


class NepaliLexicalAnalyzer(BaseEstimator, TransformerMixin):
    def fit(self, X, y=None):
        self.fitted_ = True
        return self

    def transform(self, X, y=None):
        tokenized_documents = []
        for sentence in X:
            tokens = re.findall(r'[^\s।,\.!?;:()\'"“”]+', sentence)
            tokenized_documents.append(tokens)
        return tokenized_documents


class NepaliHeuristicDatasetGenerator(BaseEstimator, TransformerMixin):
    def __init__(self):
        # Large word->lemma dictionary (verbs conjugations, pronoun case-forms)
        # checked before falling back to the suffix-stripping heuristics below.
        self.lemma_dict = load_lemma_dict()
        self.irregulars = {
            "छ": "हुनु", "छन्": "हुनु", "हो": "हुनु", "हुन्": "हुनु",
            "भयो": "हुनु", "भए": "हुनु", "हुन्छ": "हुनु", "थियो": "हुनु",
            "गयो": "जानु", "गए": "जानु", "जान्छ": "जानु", "गएको": "जानु",
            "आयो": "आउनु", "आए": "आउनु", "आउँछ": "आउनु"
        }
        self.noun_suffixes = [
            "हरुलाई", "हरुले", "हरुको", "हरुबाट", "हरुमा", "हरुका", "हरुकी",
            "हरु", "लाई", "बाट", "देखि", "द्वारा", "सम्म",
            "ले", "को", "का", "की", "मा"
        ]
        self.verb_endings = [
            "ँदैछ", "ँदैछन्", "न्छन्", "ेका", "ेको", "ेकी",
            "छन्", "न्छ", "यौं", "यो", "ौं", "नेछ"
        ]

    def fit(self, X, y=None):
        return self

    def _lemmatize_word(self, word: str) -> str:
        if word in self.lemma_dict:
            return self.lemma_dict[word]

        if word in self.irregulars:
            return self.irregulars[word]

        original_length = len(word)
        for suffix in self.noun_suffixes:
            if word.endswith(suffix) and original_length > len(suffix) + 2:
                return word[:-len(suffix)]

        for ending in self.verb_endings:
            if word.endswith(ending) and original_length > len(ending) + 1:
                base = word[:-len(ending)]
                if base.endswith("्"):
                    base = base[:-1]
                return base + "नु"

        return word

    def transform(self, X, y=None):
        X_train_words = []
        y_train_lemmas = []

        for essay in X:
            sentences = re.split(r'[।\?\!]', essay)
            for sentence in sentences:
                sentence = sentence.strip()
                if not sentence: continue

                words = re.findall(r'[^\s।,\.!?;:()\'"“”]+', sentence)
                if not words: continue

                lemmas = [self._lemmatize_word(w) for w in words]
                X_train_words.append(words)
                y_train_lemmas.append(lemmas)

        return X_train_words, y_train_lemmas


def return_neg_inf():
    return float('-inf')


def return_inner_dict():
    return defaultdict(return_neg_inf)


class NepaliHMMLemmatizer(BaseEstimator, TransformerMixin):
    def __init__(self):
        # Now these use standard functions, making them 100% picklable!
        self.transition_probs = defaultdict(return_inner_dict)
        self.emission_probs = defaultdict(return_inner_dict)
        self.start_probs = defaultdict(return_neg_inf)

        self.word_to_known_lemmas = defaultdict(set)
        self.UNSEEN_LOG_PROB = -20.0

        # Consulted as a fallback for words never seen during training, so
        # OOV words with a known dictionary lemma don't fall through to the
        # crude हरु/ले/को suffix-stripping below.
        self.lemma_dict = load_lemma_dict()

    def fit(self, X, y):
        start_counts = defaultdict(int)
        transition_counts = defaultdict(lambda: defaultdict(int))
        emission_counts = defaultdict(lambda: defaultdict(int))
        lemma_counts = defaultdict(int)

        for doc_tokens, doc_lemmas in zip(X, y):
            if not doc_tokens: continue
            start_counts[doc_lemmas[0]] += 1

            for i in range(len(doc_tokens)):
                word = doc_tokens[i]
                lemma = doc_lemmas[i]
                emission_counts[lemma][word] += 1
                lemma_counts[lemma] += 1
                self.word_to_known_lemmas[word].add(lemma)

                if i > 0:
                    prev_lemma = doc_lemmas[i-1]
                    transition_counts[prev_lemma][lemma] += 1

        total_sentences = len(X)
        for lemma, count in start_counts.items():
            self.start_probs[lemma] = math.log(count / total_sentences)

        for prev_lemma, next_lemmas in transition_counts.items():
            total_transitions = sum(next_lemmas.values())
            for next_lemma, count in next_lemmas.items():
                self.transition_probs[prev_lemma][next_lemma] = math.log(count / total_transitions)

        for lemma, words in emission_counts.items():
            total_emissions = lemma_counts[lemma]
            for word, count in words.items():
                self.emission_probs[lemma][word] = math.log(count / total_emissions)

        return self

    def transform(self, X, y=None):
        lemmatized_documents = []
        for doc_tokens in X:
            if not doc_tokens:
                lemmatized_documents.append([])
                continue
            lemmatized_documents.append(self._viterbi(doc_tokens))
        return lemmatized_documents

    def _viterbi(self, tokens):
        viterbi = []
        first_word = tokens[0]
        candidates = self._get_candidates(first_word)
        step_0 = {}
        for state in candidates:
            start_p = self.start_probs.get(state, self.UNSEEN_LOG_PROB)
            emit_p = self.emission_probs.get(state, {}).get(first_word, self.UNSEEN_LOG_PROB)
            step_0[state] = (start_p + emit_p, None)
        viterbi.append(step_0)

        for t in range(1, len(tokens)):
            word = tokens[t]
            candidates = self._get_candidates(word)
            current_step = {}
            for state in candidates:
                max_tr_prob = float('-inf')
                best_prev_state = None
                for prev_state, (prev_prob, _) in viterbi[t-1].items():
                    trans_p = self.transition_probs.get(prev_state, {}).get(state, self.UNSEEN_LOG_PROB)
                    prob = prev_prob + trans_p
                    if prob > max_tr_prob:
                        max_tr_prob = prob
                        best_prev_state = prev_state
                emit_p = self.emission_probs.get(state, {}).get(word, self.UNSEEN_LOG_PROB)
                current_step[state] = (max_tr_prob + emit_p, best_prev_state)
            viterbi.append(current_step)

        best_final_state = max(viterbi[-1].keys(), key=lambda k: viterbi[-1][k][0])
        sequence = []
        current_state = best_final_state
        for t in range(len(viterbi) - 1, -1, -1):
            sequence.append(current_state)
            current_state = viterbi[t][current_state][1]

        sequence.reverse()
        return sequence

    def _get_candidates(self, word):
        if word in self.word_to_known_lemmas:
            return self.word_to_known_lemmas[word]
        if word in self.lemma_dict:
            return {self.lemma_dict[word]}
        root = word
        if word.endswith("हरु"): root = word[:-3]
        elif word.endswith("ले") or word.endswith("को"): root = word[:-2]
        return {root}


class NepaliStopWordRemover(BaseEstimator, TransformerMixin):
    def __init__(self, stop_words):
        self.stop_words = set(stop_words)

    def fit(self, X, y=None):
        self.fitted_ = True
        return self

    def transform(self, X, y=None):
        filtered_documents = []
        for doc_lemmas in X:
            filtered_tokens = [lemma for lemma in doc_lemmas if lemma not in self.stop_words]
            filtered_documents.append(filtered_tokens)
        return filtered_documents
