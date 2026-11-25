#ifndef A9_INPUT_COMPAT_H
#define A9_INPUT_COMPAT_H
#include <stdint.h>

enum a9_key_state { A9_KEY_UNKNOWN=-1, A9_KEY_UP=0, A9_KEY_DOWN=1 };
enum a9_input_priority { A9_INPUT_FAST=0, A9_INPUT_DISMISS=1 };
enum a9_input_kind { A9_INPUT_HOST_FIXTURE=1, A9_INPUT_NATIVE=2 };
enum a9_logical_key {
    A9_KEY_MENU, A9_KEY_AEL, A9_KEY_FULL, A9_KEY_HALF,
    A9_KEY_DISMISS_3, A9_KEY_DISMISS_15, A9_KEY_DISMISS_30, A9_KEY_DISMISS_66,
    A9_KEY_DISMISS_1AC, A9_KEY_DISMISS_1AF, A9_KEY_DISMISS_1F0,
    A9_KEY_DISMISS_1F4, A9_KEY_DISMISS_1F7, A9_KEY_DISMISS_1F8, A9_KEY_DISMISS_1F9,
    A9_KEY_DISMISS_7095, A9_KEY_DISMISS_70A9, A9_KEY_DISMISS_70AA,
    A9_KEY_DISMISS_70AB, A9_KEY_DISMISS_70AD, A9_KEY_DISMISS_70C4,
    A9_KEY_KURU_LEFT, A9_KEY_KURU_RIGHT, A9_KEY_WHEEL_LEFT, A9_KEY_WHEEL_RIGHT,
    A9_KEY_COUNT
};
#define A9_INPUT_OPTIONAL_ROTARY_MASK ((1u<<A9_KEY_KURU_LEFT)|(1u<<A9_KEY_KURU_RIGHT)|\
                                     (1u<<A9_KEY_WHEEL_LEFT)|(1u<<A9_KEY_WHEEL_RIGHT))
struct a9_key_binding { uint32_t upstream_id,a9_raw_id,priority,dismiss; };
extern const struct a9_key_binding a9_keymap[A9_KEY_COUNT];
struct a9_input_config {
    uint32_t abi,size;
    uint64_t fast_period_us,dismiss_period_us,ttl_us,max_skew_us,query_budget_us;
    uint32_t disabled_optional_mask; /* Only the four rotary dismiss sources. */
    uint32_t best_effort_aux_keys; /* First resident profile: MENU/AEL/FULL required. */
};
struct a9_input_platform {
    uint32_t abi,size,kind;
    void *context;
    int (*context_ok)(void *);
    void *(*get_instance)(void *);
    int (*get_status)(void *,void *instance,uint32_t raw_key);
    uint64_t (*now_us)(void *);
};
struct a9_input_sample {
    int32_t raw_state,state;
    uint32_t valid,epoch,dismiss_epoch;
    uint64_t sampled_at_us;
};
struct a9_input_frame {
    uint32_t seq,epoch,dismiss_epoch;
    uint64_t captured_at_us;
    void *native_instance;
    struct a9_input_sample keys[A9_KEY_COUNT];
};
struct a9_input_diag {
    uint32_t successful_queries,failed_queries,late_replies,slow_replies,lock_contentions;
    uint32_t inflight,last_reason,last_query_us,max_query_us;
};
int a9_input_init(const struct a9_input_config *,const struct a9_input_platform *);
int a9_input_key_enabled(unsigned logical_key);
int a9_input_key_required(unsigned logical_key);
int a9_input_collect(uint64_t now_us);
int a9_input_set_visibility(unsigned visible);
int a9_input_begin_frame(uint64_t now_us,struct a9_input_frame *out);
int a9_input_read(const struct a9_input_frame *,unsigned logical_key);
int a9_input_legacy_read(void *native_instance,int upstream_key,void *out);
void a9_input_invalidate(uint32_t reason);
void a9_input_request_stop(void);
int a9_input_stop_status(void);
int a9_input_get_diag(struct a9_input_diag *out);
#endif
