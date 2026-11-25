#ifndef A9_DRIVE_MODE_H
#define A9_DRIVE_MODE_H
#include "sound/a9_sound_state.h"
enum {A9_DRIVE_RAW_VALID=1,A9_DRIVE_SPEED_VALID=2,A9_DRIVE_OPTION_VALID=4,A9_DRIVE_BOL_VALID=8};
struct a9_drive_snapshot {
 uint32_t query_ok,context_ok,valid_mask;
 int32_t model_id,raw,speed,option,bol_speed;
};
enum a9_sound_mode a9_drive_classify(const struct a9_drive_snapshot *);
#endif
