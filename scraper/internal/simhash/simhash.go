// Package simhash implements Charikar's simhash algorithm for near-duplicate
// text detection: two documents that differ only slightly (a timestamp, an
// ad slot, a view counter) produce fingerprints with a small Hamming
// distance, unlike a cryptographic content hash where a single-byte change
// produces a completely different digest.
package simhash

import (
	"hash/fnv"
	"math/bits"
	"strings"
)

// Fingerprint computes a 64-bit simhash of text: split into words, hash each
// word, and for every bit position sum +1/-1 across all word hashes
// (weighted by how many times each word appears) -- the final fingerprint's
// bit i is 1 if that sum is positive. Documents sharing most of their words
// end up with fingerprints that differ in only a few bits, regardless of
// where in the document those differences fall.
func Fingerprint(text string) uint64 {
	counts := make(map[string]int)
	for _, word := range strings.Fields(text) {
		counts[word]++
	}

	var weights [64]int
	for word, freq := range counts {
		h := hashToken(word)
		for i := 0; i < 64; i++ {
			if h&(1<<uint(i)) != 0 {
				weights[i] += freq
			} else {
				weights[i] -= freq
			}
		}
	}

	var fp uint64
	for i := 0; i < 64; i++ {
		if weights[i] > 0 {
			fp |= 1 << uint(i)
		}
	}
	return fp
}

// hashToken hashes one word to 64 bits. FNV-1a is used purely as a fast,
// well-distributed non-cryptographic hash -- simhash's near-duplicate
// property comes from the weighted-bit-voting scheme above, not from any
// property of the underlying per-word hash function.
func hashToken(word string) uint64 {
	h := fnv.New64a()
	h.Write([]byte(word))
	return h.Sum64()
}

// HammingDistance counts the bits that differ between two fingerprints --
// the standard similarity measure for simhash: 0 means identical, higher
// means less similar. 64-bit fingerprints commonly use a threshold of ~3-4
// bits to call two documents near-duplicates.
func HammingDistance(a, b uint64) int {
	return bits.OnesCount64(a ^ b)
}

// AnyWithin reports whether h is within maxDistance Hamming bits of any
// fingerprint in hashes -- the check used to decide "is this a
// near-duplicate of something already seen".
func AnyWithin(hashes []uint64, h uint64, maxDistance int) bool {
	for _, prior := range hashes {
		if HammingDistance(prior, h) <= maxDistance {
			return true
		}
	}
	return false
}
