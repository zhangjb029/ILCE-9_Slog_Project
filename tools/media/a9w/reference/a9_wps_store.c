#include "a9_wps_store.h"
#include <stdlib.h>
#include <string.h>
static uint32_t get(const uint8_t*p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static void put(uint8_t*p,uint32_t n){for(unsigned i=0;i<4;i++)p[i]=(uint8_t)(n>>(8*i));}
static int valid(const uint8_t*p,unsigned n,uint32_t*gen){
 unsigned bytes=n>=512?get(p+20):0;
 if((bytes!=A9_WPS_V1_BYTES&&bytes!=A9_WPS_PACK_BYTES)||n!=512+bytes||memcmp(p,"A9WSTORE",8)||get(p+8)!=1||get(p+12)!=n||!get(p+16)||
    get(p+24)!=0x544d4f43||get(p+28))return 0;
 for(unsigned i=96;i<512;i++)if(p[i])return 0;
 uint8_t hash[32];struct a9_wps_package package;
 a9_wps_digest(p,64,p+512,bytes,hash);
 if(memcmp(hash,p+64,32)||a9_wps_decode(p+512,bytes,&package)||memcmp(p+32,package.sha256,32))return 0;
 *gen=get(p+16);return 1;
}
int a9_wps_store_load(const struct a9_wps_store_io*io,uint8_t out[A9_WPS_PACK_BYTES],uint32_t*gen,unsigned*selected){
 if(!io||!io->read||!out||!gen||!selected)return A9_WPS_ARGUMENT;
 *gen=0;*selected=2;
 uint8_t *raw=malloc(A9_WPS_STORE_BYTES+1);if(!raw)return A9_WPS_IO;
 int result=A9_WPS_NONE,malformed=0;
 for(unsigned i=0;i<2;i++){
  unsigned n=0;int rc=io->read(io->context,i,raw,A9_WPS_STORE_BYTES+1,&n);
  if(rc==A9_WPS_NONE)continue;
  if(rc){result=A9_WPS_IO;goto done;}
  uint32_t generation=0;if(!valid(raw,n,&generation)){malformed=1;continue;}
  if(result==0&&generation==*gen&&(get(out+12)!=get(raw+20)||memcmp(out,raw+512,get(raw+20)))){result=A9_WPS_CONFLICT;goto done;}
  if(result||generation>*gen){memset(out,0,A9_WPS_PACK_BYTES);memcpy(out,raw+512,get(raw+20));*gen=generation;*selected=i;result=0;}
 }
 if(result==A9_WPS_NONE&&malformed)result=A9_WPS_FORMAT;
done:
 free(raw);if(result){*gen=0;*selected=2;memset(out,0,A9_WPS_PACK_BYTES);}return result;
}
int a9_wps_store_save(const struct a9_wps_store_io*io,const uint8_t*pack,unsigned n){
 struct a9_wps_package package;
 if(!io||!io->read||!io->write)return A9_WPS_ARGUMENT;
 int rc=a9_wps_decode(pack,n,&package);if(rc)return rc;
 uint8_t *old=malloc(A9_WPS_PACK_BYTES),*raw=malloc(A9_WPS_STORE_BYTES+1),*check=malloc(A9_WPS_STORE_BYTES+1);
 if(!old||!raw||!check){free(old);free(raw);free(check);return A9_WPS_IO;}
 uint32_t gen=0;unsigned selected=2;rc=a9_wps_store_load(io,old,&gen,&selected);
 /* No valid record after two completed reads may be an interrupted very
  * first save. Repair reserved slot0; preserve slot1. Unknown I/O and equal
  * generation conflicts remain fatal and never authorize an overwrite. */
 if(rc!=0&&rc!=A9_WPS_NONE&&rc!=A9_WPS_FORMAT)goto done;
 if(!rc&&get(old+12)==n&&!memcmp(old,pack,n))goto done;
 if(gen==UINT32_MAX){rc=A9_WPS_OVERFLOW;goto done;}
 memset(raw,0,512);memcpy(raw,"A9WSTORE",8);put(raw+8,1);put(raw+12,512+n);put(raw+16,gen+1);
 put(raw+20,n);put(raw+24,0x544d4f43);memcpy(raw+32,package.sha256,32);memcpy(raw+512,pack,n);
 a9_wps_digest(raw,64,raw+512,n,raw+64);
 unsigned inactive=selected<2?selected^1u:0;
 rc=io->write(io->context,inactive,raw,512+n);if(rc){rc=A9_WPS_WRITE;goto done;}
 unsigned bytes=0;rc=io->read(io->context,inactive,check,A9_WPS_STORE_BYTES+1,&bytes);
 uint32_t verified=0;
 if(rc||bytes!=512+n||memcmp(raw,check,512+n)||!valid(check,bytes,&verified)||verified!=gen+1)rc=A9_WPS_VERIFY;
done:
 free(old);free(raw);free(check);return rc;
}
