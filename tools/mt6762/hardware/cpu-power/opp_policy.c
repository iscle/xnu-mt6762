#include "opp_policy.h"
/* Exact stock level4 tables; see evidence/stock-opp-tables.json. */
static const struct mt6762_nominal_opp opps[3][16]={
 {
  {2001000,1118750,1,1,0},
  {1961000,1068750,1,1,1},
  {1927000,1025000,1,1,2},
  {1897000,987500,1,1,3},
  {1868000,950000,1,1,4},
  {1838000,912500,1,1,5},
  {1809000,875000,1,1,6},
  {1779000,837500,1,1,7},
  {1750000,800000,1,1,8},
  {1617000,768750,1,1,9},
  {1484000,737500,2,1,10},
  {1351000,706250,2,1,11},
  {1218000,675000,2,1,12},
  {1085000,643750,2,1,13},
  {979000,618750,2,1,14},
  {900000,600000,2,1,15},
 },
 {
  {1500000,1118750,2,1,0},
  {1429000,1068750,2,1,1},
  {1367000,1025000,2,1,2},
  {1314000,987500,2,1,3},
  {1261000,950000,2,1,4},
  {1208000,912500,2,1,5},
  {1155000,875000,2,1,6},
  {1102000,837500,2,1,7},
  {1050000,800000,2,1,8},
  {948000,768750,2,1,9},
  {846000,737500,2,1,10},
  {745000,706250,4,1,11},
  {643000,675000,4,1,12},
  {542000,643750,4,1,13},
  {501000,631250,4,1,14},
  {400000,600000,4,2,15},
 },
 {
  {1048000,1118750,2,1,0},
  {997000,1068750,2,1,1},
  {953000,1025000,2,1,2},
  {915000,987500,2,1,3},
  {877000,950000,2,1,4},
  {839000,912500,2,1,5},
  {801000,875000,2,1,6},
  {763000,837500,2,1,7},
  {724000,800000,4,1,8},
  {658000,768750,4,1,9},
  {592000,737500,4,1,10},
  {525000,706250,4,1,11},
  {459000,675000,4,2,12},
  {392000,643750,4,2,13},
  {339000,618750,4,2,14},
  {300000,600000,4,2,15},
 },
};
int mt6762_c62_select(enum mt6762_domain d,uint32_t request,uint32_t floor,
                     uint32_t cap,uint32_t thermal,struct mt6762_nominal_opp *out)
{
    unsigned i;
    uint32_t limit=request;
    if ((unsigned)d>=3 || !out || !request || !floor || !cap || !thermal) return -1;
    if (cap<limit) limit=cap;
    if (thermal<limit) limit=thermal;
    if (floor>limit) return -1;
    for(i=0;i<16;i++) {
        if(opps[d][i].khz<=limit && opps[d][i].khz>=floor) {
            *out=opps[d][i]; return 0;
        }
    }
    return -1;
}
int mt6762_c62_shared_voltage(const uint8_t idx[3],uint32_t *out)
{
    uint32_t v=0;
    unsigned d;
    if(!idx || !out) return -1;
    for(d=0;d<3;d++) {
        if(idx[d]>=16) return -1;
        if(opps[d][idx[d]].nominal_uv>v) v=opps[d][idx[d]].nominal_uv;
    }
    *out=v;return 0;
}
int mt6357_selector_for_window(uint32_t min,uint32_t max,uint8_t *sel,uint32_t *actual)
{
    uint32_t s,v;
    if(!sel || !actual || min<518750 || min>max || max>1312500) return -1;
    s=(min-518750+6249)/6250;
    if(s>127) return -1;
    v=518750+s*6250;
    if(v>max) return -1;
    *sel=(uint8_t)s;*actual=v;return 0;
}
int mt6762_sspm_vote(enum mt6762_domain d,unsigned index,unsigned counter,
                    uint32_t *offset,uint32_t *word)
{
    if((unsigned)d>=3 || index>=16 || !counter || counter>255 || !offset || !word)
        return -1;
    *offset=0x3a4+4*(unsigned)d;
    *word=(counter<<4)|index;return 0;
}
