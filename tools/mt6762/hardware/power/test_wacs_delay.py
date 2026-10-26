"""Run the actual short-poll wrapper with a deterministic13MHz clock."""
from pathlib import Path
import subprocess,tempfile
HERE=Path(__file__).resolve().parent
source=(HERE.parents[3]/'bsd/dev/mt6762_power.c').read_text()
start=source.index('static void pwrap_wacs_delay('); opening=source.index('{',start)
end=opening+1;depth=1
while depth:
    depth+=(source[end]=='{')-(source[end]=='}');end+=1
function=source[start:end]
assert function.count('__asm__ volatile("yield" ::: "memory");')==1
function=function.replace('__asm__ volatile("yield" ::: "memory");','hints++;')
header=r'''
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#define NSEC_PER_USEC 1000
static uint64_t ticks;
static unsigned hints,sleeps,last_sleep,clock_reads;
static void delay(unsigned us){sleeps++;last_sleep=us;}
static uint64_t mach_absolute_time(void){clock_reads++;return ticks++;}
static void clock_interval_to_absolutetime_interval(unsigned us,unsigned scale,uint64_t *result){
 assert(scale==1000);*result=(uint64_t)us*13;
}
'''
cases=r'''
int main(void){
 pwrap_wacs_delay(0,0);assert(!clock_reads && !sleeps && !hints);
 for(unsigned us=1;us<=10;us++){
  uint64_t initial=ticks;unsigned previous=hints;
  pwrap_wacs_delay(0,us);
  assert(!sleeps && ticks-initial>=us*13 && hints-previous==us*13-1);
 }
 ticks=UINT64_MAX-4;unsigned previous=hints;
 pwrap_wacs_delay(0,10);assert(ticks==126 && hints-previous==129);
 unsigned reads=clock_reads;pwrap_wacs_delay(0,11);
 assert(sleeps==1 && last_sleep==11 && reads==clock_reads);
 puts("PASS: actual WACS short-poll wrapper,13MHz elapsed timing/wrap/zero/long-delay fallback");
}
'''
with tempfile.TemporaryDirectory() as tmp:
 p=Path(tmp);(p/'test.c').write_text(header+function+cases)
 subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=5)
