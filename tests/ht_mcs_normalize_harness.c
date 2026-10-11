/* Exercise the pure nl80211 MCS validator without touching a radio. */

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "netutils.h"

static int run_case(const char *name, const uint8_t *raw, size_t raw_len,
                    bool have_antenna, uint32_t antenna_mask,
                    int want_success, size_t want_count,
                    const uint8_t expected_masks[4]) {
	uint8_t masks[4] = { 0xaa, 0xaa, 0xaa, 0xaa };
	size_t count = 99;
	int rc = normalize_ht_rx_mcs_masks(raw, raw_len, have_antenna,
	                                   antenna_mask, masks, &count);
	int success = rc == 0;

	printf("case=%s rc=%d count=%zu masks=%02x,%02x,%02x,%02x\n",
	       name, rc, count, masks[0], masks[1], masks[2], masks[3]);
	if (success != want_success)
		return 1;
	if (success && count != want_count)
		return 1;
	if (success && expected_masks && memcmp(masks, expected_masks, 4) != 0)
		return 1;
	if (!success && count != 99)
		return 1;
	return 0;
}

int main(void) {
	uint8_t raw[16];

	memset(raw, 0, sizeof(raw));
	raw[0] = 0xff;
	raw[1] = 0xff;
	if (run_case("two-stream", raw, sizeof(raw), false, 0, 1, 2,
	             (uint8_t[]) { 0xff, 0xff, 0, 0 }))
		return 1;

	raw[1] = 0;
	if (run_case("one-stream", raw, sizeof(raw), false, 0, 1, 1,
	             (uint8_t[]) { 0xff, 0, 0, 0 }))
		return 1;

	raw[1] = 0xff;
	if (run_case("antenna-clamp", raw, sizeof(raw), true, 1, 1, 1,
	             (uint8_t[]) { 0xff, 0, 0, 0 }))
		return 1;
	if (run_case("two-antenna", raw, sizeof(raw), true, 3, 1, 2,
	             (uint8_t[]) { 0xff, 0xff, 0, 0 }))
		return 1;

	raw[1] = 0;
	raw[2] = 0xff;
	if (run_case("sparse", raw, sizeof(raw), false, 0, 0, 0, NULL))
		return 1;

	raw[2] = 0;
	if (run_case("short", raw, sizeof(raw) - 1, false, 0, 0, 0, NULL))
		return 1;
	if (run_case("zero-antenna", raw, sizeof(raw), true, 0, 0, 0, NULL))
		return 1;

	/* A fifth MCS byte is outside the AWDL type-7 four-stream envelope and is
	 * intentionally ignored; the first four remain contiguous. */
	raw[1] = 0xff;
	raw[2] = 0xff;
	raw[3] = 0xff;
	raw[4] = 0xff;
	if (run_case("four-stream-cap", raw, sizeof(raw), false, 0, 1, 4,
	             (uint8_t[]) { 0xff, 0xff, 0xff, 0xff }))
		return 1;

	memset(raw, 0, sizeof(raw));
	raw[0] = 0x12;
	raw[1] = 0x34;
	if (run_case("preserve-masks", raw, sizeof(raw), false, 0, 1, 2,
	             (uint8_t[]) { 0x12, 0x34, 0, 0 }))
		return 1;

	return 0;
}
