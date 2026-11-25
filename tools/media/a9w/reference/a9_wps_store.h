#ifndef A9_WPS_STORE_H
#define A9_WPS_STORE_H
#include "a9_wps_pack.h"
#define A9_WPS_STORE_BYTES (512u+A9_WPS_PACK_BYTES)
/* read: 0 means a completed read (including malformed/short files); NONE only
 * means explicitly absent. Other errors must not be mistaken for absence.
 * write replaces only the nominated inactive slot, syncs and closes it;
 * success is not accepted until the core reopens and verifies every byte.
 * Dual slots provide recoverability, not a vfat power-loss atomicity claim. */
struct a9_wps_store_io {
 void *context;
 int (*read)(void *,unsigned,uint8_t *,unsigned,unsigned *);
 int (*write)(void *,unsigned,const uint8_t *,unsigned);
};
/* Store v1 header: magic "A9WSTORE", version1@8, total@12, generation@16,
 * pack length@20, COMT(0x544d4f43)@24, reserved0@28, package digest@32,
 * store digest@64 using a9_wps_digest(header,64,pack,actual_length); rest zero.
 * Store envelope stays version1: exact total512+pack length (73600 or83520).
 * load zero-fills capacity beyond legacy bytes; callers use package total@12.
 * A complete valid image is its commit record. A torn image is never selected.
 */
int a9_wps_store_load(const struct a9_wps_store_io *,uint8_t [A9_WPS_PACK_BYTES],
                      uint32_t *generation,unsigned *selected_slot);
int a9_wps_store_save(const struct a9_wps_store_io *,const uint8_t *,unsigned);
#endif
