/* Small wire-only harness used by run_ht_regression.py.
 * It deliberately performs explicit checks and does not rely on assert(), so
 * the checks remain active in Release/NDEBUG builds. */

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "state.h"
#include "tx.h"

static int fail(const char *message) {
	fprintf(stderr, "FAIL: %s\n", message);
	return 1;
}

int main(int argc, char **argv) {
	struct awdl_state state = { 0 };
	uint8_t wire[64];
	const size_t mcs_offset = offsetof(struct awdl_ht_capabilities_tlv, rx_mcs);
	const char *mode;
	int total;
	uint16_t length;
	const uint8_t *expected_wire;
	size_t expected_wire_len;
	static const uint8_t legacy_wire[] = {
		0x07, 0x08, 0x00, 0x00, 0x00, 0xce, 0x11, 0x1b, 0xff, 0x00, 0x00,
	};
#ifdef HT_EXPERIMENT_CANDIDATE
	static const uint8_t two_stream_wire[] = {
		0x07, 0x09, 0x00, 0x00, 0x00, 0xce, 0x11, 0x1b, 0xff, 0xff, 0x00, 0x00,
	};
	static const uint8_t four_stream_wire[] = {
		0x07, 0x0b, 0x00, 0x00, 0x00, 0xce, 0x11, 0x1b,
		0x12, 0x34, 0x56, 0x78, 0x00, 0x00,
	};
#endif

	if (argc != 2)
		return fail("usage: ht_caps_wire_harness legacy|two-stream|four-stream|invalid-state");
	mode = argv[1];
	if (strcmp(mode, "legacy") && strcmp(mode, "two-stream") &&
	    strcmp(mode, "four-stream") && strcmp(mode, "invalid-state"))
		return fail("unknown mode");

	if (!strcmp(mode, "two-stream")) {
		/* The candidate can be driven directly without a real radio.  The
		 * baseline intentionally ignores these fields and remains one stream. */
	#ifdef HT_EXPERIMENT_CANDIDATE
		state.ht_rx.count = 2;
		state.ht_rx.mcs[0] = 0xff;
		state.ht_rx.mcs[1] = 0xff;
	#endif
	} else if (!strcmp(mode, "four-stream")) {
	#ifdef HT_EXPERIMENT_CANDIDATE
		state.ht_rx.count = 4;
		state.ht_rx.mcs[0] = 0x12;
		state.ht_rx.mcs[1] = 0x34;
		state.ht_rx.mcs[2] = 0x56;
		state.ht_rx.mcs[3] = 0x78;
	#endif
	} else if (!strcmp(mode, "invalid-state")) {
	#ifdef HT_EXPERIMENT_CANDIDATE
		state.ht_rx.count = AWDL_HT_RX_MCS_MAX_STREAMS + 1;
		state.ht_rx.mcs[0] = 0x12;
	#endif
	}

	expected_wire = legacy_wire;
	expected_wire_len = sizeof(legacy_wire);
#ifdef HT_EXPERIMENT_CANDIDATE
	if (!strcmp(mode, "two-stream")) {
		expected_wire = two_stream_wire;
		expected_wire_len = sizeof(two_stream_wire);
	} else if (!strcmp(mode, "four-stream")) {
		expected_wire = four_stream_wire;
		expected_wire_len = sizeof(four_stream_wire);
	}
#endif

	memset(wire, 0xcc, sizeof(wire));
	total = awdl_init_ht_capabilities_tlv(wire, &state);
	if (total <= 0 || total >= (int) sizeof(wire))
		return fail("invalid returned TLV size");

	length = (uint16_t) wire[1] | ((uint16_t) wire[2] << 8);
	if ((size_t) total != sizeof(struct tl) + length)
		return fail("returned size disagrees with TLV length");
	if (wire[total] != 0xcc)
		return fail("following byte was overwritten");
	if (total != (int) expected_wire_len ||
	    memcmp(wire, expected_wire, expected_wire_len) != 0)
		return fail("unexpected TLV bytes for selected mode");

	printf("total=%d length=%u mcs=", total, (unsigned) length);
	for (size_t i = mcs_offset; i < (size_t) total - sizeof(uint16_t); i++) {
		/* The final two bytes are the existing pad, not MCS bytes. */
		printf("%s%02x", i == mcs_offset ? "" : ",", wire[i]);
	}
	printf(" next=%d sentinel=%02x\n", total, wire[total]);
	return 0;
}
