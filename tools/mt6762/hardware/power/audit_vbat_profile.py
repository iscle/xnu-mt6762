"""Pin VBAT admission to original artifacts, register fields and capture44."""
from pathlib import Path
import hashlib
import json
import re
import struct
from audit_adc_entry import array
from audit_battery_capture44 import properties

HERE=Path(__file__).resolve().parent
XNU=HERE.parents[3];PORT=XNU.parents[2]
BSP=Path('/mnt/0da18f53-c547-40a2-a7c3-b08e84d1aab4/alps/aosp-docker/workspace')
REGS=BSP/'kernel-4.14/include/linux/mfd/mt6357/registers.h'
PRELOADER=Path('/home/iscle/Documents/mini_iphone_dump_2/preloader.bin')
def identity(p):return {'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}

def main():
    source=REGS.read_text();plain=source.replace('\\\n','')
    definitions={m[1]:m[2].strip() for m in re.finditer(r'^#define (\w+)\s+([^\n]+)',plain,re.M)}
    def field(name):
        prefix='PMIC_'+name
        register=definitions[prefix+'_ADDR'];expression=definitions[register]
        address=int(re.search(r'\+0x([0-9a-f]+)',expression)[1],16)
        mask,shift=int(definitions[prefix+'_MASK'],0),int(definitions[prefix+'_SHIFT'],0)
        return {'name':name,'address':address,'mask':mask,'shift':shift,
                'source_line':source[:source.index('#define '+prefix+'_ADDR')].count('\n')+1}
    fields=[field(n) for n in ['RG_AUXADC_AO_1M_CK_PDN','RG_AUXADC_1M_CK_PDN_HWEN',
        'RG_AUXADC_1M_CK_PDN','RG_AUXADC_CK_PDN_HWEN','RG_AUXADC_CK_PDN',
        'RG_AUXADC_RNG_CK_PDN_HWEN','RG_AUXADC_RNG_CK_PDN','RG_AUXADC_32K_CK_PDN_HWEN',
        'RG_AUXADC_32K_CK_PDN','RG_AUXADC_1K_CK_PDN','RG_AUXADC_CK_DIVSEL',
        'RG_AUXADC_CK_TSTSEL','RG_AUXADC_INTRP_CK_PDN','RG_AUXADC_RST','RG_AUXADC_REG_RST',
        'BANK_HK_TOP_SWRST','BANK_AUXADC_SWRST','BANK_AUXADC_DIG_1_SWRST','BANK_AUXADC_DIG_2_SWRST',
        'BANK_AUXADC_DIG_3_SWRST','BANK_AUXADC_DIG_4_SWRST','AUXADC_RNG_EN','AUXADC_TEST_MODE',
        'AUXADC_START_SWCTRL','AUXADC_TS_VBE_SEL_SWCTRL','AUXADC_VBUF_EN_SWCTRL','AUXADC_OUT_SEL',
        'AUXADC_DATA_REUSE_EN','AUXADC_CH0_DATA_REUSE_EN','AUXADC_CH1_DATA_REUSE_EN','AUXADC_DCXO_DATA_REUSE_EN',
        'AUXADC_SW_GAIN_TRIM','AUXADC_SW_OFFSET_TRIM','AUXADC_TRIM_CH1_SEL']]
    binary=PRELOADER.read_bytes();assert identity(PRELOADER)['sha256']=='7e62da99110271864c330cffcef5237e20ca03881b933263af828561d963f674'
    tuples=[]
    for row in [(0xf8c,0xaa,0x3ff,0),(0xf8e,0,1,0),(0x114c,0x100,0x103,0)]:
        needle=struct.pack('<4H',*row);offset=binary.find(needle)
        assert offset>=0 and binary.find(needle,offset+1)<0
        tuples.append({'offset':offset,'address':row[0],'value':row[1],'mask':row[2],'shift':row[3]})
    header=HERE/'mt6762_vbat_profile.h';text=header.read_text()
    registers=array(text,'mt6762_vbat_entry_regs');expected=array(text,'mt6762_vbat_fixed_values')
    assert len(registers)==24 and len(expected)==19
    logpath=PORT/'hardware/trace-boot-20261025/capture44/xnu-log-ordered.bin'
    log=logpath.read_bytes();assert identity(logpath)['sha256']=='4eb9b9fb33eca61b4e852a257ac17160e117646c6e6140711fca13fd51279f2d'
    passes=[]
    for p in range(2):
        rows=[(int(a,16),int(v,16)) for a,v in re.findall(rb'^MT6762_ADC_ENTRY pass='+str(p).encode()+rb' index=\d+ address=([0-9a-f]+) value=([0-9a-f]+)',log,re.M)]
        assert rows==list(zip(registers[:19],expected));passes.append(rows)
    dtpath=PORT/'hardware/trace-boot-20261025/capture44/runtime.dtb'
    dt=properties(dtpath.read_bytes());adc='/pwrap@1000d000/main_pmic/pmic_auxadc';gauge='/pwrap@1000d000/main_pmic/mtk_gauge'
    selected={path+'/'+name:value.hex() for (path,name),value in dt.items() if
              path==adc+'/isense' or (path==adc and name in ['compatible','phandle','#io-channel-cells']) or
              (path==gauge and name in ['compatible','io-channels','io-channel-names'])}
    image=PORT/'firmware/Image';raw=image.read_bytes();base=0xffffff8008080000
    descriptor=0xffffff80098932c8+64;table=0xffffff8009105ef8+12
    assert struct.unpack_from('<III',raw,table-base)==(0x110e,1,0x108a)
    assert raw[descriptor-base+0x19]==15 and struct.unpack_from('<QQ',raw,descriptor-base+0x30)==(0,0)
    evidence={'schema':'mt6762-vbat-profile-source-v1','physical_new_observer_execution_proven':False,
        'provenance':[identity(p) for p in [image,PRELOADER,REGS,logpath,dtpath,header,
            HERE/'mt6762_vbat_fdt.c',XNU/'bsd/dev/mt6762_power.c',XNU/'bsd/dev/mt6762_vbat_observer.c',XNU/'bsd/dev/mt6762_battery_observer.c',
            XNU/'bsd/dev/mt6762_bif_protocol.h',XNU/'bsd/dev/mt6762_power_protocol.h',
            HERE/'test_vbat_profile.py',HERE/'test_vbat_observer_integration.c',HERE/'test_vbat_observer_integration.py',
            HERE/'test_battery_observer_integration.c',HERE/'emulate_stock_vbat.py',HERE/'audit_vbat_profile.py',
            HERE/'evidence/vbat-stock-disassembly.txt',HERE/'evidence/stock-vbat-vectors.json']],
        'field_catalog':fields,'preloader_table_tuples':tuples,'capture44_adc_passes':passes,
        'unobserved_control_addresses':registers[19:],'live_dt_properties_hex':selected,
        'required_masks':[{'address':a,'mask':m,'value':v} for a,m,v in [(0xf8c,0x3ff,0xaa),(0xf8e,7,0),(0xf90,0xff,0),(0x113e,0x3449,0),(0x114c,0x500,0)]],
        'original_request_read':{'function':hex(0xffffff8008b6aab8),'request':0x110e,'value':2,'result':0x108a,'avg_wait_us':[1280,1290]},
        'original_processed_conversion':{'function':hex(0xffffff8008b6b8fc),'resolution':15,'ratio':[3,1],'unit_mv':1800,'conversion_callback':0,'software_calibration_callback':0,
            'probe_hook_stores':['0xffffff8008b6b24c: DCXO convert','0xffffff8008b6b250: VBIF convert','0xffffff8008b6b254: BAT_TEMP calibration'],
            'scope':'Original cold descriptor plus init-probe writes; no reconstruction of mutable historical Android object.'},
        'reuse_boundary':{'global_bit':8,'channel1_bit':10,'preloader_sets_global_bit':True,
            'get_auxadc_out_reads_or_writes_114c':False,'boolean_coupling_proven':False,
            'policy':'Require both disabled; observe/log and refuse if either enabled. Do not infer independence from field names or issue a guessed configuration write.'},
        'per_acquisition':{'private_writes_max':1,'only_write':[0x110e,2],'configuration_reads':48,
            'freshness':'post-request READY low then high, bounded timeout, rail rejection, unchanged full profile, <=2s acquisition lease',
            'no_automatic_retry':True,'public_pwrap_writes':False,'charger_control':False,'ntc_or_bif_or_tdet_writes':False},
        'validation':{'host_wacs_faults':215,'host_config_changes':48,'host_expiry_positions':54,
            'fdt_tests':7,'original_arm64_vectors':9,'absolute_physical_voltage_calibration_claimed':False}}
    out=HERE/'evidence/vbat-profile-source.json';out.write_text(json.dumps(evidence,indent=2)+'\n')
    print('PASS: original table/register/request/conversion provenance and capture44 profile; '+identity(out)['sha256'])
if __name__=='__main__':main()
