#ifndef A9_WPS_PACK_H
#define A9_WPS_PACK_H
#include <stdint.h>
#define A9_WPS_V1_BYTES 73600u
#define A9_WPS_PACK_BYTES 83520u
#define A9_WPS_HEADER_BYTES 512u
#define A9_WPS_SLOTS 4u
#define A9_WPS_ACTIVE_PATH "/tmp_bt/a9-wps-active.a9w"
enum a9_wps_error {
 A9_WPS_OK=0,A9_WPS_NONE=1,A9_WPS_ARGUMENT=-600,A9_WPS_FORMAT=-601,
 A9_WPS_HASH=-602,A9_WPS_SDS=-603,A9_WPS_IO=-604,A9_WPS_CONFLICT=-605,
 A9_WPS_OVERFLOW=-606,A9_WPS_WRITE=-607,A9_WPS_VERIFY=-608,
 A9_WPS_BIND=-609,A9_WPS_ROLLBACK=-610,A9_WPS_BUSY=-611
};
struct a9_wps_slot {const uint8_t *data;uint32_t bytes;uint8_t sha256[32];};
struct a9_wps_package {uint32_t mask,bytes,slots,version;struct a9_wps_slot slot[A9_WPS_SLOTS];uint8_t sha256[32];};
extern const unsigned a9_wps_slot_bytes[A9_WPS_SLOTS];
extern const unsigned a9_wps_slot_offsets[A9_WPS_SLOTS];
/* Canonical little-endian A9W v1, exact 73600 bytes:
 * 0..7 "A9WPS1\0\0"; u32 version@8=1, total@12, header@16=512,
 * mask@20 (bits0..2), model@24=0x00060009, slots@28=3.
 * Three 48-byte descriptors @32: APP ID(0x33+i), fixed size, fixed offset,
 * reserved0, SHA256(slot bytes). Unselected slots and their SHA are all zero.
 * package digest @176 = SHA256(header with bytes176..207 zero || SHA256(payload)).
 * Bytes208..511 are zero. Thus the package digest authenticates every byte;
 * the nested definition avoids a second 73600-byte allocation on the camera.
 * V2 keeps magic/model/header and first three payload offsets, uses version2,
 * total83520, slots4, mask0..15. Fourth descriptor@176 is APP0x32, size9920,
 * offset73600. Digest@224..255, reserved256..511 zero (no overlap).
 * A9_WPS_PACK_BYTES is allocation capacity; decoded bytes is actual V1/V2 size.
 * Every selected SDS block has mode0/1 and shift0..8 in its first byte.
 * Output pointers borrow raw; keep raw alive while using out. Error clears out.
 */
int a9_wps_decode(const uint8_t *raw,unsigned bytes,struct a9_wps_package *out);
void a9_wps_digest(const uint8_t *header,unsigned digest_offset,
                   const uint8_t *payload,unsigned bytes,uint8_t out[32]);
#endif
