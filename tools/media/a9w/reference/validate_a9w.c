/* PC-side validation through the frozen V8 parser; never links a camera API. */
#include "a9_wps_pack.h"
#include <stdio.h>
#include <stdlib.h>
int main(int argc,char **argv){
 if(argc!=2)return 2;
 FILE *f=fopen(argv[1],"rb");if(!f)return 3;
 unsigned char *p=malloc(A9_WPS_PACK_BYTES+1);if(!p){fclose(f);return 4;}
 unsigned n=(unsigned)fread(p,1,A9_WPS_PACK_BYTES+1,f);int failed=ferror(f);fclose(f);
 struct a9_wps_package out;int rc=failed?-1:a9_wps_decode(p,n,&out);
 if(!rc)printf("A9W_C_OK version=%u slots=%u mask=%u bytes=%u\n",out.version,out.slots,out.mask,out.bytes);
 else fprintf(stderr,"A9W_C_REJECT %d\n",rc);
 free(p);return rc?1:0;
}
