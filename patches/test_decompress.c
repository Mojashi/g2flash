#include <stdint.h>
#include <stdio.h>
#include <string.h>
uint32_t decompress_1to4(const uint8_t*,uint32_t,uint8_t*,uint32_t);
int main(){
  uint8_t src[]={0xB2,0xFF,0x00,0x01};
  uint8_t dst[64]; memset(dst,0xAA,sizeof dst);
  // full capacity
  uint32_t n=decompress_1to4(src,4,dst,sizeof dst);
  printf("n=%u\n",n);
  for(uint32_t i=0;i<n;i++)printf("%02x ",dst[i]); printf("\n");
  // cap test: only 3 bytes of room
  uint8_t d2[8]; memset(d2,0xAA,sizeof d2);
  uint32_t m=decompress_1to4(src,4,d2,3);
  printf("capped n=%u: ",m); for(uint32_t i=0;i<8;i++)printf("%02x ",d2[i]); printf("\n");
  return 0;
}
