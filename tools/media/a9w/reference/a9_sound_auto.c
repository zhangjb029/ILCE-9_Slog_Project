#include "a9_sound_auto.h"
#include <string.h>
unsigned a9_sound_auto_resolve(const struct a9_drive_snapshot *s){
 if(!s||!s->query_ok||!s->context_ok||!(s->valid_mask&A9_DRIVE_RAW_VALID))return A9_SOUND_AUTO_UNKNOWN;
 if(s->raw==1){
  if(!(s->valid_mask&A9_DRIVE_SPEED_VALID))return A9_SOUND_AUTO_UNKNOWN;
  switch(s->speed){case 0:return A9_SOUND_SELECTION_LOOPL;case 1:return A9_SOUND_SELECTION_LOOPH;
   case 2:case 3:return A9_SOUND_SELECTION_LOOPSH;default:return A9_SOUND_AUTO_UNKNOWN;}
 }
 switch(s->raw){
 case 0:case 2:case 3:case 4:case 5:case 7:case 8:case 9:case 12:case 13:case 14:case 15:case 16:
  return A9_SOUND_SELECTION_SINGLE;
 default:return A9_SOUND_AUTO_UNKNOWN;
 }
}
void a9_sound_auto_bind(struct a9_sound_auto *a,struct a9_resident_sound *s){
 memset(a,0,sizeof *a);a->sound=s;
}
int a9_sound_auto_configure(struct a9_sound_auto *a,unsigned policy){
 if(!a||!a->sound||policy>A9_SOUND_SELECTION_AUTO)return -1;
 if(a->policy!=policy){
  a->policy=policy;a->latched=0;a->pending=A9_SOUND_AUTO_UNKNOWN;
  /* Explicit user policy changes cancel, ordinary drive changes do not. */
  a9_resident_sound_step(a->sound,a->sound->last_time,A9_KEY_UNKNOWN,0);
  a->sound->have_snapshot=0;
  a->effective=policy==A9_SOUND_SELECTION_AUTO?A9_SOUND_SELECTION_OFF:policy;
  return a9_resident_sound_configure(a->sound,a->effective);
 }
 return 0;
}
void a9_sound_auto_step(struct a9_sound_auto *a,uint64_t now,enum a9_key_state key,
                       uint32_t input,uint32_t chain,const struct a9_drive_snapshot *snapshot){
 struct a9_resident_sound *s=a->sound;
 unsigned candidate=a->policy==A9_SOUND_SELECTION_AUTO?a9_sound_auto_resolve(snapshot):a->policy;
 int changed=a->have_epoch&&(a->input_epoch!=input||a->chain_epoch!=chain);
 a->have_epoch=1;a->input_epoch=input;a->chain_epoch=chain;a->pending=candidate;
 if(changed||!input||!chain||candidate==A9_SOUND_AUTO_UNKNOWN||
    (key!=A9_KEY_UP&&key!=A9_KEY_DOWN)){
  a9_resident_sound_step(s,now,A9_KEY_UNKNOWN,input);a->latched=0;return;
 }
 /* Advance elapsed tail guard before choosing another mode. */
 if(s->tail_active&&now>=s->tail_until){s->tail_active=0;s->tail_until=0;a->latched=0;}
 int single_guard=a->policy==A9_SOUND_SELECTION_AUTO&&s->active&&s->selection==A9_SOUND_SELECTION_SINGLE&&
  s->have_play&&now>=s->last_play_time&&now-s->last_play_time<A9_RESIDENT_SOUND_TAIL_US;
 if(!a->latched&&!s->tail_active&&!single_guard&&(key==A9_KEY_UP||s->armed)&&candidate!=a->effective){
  unsigned armed=s->armed;
  if(!a9_resident_sound_configure(s,candidate)){a->effective=candidate;s->armed=armed;}
 }
 /* A deferred AUTO transition must not submit the old SINGLE again.
  * Consume this DOWN while retaining resident time/epoch validation below;
  * only a later observed UP may rearm, even after the guard expires. */
 if(single_guard&&!a->latched&&candidate!=a->effective&&key==A9_KEY_DOWN)
  s->armed=0;
 if(key==A9_KEY_DOWN&&s->armed&&!s->tail_active)a->latched=1;
 a9_resident_sound_step(s,now,key,input);
 if(key==A9_KEY_UP&&!s->tail_active)a->latched=0;
 if(key==A9_KEY_UP&&s->tail_active)a->latched=1;
}
