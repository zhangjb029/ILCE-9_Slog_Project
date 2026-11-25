#ifndef A9_SOUND_RESIDENT_H
#define A9_SOUND_RESIDENT_H
#include "a9_sound_state.h"
/* Resident request scheduler, deliberately separate from the handle/idle ABI.
 * A void Sony command proves submission only. It cannot satisfy is_idle(). */
enum {A9_NATIVE_COMPLETION_UNKNOWN=0};
enum {A9_SOUND_NO_REQUEST=0,A9_SOUND_PLAY_REQUEST_SUBMITTED,A9_SOUND_STOP_REQUEST_SUBMITTED,A9_SOUND_REQUEST_REJECTED};
enum {A9_SOUND_SELECTION_OFF=0,A9_SOUND_SELECTION_SINGLE=1,
      A9_SOUND_SELECTION_LOOPL=2,A9_SOUND_SELECTION_LOOPH=3,A9_SOUND_SELECTION_LOOPSH=4,A9_SOUND_SELECTION_AUTO=5};
#define A9_RESIDENT_SOUND_COOLDOWN_US 450000u
#define A9_RESIDENT_SOUND_LOOPL_US 1200000u
#define A9_RESIDENT_SOUND_LOOPH_US 700000u
#define A9_RESIDENT_SOUND_LOOPSH_US 400000u
/* WPS1: 774 SDS frames * 31 samples / 24000 Hz. This protects a request;
 * there is no native playback completion acknowledgement. */
#define A9_RESIDENT_SOUND_TAIL_US 999750u
struct a9_resident_sound_api {
 void *context;
 int (*play)(void *,unsigned app_id);
 int (*stop)(void *);
};
struct a9_resident_sound {
 struct a9_resident_sound_api api;
 uint32_t enabled,selection,slot,interval,armed,active,repeat_active,stop_on_release;
 uint32_t input_epoch,have_snapshot,have_time,have_play,tail_active;
 uint64_t last_time,due,last_play_time,tail_until;
 uint32_t play_requests,stop_requests,last_request,native_completion;
};
void a9_resident_sound_bind(struct a9_resident_sound *,const struct a9_resident_sound_api *);
/* Manual modes fix both APP slot and whole-resource replay period:
 * SINGLE=WPS1, LOOPL=WPS2/1.2s, LOOPH=WPS3/0.7s, LOOPSH=WPS4(APP0x32)/0.4s. */
int a9_resident_sound_configure(struct a9_resident_sound *,unsigned selection);
/* One fixed-slot preview; explicitly cancels any loop/tail, never schedules
 * repeats or a release tail, and re-arms only after valid FULL UP. */
int a9_resident_sound_preview(struct a9_resident_sound *,uint64_t now_us);
void a9_resident_sound_step(struct a9_resident_sound *,uint64_t now_us,
                          enum a9_key_state,uint32_t input_epoch);
#endif
