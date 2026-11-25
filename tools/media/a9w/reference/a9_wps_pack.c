#include "a9_wps_pack.h"
#include <string.h>
extern void a9_sha256(const uint8_t *,unsigned,uint8_t[32]);
const unsigned a9_wps_slot_bytes[4]={24768,29760,18560,9920};
const unsigned a9_wps_slot_offsets[4]={512,25280,55040,73600};
static uint32_t get(const uint8_t*p){return p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static int zero(const uint8_t*p,unsigned n){while(n--)if(*p++)return 0;return 1;}
void a9_wps_digest(const uint8_t*h,unsigned o,const uint8_t*p,unsigned n,uint8_t out[32]){
 uint8_t block[544];
 if(!h||o>480||!p||!out){if(out)memset(out,0,32);return;}
 memcpy(block,h,512);memset(block+o,0,32);a9_sha256(p,n,block+512);a9_sha256(block,sizeof block,out);
}
int a9_wps_decode(const uint8_t*p,unsigned n,struct a9_wps_package*out){
 if(!out)return A9_WPS_ARGUMENT;
 memset(out,0,sizeof *out);
 if(!p)return A9_WPS_ARGUMENT;
 unsigned version=n>=32?get(p+8):0;
 unsigned slots=version==1?3:version==2?4:0,digest=version==1?176:224;
 if(!slots||n!=(version==1?A9_WPS_V1_BYTES:A9_WPS_PACK_BYTES)||memcmp(p,"A9WPS1\0\0",8)||get(p+12)!=n||
    get(p+16)!=512||get(p+20)>((1u<<slots)-1)||get(p+24)!=0x60009||get(p+28)!=slots||!zero(p+digest+32,512-digest-32))return A9_WPS_FORMAT;
 uint8_t hash[32];a9_wps_digest(p,digest,p+512,n-512,hash);
 if(memcmp(hash,p+digest,32))return A9_WPS_HASH;
 struct a9_wps_package result={.mask=get(p+20),.bytes=n,.slots=slots,.version=version};
 for(unsigned i=0;i<slots;i++){
  const uint8_t*d=p+32+48*i,*data=p+a9_wps_slot_offsets[i];unsigned bytes=a9_wps_slot_bytes[i];
  if(get(d)!=(i==3?0x32:0x33+i)||get(d+4)!=bytes||get(d+8)!=a9_wps_slot_offsets[i]||get(d+12))return A9_WPS_FORMAT;
  result.slot[i].bytes=bytes;
  if(!(result.mask&(1u<<i))){if(!zero(d+16,32)||!zero(data,bytes))return A9_WPS_FORMAT;continue;}
  a9_sha256(data,bytes,hash);if(memcmp(hash,d+16,32))return A9_WPS_HASH;
  for(unsigned j=0;j<bytes;j+=32)if((data[j]>>4)>1||(data[j]&15)>8)return A9_WPS_SDS;
  result.slot[i].data=data;memcpy(result.slot[i].sha256,hash,32);
 }
 memcpy(result.sha256,p+digest,32);*out=result;return 0;
}
