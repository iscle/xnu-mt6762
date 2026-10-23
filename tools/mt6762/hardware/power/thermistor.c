#include "thermistor.h"
/* Recovered Fg_Temperature_Table at stock VA 0xffffff800987b7d8.
 * Nominal degrees C = -40 + 5*index; resistance in ohms. */
static const uint32_t resistance[]={195652,148171,113347,87559,68237,
 53650,42506,33892,27219,22021,17926,14674,12081,10000,8315,6948,
 5834,4917,4161,3535,3014};
int mt6357_ntc_temperature(uint32_t adc_mv,uint32_t pullup_mv,
                          uint32_t pullup_ohms,int *out_deci_c)
{
    uint64_t r;
    unsigned i;
    if (!out_deci_c || !adc_mv || adc_mv>=pullup_mv || !pullup_ohms)
        return -1;
    r=(uint64_t)adc_mv*pullup_ohms/(pullup_mv-adc_mv);
    if (r>resistance[0] || r<resistance[20]) return -1;
    for(i=1;i<21;i++) {
        if(r>=resistance[i]) {
            int cold=-400+50*(int)(i-1),warm=cold+50;
            int64_t numerator=(int64_t)(r-resistance[i])*cold+
                (int64_t)(resistance[i-1]-r)*warm;
            *out_deci_c=(int)(numerator/(resistance[i-1]-resistance[i]));
            return 0;
        }
    }
    return -1;
}

int mt6357_ntc_compensated_temperature(uint32_t adc_mv,uint32_t bif_mv,
    uint32_t pullup_ohms,int32_t current_ua,uint32_t com_fg,
    uint32_t com_rfg,unsigned no_comp,int *out_deci_c)
{
    int64_t current=current_ua;
    int64_t delta,corrected,bif;
    uint64_t resistance;
    if(no_comp>1 || !out_deci_c) return -1;
    if(current<0) current=-current;
    resistance=(no_comp?0:(uint64_t)com_fg)+com_rfg;
    /* Original current is in 0.1 mA and truncates to whole mA first. */
    delta=(int64_t)(((uint64_t)(current/1000)*resistance)/10000);
    if(current_ua>0) delta=-delta;
    corrected=(int64_t)adc_mv+delta;
    bif=(int64_t)bif_mv+delta;
    if(corrected<=0 || corrected>UINT32_MAX || bif<=0 || bif>UINT32_MAX)
        return -1;
    return mt6357_ntc_temperature((uint32_t)corrected,(uint32_t)bif,
                                  pullup_ohms,out_deci_c);
}
