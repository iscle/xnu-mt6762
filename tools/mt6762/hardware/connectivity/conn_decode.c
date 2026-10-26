/* SPDX-License-Identifier: MIT */
#include "conn_decode.h"
static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1]<<8)); }
static uint32_t le32(const uint8_t *p) { return (uint32_t)le16(p) | ((uint32_t)le16(p+2)<<16); }
static uint64_t le64(const uint8_t *p) { return (uint64_t)le32(p) | ((uint64_t)le32(p+4)<<32); }
static int equal(const uint8_t *p, const char *q, size_t n) { size_t i; for(i=0;i<n;i++) if(p[i]!=(uint8_t)q[i]) return 0; return 1; }
static int zero(const uint8_t *p, size_t n) { size_t i; for(i=0;i<n;i++) if(p[i]) return 0; return 1; }
static int digits(const uint8_t *p, size_t n) { size_t i; for(i=0;i<n;i++) if(p[i]<'0'||p[i]>'9') return 0; return 1; }
static int release_info(const uint8_t *p, size_t n) {
 size_t end, at;
 if(n<36 || !equal(p,"################",16) || !equal(p+n-16,"################",16)) return CONN_FORMAT;
 if(p[18] || p[19] || le16(p+16)!=(n-36)) return CONN_FORMAT;
 end=n-16; at=20;
 while(at<end) {
  size_t len;
  if(end-at<4) return CONN_SIZE;
  len=(size_t)le16(p+at)+p[at+2];
  if((p[at+3]!=1 && p[at+3]!=2)||len>end-at-4) return CONN_RANGE;
  at+=4+len;
 }
 return at==end?CONN_OK:CONN_RANGE;
}
int conn_image_parse(const uint8_t *b,size_t n,unsigned kind,struct conn_image *out) {
 struct conn_image r={0}; size_t i,tail,used=0; const uint8_t *p;
 if(!b || !out || n>16*1024*1024) return CONN_SIZE;
 r.kind=kind;
 if(kind==CONN_WLAN) {
  if(n<76) return CONN_SIZE;
  p=b+n-36; r.chip=p[0];r.eco=p[1];r.region_count=p[2];r.format=p[3];r.flags=p[4];
  /* Exact supported format family; ECO is reported, never claimed measured. */
  if(r.chip!=7 || r.format!=2 || r.flags>1 || !zero(p+5,2) || !digits(p+17,14) || p[31]) return CONN_FORMAT;
  if(!r.region_count || r.region_count>16 || r.region_count>(n-36)/40) return CONN_RANGE;
  tail=n-36-r.region_count*40;
  for(i=0;i<r.region_count;i++) {
   const uint8_t *s=b+tail+i*40; uint32_t addr=le32(s+16),len=le32(s+20);size_t j;
   if(!len || len>tail-used || (uint64_t)addr+len>UINT64_C(0x100000000)) return CONN_RANGE;
   /* This package supports the actual uncompressed CONNAC tailers only. */
   if(!zero(s,16)||!zero(s+25,15)||(s[24]!=7 && s[24]!=128)) return CONN_FORMAT;
   for(j=0;j<i;j++) if((uint64_t)addr< (uint64_t)r.regions[j].device_address+r.regions[j].length &&
    (uint64_t)r.regions[j].device_address<(uint64_t)addr+len) return CONN_RANGE;
   r.regions[i].offset=(uint32_t)used;r.regions[i].length=len;r.regions[i].device_address=addr;r.regions[i].feature=s[24];used+=len;
  }
  if(used<tail) { int e; if(!r.flags) return CONN_FORMAT;e=release_info(b+used,tail-used);if(e) return e; }
  r.payload_bytes=(uint32_t)used;
 } else if(kind==CONN_WMT_PATCH || kind==CONN_WMT_RAM) {
  size_t header=kind==CONN_WMT_RAM?48:28;
  if(n<=header) return CONN_SIZE;
  if(!digits(b,16)||!equal(b+16,"ALPS",4)) return CONN_FORMAT;
  r.hw_version=((uint32_t)b[20]<<8)|b[21];r.sw_version=((uint32_t)b[22]<<8)|b[23];
  r.target=le32(b+24);r.payload_bytes=(uint32_t)(n-header);
  if(kind==CONN_WMT_RAM) {
   r.image_type=le32(b+28);
   /* u4CRC[4] at32 is retained opaque; this is not a CRC verifier. */
   if(r.image_type!=0x03000000 && r.image_type!=0x04000000) return CONN_FORMAT;
   if((uint64_t)r.target+r.payload_bytes>UINT64_C(0x100000000)) return CONN_RANGE;
  }
 } else if(kind==CONN_CALIBRATION) {
  /* 2048-byte WIFI_CFG_PARAM_STRUCT + two uninterpreted stock trailer bytes.
   * Never log or return the MAC/calibration bytes. SHA pins the complete file.
   */
  if(n!=2050) return CONN_SIZE;
  r.own_version=le16(b);r.peer_version=le16(b+2);
  if(r.own_version!=1||r.peer_version!=8 || (b[4]&1) || zero(b+4,6)) return CONN_FORMAT;
  r.payload_bytes=2048;
 } else return CONN_FORMAT;
 *out=r;return CONN_OK;
}
/* Candidate passive observation set only. This code DOES NOT read addresses.
 * BSP platform/include/mt6765.h and shipped WMT module identify these fields.
 * Physical acquisition needs a separately reviewed allowlist/identity binding.
 */
static const uint64_t addresses[]={0x10006180,0x10006184,0x1000632c,0x10001220,0x10001228,0x10001258,0x10007018,0x100053e0,0x100053f0};
size_t conn_register_count(void) { return sizeof(addresses)/sizeof(addresses[0]); }
uint64_t conn_register_address(size_t i) { return i<conn_register_count()?addresses[i]:0; }
int conn_state_parse(const uint8_t *b,size_t n,unsigned enabled,struct conn_state *out) {
 struct conn_state r={0}; uint32_t value[9]={0};size_t count,i,j;
 if(!b||!out||n<48||enabled>1) return CONN_SIZE;
 if(!equal(b,"MTKCONN1",8)||le16(b+8)!=1||le16(b+10)!=48||le16(b+14)!=24||le32(b+20)) return CONN_FORMAT;
 count=le16(b+12);if(count>9||n!=48+count*24||le32(b+16)!=n) return CONN_SIZE;
 r.begin=le64(b+24);r.end=le64(b+32);r.hz=le64(b+40);r.survey_enabled=enabled;
 if(!r.hz||r.hz>UINT64_C(10000000000)||r.end<r.begin||r.end-r.begin>r.hz*10) return CONN_RANGE;
 for(i=0;i<count;i++) {
  const uint8_t *s=b+48+i*24;uint64_t a=le64(s);uint32_t bit;
  for(j=0;j<conn_register_count()&&a!=addresses[j];j++) {}
  if(j==conn_register_count()||s[16]!=4||s[17]>3||!zero(s+18,6)) return CONN_FORMAT;
  bit=1u<<j;if(r.seen&bit) return CONN_DUPLICATE;r.seen|=bit;
  if(s[17]==3 && le32(s+8)==le32(s+12)) {r.stable|=bit;value[j]=le32(s+8);}
 }
 r.missing=0x1ffu&~r.stable;
 if(enabled && (r.stable&7)==7) {
  unsigned a=(value[0]>>1)&1,c=(value[1]>>1)&1;
  if(a!=c) r.power=CONN_TRANSITION;
  else if(!a) r.power=CONN_OFF;
  else if((value[2]&0x1f)!=0x0d || (value[2]&0x100)) r.power=CONN_ISOLATED;
  else if((r.stable&0x38)==0x38) {
   r.power=((value[3]|value[4])&0x6000)||(value[5]&0x40000)?CONN_ISOLATED:CONN_POWER_BITS_READY;
  }
 }
 *out=r;return CONN_OK;
}
