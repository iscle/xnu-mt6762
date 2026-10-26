"""Host-execute the actual kernel's passive PMIC probe; never access hardware."""
from pathlib import Path
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
SOURCE=(HERE.parents[3]/'bsd/dev/mt6762_power.c').read_text()

def function(name):
    marker=SOURCE.index(name+'(')
    begin=SOURCE.rfind('\n',0,marker)+1
    opening=SOURCE.index('{',marker)
    depth=1;end=opening+1
    while depth:
        depth+=(SOURCE[end]=='{')-(SOURCE[end]=='}');end+=1
    return SOURCE[begin:end]+'\n'

HARNESS=r'''
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>
#include "mt6762_pmic_entry.h"
static int pwrap_ready,pwrap_read_only,pwrap_fault;
static unsigned reads,starts[2],entries[2],completions[2],failures[2];
static int fail_at,bad_id_at,adc_only;
static char messages[16384];
static const uint16_t original[]={0x8,0xc0c,0xd08,0xd0a,0xc8e,0xc90,
    0xd94,0xd96,0xe08,0x108a,0x108e,0x109e,0x1236};
static const uint16_t adc[]={0x8,0xa,0x10de,0x10e0,0x1120,0x1126,
    0x1128,0x112e,0x1132,0x1136,0x113a,0x113c,0x1008,
    0x11a2,0x11a4,0x11a6,0x11a8,0x11aa,0x11ac};
static uint16_t address_at(unsigned index) {
    if(adc_only){assert(index<38);return adc[index%19];}
    assert(index<64);return index<26?original[index%13]:adc[(index-26)%19];
}
static int mt6762_pwrap_read16(uint16_t address,uint16_t *value) {
    unsigned index=reads++;
    assert(address==address_at(index));
    if((int)index==fail_at){pwrap_fault=1;return -71;}
    *value=address==8?0x5730:(uint16_t)(index|0x8000);
    if((int)index==bad_id_at)*value=0xffff;
    return 0;
}
static void kprintf(const char *format,...) {
    char text[512];va_list ap;va_start(ap,format);
    vsnprintf(text,sizeof(text),format,ap);va_end(ap);
    assert(strlen(messages)+strlen(text)<sizeof(messages));strcat(messages,text);
    unsigned kind=!!strstr(text,"MT6762_ADC_ENTRY");
    if(!kind)assert(strstr(text,"MT6762_PMIC_ENTRY"));
    if(strstr(text,"_BEGIN ")) {
        assert(strstr(text,kind?
            "version=1 passes=2 registers=19 conversion_requested=0 gauge_commands=0":
            "version=1 passes=2 registers=13 conversion_requested=0 gauge_commands=0"));
        starts[kind]++;
    }else if(strstr(text,"_FAILED "))failures[kind]++;
    else if(strstr(text,"_COMPLETE ")) {
        assert(strstr(text,"measurement_valid=0 ownership_grant=0"));
        if(kind)assert(strstr(text,"calibration_grant=0"));
        completions[kind]++;
    }else {
        assert(strstr(text,kind?"MT6762_ADC_ENTRY pass=":"MT6762_PMIC_ENTRY pass="));
        entries[kind]++;
    }
}
'''
CASES=r'''
static void reset(void) {
    reads=0;memset(starts,0,sizeof(starts));memset(entries,0,sizeof(entries));
    memset(completions,0,sizeof(completions));memset(failures,0,sizeof(failures));
    messages[0]=0;adc_only=0;
    fail_at=bad_id_at=-1;pwrap_ready=pwrap_read_only=1;pwrap_fault=0;
}
static void check_failure(unsigned at,int transport) {
    unsigned kind=adc_only || at>=26;
    unsigned index=kind?(adc_only?at:at-26):at;
    unsigned count=kind?19:13;
    char expected[256];
    snprintf(expected,sizeof(expected),
        "%s_FAILED pass=%u index=%u address=%04x error=%d transport=%d value=%04x\n",
        kind?"MT6762_ADC_ENTRY":"MT6762_PMIC_ENTRY",index/count,index%count,
        address_at(at),transport?-2:-3,transport?-71:0,transport?0:0xffff);
    assert(strstr(messages,expected));
    assert(reads==at+1 && failures[kind]==1 && !failures[!kind]);
    unsigned old_done=adc_only?0:(at<26?at/13:2);
    unsigned adc_done=kind?index/19:0;
    assert(completions[0]==old_done && entries[0]==13*old_done);
    assert(completions[1]==adc_done && entries[1]==19*adc_done);
    assert(starts[0]==(unsigned)!adc_only && starts[1]==kind);
}
int main(void) {
    reset();pmic_entry_probe();
    assert(reads==64 && starts[0]==1 && entries[0]==26 && completions[0]==2 && !failures[0]);
    assert(starts[1]==1 && entries[1]==38 && completions[1]==2 && !failures[1]);
    /* Prefix remains exactly the original two13-word passes. The new prefix
     * is appended only after the original completion, preserving decoders. */
    const char *old_end=strstr(messages,"MT6762_PMIC_ENTRY_COMPLETE pass=1 measurement_valid=0 ownership_grant=0\n");
    assert(old_end && strstr(messages,"MT6762_ADC_ENTRY_BEGIN ")>old_end);
    for(int i=0;i<64;i++) {
        reset();fail_at=i;pmic_entry_probe();
        check_failure((unsigned)i,1);
        assert(pwrap_fault);pmic_entry_probe();assert(reads==(unsigned)i+1);
    }
    static const int id_indices[]={0,13,26,45};
    for(unsigned i=0;i<4;i++) {
        reset();bad_id_at=id_indices[i];pmic_entry_probe();
        check_failure((unsigned)bad_id_at,0);
    }
    reset();adc_only=1;pmic_adc_entry_probe();
    assert(reads==38 && !starts[0] && starts[1]==1 && entries[1]==38 && completions[1]==2);
    for(int i=0;i<38;i++) {
        reset();adc_only=1;fail_at=i;pmic_adc_entry_probe();check_failure((unsigned)i,1);
        pmic_adc_entry_probe();assert(reads==(unsigned)i+1);
    }
    for(int pass=0;pass<2;pass++) {
        reset();adc_only=1;bad_id_at=19*pass;pmic_adc_entry_probe();
        check_failure((unsigned)bad_id_at,0);
    }
    for(int direct=0;direct<2;direct++)for(int gate=0;gate<3;gate++) {
        reset();adc_only=direct;
        if(gate==0)pwrap_ready=0;
        if(gate==1)pwrap_read_only=0;
        if(gate==2)pwrap_fault=1;
        if(direct)pmic_adc_entry_probe();else pmic_entry_probe();
        assert(!reads && !starts[0] && !starts[1] && !messages[0]);
    }
    puts("native PMIC/ADC probes: old records preserved, readonly gates, all64 failures, identity stop, no measurement grants PASS");
}
'''

with tempfile.TemporaryDirectory() as temporary:
    source=Path(temporary)/'probe.c';binary=Path(temporary)/'probe'
    source.write_text(HARNESS+function('pmic_entry_read')+function('pmic_adc_entry_probe')+
                      function('pmic_entry_probe')+CASES)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HERE),
                    str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
