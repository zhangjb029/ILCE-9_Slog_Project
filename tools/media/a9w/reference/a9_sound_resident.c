#include "a9_sound_resident.h"
#include <string.h>
/* Cancellation is never a normal shutter release and must not make a tail. */
static int cancel(struct a9_resident_sound *s){
 s->repeat_active=0;s->armed=0;s->due=0;s->stop_on_release=0;
 s->tail_active=0;s->tail_until=0;
 if(s->active){
  s->active=0;
  if(s->api.stop&&s->api.stop(s->api.context)==1){
   s->stop_requests++;s->last_request=A9_SOUND_STOP_REQUEST_SUBMITTED;
  }else{s->last_request=A9_SOUND_REQUEST_REJECTED;return 0;}
 }
 return 1;
}
void a9_resident_sound_bind(struct a9_resident_sound *s,const struct a9_resident_sound_api *api){
 memset(s,0,sizeof *s);s->api=*api;
}
int a9_resident_sound_configure(struct a9_resident_sound *s,unsigned selection){
 if(selection>A9_SOUND_SELECTION_LOOPSH||!s->api.play||!s->api.stop)return -1;
 if(selection!=s->selection){
  (void)cancel(s);s->selection=selection;s->enabled=selection!=A9_SOUND_SELECTION_OFF;
  s->slot=selection?selection-1:0;
  s->interval=selection==A9_SOUND_SELECTION_LOOPL?A9_RESIDENT_SOUND_LOOPL_US:
              selection==A9_SOUND_SELECTION_LOOPH?A9_RESIDENT_SOUND_LOOPH_US:
              selection==A9_SOUND_SELECTION_LOOPSH?A9_RESIDENT_SOUND_LOOPSH_US:0;
 }
 return 0;
}
static int observe_time(struct a9_resident_sound *s,uint64_t now){
 int backwards=s->have_time&&now<s->last_time;
 s->have_time=1;s->last_time=now;
 if(backwards){(void)cancel(s);s->have_play=0;return 0;}
 return 1;
}
static int play(struct a9_resident_sound *s,uint64_t now,unsigned app,int loop){
 s->armed=0;s->repeat_active=0;s->due=0;s->stop_on_release=0;
 s->tail_active=0;s->tail_until=0;
 if(s->api.play(s->api.context,app)!=1){
  (void)cancel(s);s->last_request=A9_SOUND_REQUEST_REJECTED;return 0;
 }
 s->play_requests++;s->active=1;s->have_play=1;s->last_play_time=now;
 s->last_request=A9_SOUND_PLAY_REQUEST_SUBMITTED;
 if(loop){s->repeat_active=1;s->stop_on_release=1;s->due=now+s->interval;}
 return 1;
}
static void release_tail(struct a9_resident_sound *s,uint64_t now){
 /* Stop must be admitted before tail play; neither command acknowledges
  * native completion or promises ordering outside this submission thread. */
 if(!cancel(s)||now>UINT64_MAX-A9_RESIDENT_SOUND_TAIL_US)return;
 if(play(s,now,0x33u,0)){
  s->tail_active=1;s->tail_until=now+A9_RESIDENT_SOUND_TAIL_US;
 }
}
int a9_resident_sound_preview(struct a9_resident_sound *s,uint64_t now){
 if(!s->enabled||!s->api.play||!s->api.stop)return 0;
 if(!observe_time(s,now)||!cancel(s))return 0;
 return play(s,now,(s->slot==3?0x32u:0x33u+s->slot),0);
}
void a9_resident_sound_step(struct a9_resident_sound *s,uint64_t now,
                          enum a9_key_state full,uint32_t input){
 int changed=s->have_snapshot&&input!=s->input_epoch;
 int time_ok=observe_time(s,now);
 s->have_snapshot=1;s->input_epoch=input;
 if(!s->enabled)return;
 if(!time_ok||changed||!input||!s->api.play||!s->api.stop||
    (full!=A9_KEY_UP&&full!=A9_KEY_DOWN)){
  (void)cancel(s);return;
 }
 if(s->tail_active&&now>=s->tail_until){
  s->tail_active=0;s->tail_until=0; /* elapsed guard, not native idle */
 }
 if(full==A9_KEY_UP){
  if(s->stop_on_release)release_tail(s,now);
  /* SINGLE, previews, and the tail own no release stop. */
  s->armed=1;return;
 }
 if(s->tail_active){
  s->armed=0;return; /* consume protected DOWN, never delay it */
 }
 if(s->interval&&now>UINT64_MAX-s->interval){(void)cancel(s);return;}
 if(s->armed){
  s->armed=0;
  if(s->interval||!s->have_play||now-s->last_play_time>=A9_RESIDENT_SOUND_COOLDOWN_US)
   (void)play(s,now,(s->slot==3?0x32u:0x33u+s->slot),s->interval!=0);
 }else if(s->repeat_active&&now>=s->due)
  (void)play(s,now,(s->slot==3?0x32u:0x33u+s->slot),1); /* at most once; no catch-up */
}
