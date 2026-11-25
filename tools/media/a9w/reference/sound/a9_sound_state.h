#ifndef A9_SOUND_STATE_H
#define A9_SOUND_STATE_H
#include "input/a9_input_compat.h"
enum a9_sound_mode { A9_SOUND_UNKNOWN=0,A9_SOUND_SINGLE=1,A9_SOUND_CONTINUOUS=2,A9_SOUND_OTHER=3 };
enum a9_sound_state { A9_SOUND_DISABLED,A9_SOUND_WAIT_RELEASE,A9_SOUND_ARMED,
    A9_SOUND_ONE_SHOT,A9_SOUND_LOOPING,A9_SOUND_STOPPING,A9_SOUND_FAULT };
enum a9_sound_capability { A9_SOUND_ONCE=1,A9_SOUND_LOOP=2,A9_SOUND_CANCEL=4 };
/* Owner-thread interface. All callbacks must be nonblocking. A successful play
 * returns a nonzero handle. A failure with handle==0 guarantees no activity;
 * partial failure MUST return its owned handle, even when return code<0.
 * A success with no handle violates the contract and blocks quiescence.
 * stop requests cancellation; is_idle==1 guarantees both playback and callbacks
 * are finished. No native backend is admitted yet. */
struct a9_sound_backend {
    uint32_t abi,size,capabilities;
    void *context;
    int (*play_once)(void *,unsigned slot,uint32_t *handle);
    int (*start_loop)(void *,unsigned slot,uint32_t *handle);
    int (*stop)(void *,uint32_t handle);
    int (*is_idle)(void *,uint32_t handle); /* 1=idle, 0=in flight, negative=fault */
};
int a9_sound_bind(const struct a9_sound_backend *);
int a9_sound_configure(unsigned enabled,unsigned slot);
#define A9_SOUND_INPUT_EPOCH_ABI 1u
int a9_sound_step(uint64_t now_us,enum a9_key_state full_press,enum a9_sound_mode,
                   uint32_t drive_epoch,uint32_t input_epoch);
int a9_sound_disable(void);
int a9_sound_quiescent(void);
enum a9_sound_state a9_sound_get_state(void);
/* Size/slot checks only; SDS header/decoded-silence/audio acceptance is separate. */
int a9_sound_asset_size_ok(unsigned slot,unsigned bytes,unsigned a9_beep_id);
#endif
