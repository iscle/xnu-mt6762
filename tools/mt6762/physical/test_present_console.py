#!/usr/bin/env python3
"""Compile the actual MiniFB draw method with guarded host service stubs.

This checks handoff control flow, not IOKit scheduling or physical scanout.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[3]
CPP = ROOT / 'iokit/Kernel/MiniIOMobileFramebuffer.cpp'
PRELUDE = r'''
#include <cassert>
#include <cstdint>
#include <climits>
#include <cstdlib>
#include <cstdarg>
#include <vector>
#define IONew(type, count) new type[count]
#define IODelete(pointer, type, count) delete[] pointer
#define THREAD_UNINT 0
constexpr int kPEReleaseScreen=1, kPEGraphicsMode=2;
static std::vector<int> commands;
static bool console_enabled=true;
static unsigned log_count=0;
void PE_initialize_console(void *, int command) {
 commands.push_back(command);
 if(command==kPEReleaseScreen) console_enabled=false;
}
void kprintf(const char *, ...) { ++log_count; }
void IOLockLock(void *) {}
void IOLockUnlock(void *) {}
void IOLockWakeup(void *, void *, bool) {}
void IOLockSleep(void *, unsigned *busy, int) {*busy=0;}
static int gFilter=0;
static int64_t sample_at(int32_t, int32_t, int32_t) {return 0;}
struct MiniIOSurface {
 struct {uint32_t width=4,height=4,bytesPerRow=16;} info;
 uint8_t backing[64]={}; bool missing=false;
 const uint8_t *pixels() {return missing?nullptr:backing;}
};
struct RowJob {
 const uint8_t *pixels; uint32_t stride;
 int32_t sx,sy,sw,sh,px0,py0,px1,py1,cx0,cx1;
 bool filter,unscaled;
};
class IOMobileFramebuffer {
public:
 uint32_t fWidth=4,fHeight=4,fPanelWidth=4,fPanelHeight=4;
 uint32_t fBlendRowSize=0,*fBlendRow=nullptr,*fHelperBlend[8]={};
 uint32_t fThreads=1, fHelpersStarted=0,fHelpersBusy=0,fHelperGeneration=0;
 uint32_t fColumn[4]={}; uint16_t fColumnWeight[4]={};
 bool fDiff=false,fGraphics=false;
 void *fHelperLock=nullptr; RowJob *fHelperJob=nullptr;
 unsigned draws=0;
 void drawRows(const RowJob *, int32_t,int32_t,uint32_t *) {
#ifdef ARM64_BOARD_CONFIG_MT6762
 assert(!console_enabled && fGraphics);
#endif
 ++draws;
 }
 void drawLayer(MiniIOSurface *,const int32_t *,const int32_t *);
};
'''
MAIN = r'''
int main() {
 IOMobileFramebuffer f; MiniIOSurface surface;
 int32_t src[4]={0,0,4,4},dst[4]={0,0,4,4};
#ifdef ARM64_BOARD_CONFIG_MT6762
 // Invalid source, overflowing endpoint, invisible/offscreen destinations,
 // zero-size surface, and missing backing must retain the diagnostic console.
 src[0]=-1; f.drawLayer(&surface,src,dst); src[0]=INT32_MAX;
 f.drawLayer(&surface,src,dst); src[0]=0;
 dst[0]=-8; f.drawLayer(&surface,src,dst); dst[0]=8;
 f.drawLayer(&surface,src,dst); dst[0]=0;dst[1]=8;
 f.drawLayer(&surface,src,dst);dst[1]=-8;f.drawLayer(&surface,src,dst);dst[1]=0;
 dst[0]=INT32_MAX; f.drawLayer(&surface,src,dst);dst[0]=0;
 surface.info.width=0;f.drawLayer(&surface,src,dst);surface.info.width=4;
 surface.missing=true;f.drawLayer(&surface,src,dst);surface.missing=false;
 assert(commands.empty() && console_enabled && !f.fGraphics && !f.draws);
 f.drawLayer(&surface,src,dst);
 assert(commands.size()==2 && commands[0]==kPEReleaseScreen && commands[1]==kPEGraphicsMode);
 assert(f.draws==1 && log_count==2);
 f.drawLayer(&surface,src,dst);
 assert(commands.size()==2 && f.draws==2 && log_count==2);
 // The split helper path also retires the console before any row callback.
 IOMobileFramebuffer parallel;parallel.fThreads=2;parallel.fHelpersStarted=1;
 commands.clear();console_enabled=true;
 parallel.drawLayer(&surface,src,dst);
 assert(commands.size()==2 && parallel.draws==1 && !console_enabled);
 // Zero/negative extents mean the existing full-surface/full-display fallback.
 IOMobileFramebuffer fallback;commands.clear();console_enabled=true;
 src[2]=src[3]=dst[2]=dst[3]=0;
 fallback.drawLayer(&surface,src,dst);assert(fallback.draws==1 && commands.size()==2);
#else
 f.drawLayer(&surface,src,dst);
 assert(f.draws==1 && commands.empty() && console_enabled);
#endif
 return 0;
}
'''
class PresentationTests(unittest.TestCase):
 def test_actual_draw_method_handoff_and_rejected_geometry(self):
  text=CPP.read_text()
  begin=text.index('void\nIOMobileFramebuffer::drawLayer(')
  end=text.index('\n/*\n * How evenly',begin)
  with tempfile.TemporaryDirectory() as tmp:
   source=Path(tmp)/'test.cpp';source.write_text(PRELUDE+text[begin:end]+MAIN)
   for mtk in (False, True):
    binary=Path(tmp)/('mtk' if mtk else 'other')
    subprocess.run(['c++','-std=c++17','-O2','-Wall','-Wextra','-Werror',
      *(['-DARM64_BOARD_CONFIG_MT6762=1'] if mtk else []),str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True,timeout=10)
 def test_blank_and_format_guards_precede_draw(self):
  text=CPP.read_text();show=text[text.index('IOMobileFramebuffer::show('):]
  blank=show.index('if (fNativeBlanked)');draw=show.index('drawLayer(s, src, dst)')
  self.assertLess(blank,draw)
  self.assertIn('return;',show[blank:show.index('#endif',blank)])
  self.assertLess(show.index('if (s == NULL)'),draw)
  self.assertLess(show.index('s->info.bytesPerElement == 4 && s->info.planeCount == 0'),draw)
  # Source semantics establishing the bug: graphics intent alone does not disable.
  video=(ROOT/'osfmk/console/video_console.c').read_text()
  graphics=video[video.index('case kPEGraphicsMode:'):].split('break;',1)[0]
  release=video[video.index('case kPEReleaseScreen:'):].split('break;',1)[0]
  self.assertNotIn('gc_enable(FALSE)',graphics)
  self.assertIn('gc_enable(FALSE)',release.replace(' ',''))
if __name__=='__main__':unittest.main()
