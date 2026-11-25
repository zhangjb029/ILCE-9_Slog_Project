#ifndef A9_SOUND_AUTO_H
#define A9_SOUND_AUTO_H
#include "a9_sound_resident.h"
#include "platform/a9_drive_mode.h"
/* UNKNOWN is a policy resolution failure, never OFF or SINGLE. */
#define A9_SOUND_AUTO_UNKNOWN 255u
struct a9_sound_auto {
 struct a9_resident_sound *sound;
 unsigned policy,pending,effective,latched,have_epoch;
 uint32_t input_epoch,chain_epoch;
};
unsigned a9_sound_auto_resolve(const struct a9_drive_snapshot *);
void a9_sound_auto_bind(struct a9_sound_auto *,struct a9_resident_sound *);
int a9_sound_auto_configure(struct a9_sound_auto *,unsigned policy);
/* Caller queries native drive ONLY for AUTO, on natural UI thread <=10 Hz.
 * snapshot may be NULL for manual modes; chain_epoch is native.epoch,
 * input_epoch is the real key source lifecycle, never drive_revision. */
void a9_sound_auto_step(struct a9_sound_auto *,uint64_t,enum a9_key_state,
                        uint32_t input_epoch,uint32_t chain_epoch,
                        const struct a9_drive_snapshot *);
#endif
