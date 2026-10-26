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
static unsigned reads,starts,entries,completions,failures;
static int fail_at,bad_id_at;
static int mt6762_pwrap_read16(uint16_t address,uint16_t *value) {
    unsigned index=reads++;
    assert(index<26 && address==mt6762_pmic_entry_regs[index%13]);
    if((int)index==fail_at){pwrap_fault=1;return -71;}
    *value=address==8?0x5730:(uint16_t)(index|0x8000);
    if((int)index==bad_id_at)*value=0xffff;
    return 0;
}
static void kprintf(const char *format,...) {
    char text[512];va_list ap;va_start(ap,format);
    vsnprintf(text,sizeof(text),format,ap);va_end(ap);
    if(strstr(text,"_BEGIN "))starts++;
    else if(strstr(text,"_FAILED "))failures++;
    else if(strstr(text,"_COMPLETE ")) {
        assert(strstr(text,"measurement_valid=0 ownership_grant=0"));completions++;
    }else {assert(strstr(text,"MT6762_PMIC_ENTRY pass="));entries++;}
}
'''
CASES=r'''
static void reset(void) {
    reads=starts=entries=completions=failures=0;
    fail_at=bad_id_at=-1;pwrap_ready=pwrap_read_only=1;pwrap_fault=0;
}
int main(void) {
    reset();pmic_entry_probe();
    assert(reads==26 && starts==1 && entries==26 && completions==2 && !failures);
    for(int i=0;i<26;i++) {
        reset();fail_at=i;pmic_entry_probe();
        assert(reads==(unsigned)i+1 && starts==1 && failures==1);
        assert(entries==(i>=13?13u:0u) && completions==(i>=13?1u:0u));
        assert(pwrap_fault);pmic_entry_probe();assert(reads==(unsigned)i+1);
    }
    for(int pass=0;pass<2;pass++) {
        reset();bad_id_at=13*pass;pmic_entry_probe();
        assert(reads==(unsigned)bad_id_at+1 && failures==1);
        assert(completions==(unsigned)pass && entries==13u*(unsigned)pass);
    }
    reset();pwrap_ready=0;pmic_entry_probe();assert(!reads && !starts);
    reset();pwrap_read_only=0;pmic_entry_probe();assert(!reads && !starts);
    reset();pwrap_fault=1;pmic_entry_probe();assert(!reads && !starts);
    puts("native passive PMIC probe: read-only gate, two passes, fault/identity stop PASS");
}
'''

with tempfile.TemporaryDirectory() as temporary:
    source=Path(temporary)/'probe.c';binary=Path(temporary)/'probe'
    source.write_text(HARNESS+function('pmic_entry_read')+function('pmic_entry_probe')+CASES)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I',str(HERE),
                    str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)
