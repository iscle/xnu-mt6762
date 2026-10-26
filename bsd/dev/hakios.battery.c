/*
 * Battery monitor for Xiaomi redwood (POCO X5 Pro).
 *
 * The phone selects PM7325B and qcom,battery-charger over PMIC GLINK/ADSP, not
 * the local PM7250B/QG layout.  The resident UEFI contains the matching
 * Qualcomm charger drivers.  xnuloader owns that firmware context on core 0,
 * polls it, and publishes a read-only cache; XNU only consumes that cache.
 * Charger limits and JEITA protection therefore remain firmware-owned.
 */
#include <kern/clock.h>
#include <kern/locks.h>
#include "../../tools/mt6762/hardware/power/report_expiry.h"
#include <kern/thread.h>
#include <libkern/libkern.h>
#include <mach/mach_types.h>
#include <pexpert/pexpert.h>
#include <sys/hakios.input.h>
#include <sys/mt6762_power.h>
#include <sys/sysctl.h>
#include <sys/systm.h>

extern vm_offset_t ml_io_map(vm_offset_t phys_addr, vm_size_t size);

#define LOADER_BATTERY_MAGIC            0x2154544142574452ULL
#define LOADER_BATTERY_VERSION          1
#define LOADER_BATTERY_VALID            (1u << 0)
#define LOADER_BATTERY_PRESENT          (1u << 1)
#define LOADER_BATTERY_CHARGER_PRESENT  (1u << 2)
#define LOADER_BATTERY_VOLTAGE_VALID    (1u << 3)
#define LOADER_BATTERY_CHARGING         (1u << 4)
#define LOADER_BATTERY_SOC_ESTIMATED    (1u << 5)
#define LOADER_PAGE_SIZE                0x4000UL

struct loader_battery {
	uint64_t magic;
	uint32_t version, size;
	volatile uint32_t sequence;
	uint32_t flags;
	int32_t soc_percent, voltage_mv, current_ma, temperature_c;
	uint32_t charger_action, polls, failures, reserved;
};

static volatile struct loader_battery *shared_battery;
static int battery_soc_percent = -1, battery_voltage_mv = -1, battery_current_ma;
static int battery_temperature_c = -273, battery_present, battery_charger_present;
static int battery_charging, battery_soc_estimated, battery_charger_action = -1;
static uint64_t battery_updates, battery_failures;

/* Native MT6762 observations use their own ordered, expiring snapshot. The
 * legacy redwood loader/ADSP scalars retain their existing behavior. Never hold
 * this lock while calling IOKit or acquiring a power/ADC/gauge lock. */
static LCK_GRP_DECLARE(native_battery_group,"mt6762-battery-report");
static LCK_MTX_DECLARE(native_battery_mutex,&native_battery_group);
static struct mt6762_battery_sample native_battery_sample;
static struct mt6762_report_expiry native_battery_age;
static int native_battery_seen;
enum { NATIVE_SOC,NATIVE_VOLTAGE,NATIVE_CURRENT,NATIVE_TEMPERATURE,NATIVE_PRESENT,
    NATIVE_EXTERNAL,NATIVE_CHARGING,NATIVE_ESTIMATED,NATIVE_ACTION,NATIVE_FULL,
    NATIVE_DESIGN,NATIVE_CYCLES,NATIVE_DSP };
static int
native_battery_snapshot(struct mt6762_battery_sample *sample)
{
    uint64_t now;
    int seen;
    lck_mtx_lock(&native_battery_mutex);
    clock_get_uptime(&now);
    seen=native_battery_seen;
    if(seen) {
        (void)mt6762_report_expire(&native_battery_age,now);
        *sample=native_battery_sample;
        if(!native_battery_age.active)sample->valid=0;
    }
    lck_mtx_unlock(&native_battery_mutex);
    return seen;
}
uint32_t
mt6762_battery_valid_fields(void)
{
    struct mt6762_battery_sample sample;
    return native_battery_snapshot(&sample)?sample.valid:0;
}
static int
battery_scalar(unsigned field,int legacy)
{
    struct mt6762_battery_sample b;
    if(!native_battery_snapshot(&b))return legacy;
    const uint32_t v=b.valid;
    switch(field) {
    case NATIVE_SOC:return (v&MT6762_BAT_SOC)?(b.percent_hundredths+50)/100:-1;
    case NATIVE_VOLTAGE:return (v&MT6762_BAT_VOLTAGE)?b.voltage_uv/1000:-1;
    case NATIVE_CURRENT:return (v&MT6762_BAT_CURRENT)?b.current_ua/1000:(-2147483647-1);
    case NATIVE_TEMPERATURE:return (v&MT6762_BAT_TEMP)?b.temperature_hundredths/100:-273;
    case NATIVE_PRESENT:return (v&MT6762_BAT_PRESENT)?!!b.present:-1;
    case NATIVE_EXTERNAL:return (v&MT6762_BAT_EXTERNAL)?!!b.external:-1;
    case NATIVE_CHARGING:return (v&(MT6762_BAT_STATUS|MT6762_BAT_EXTERNAL))==
        (MT6762_BAT_STATUS|MT6762_BAT_EXTERNAL)?(!!b.external && b.status==1):-1;
    case NATIVE_ACTION:return (v&MT6762_BAT_STATUS)?b.status:-1;
    default:return 0; /* No learned capacity/cycles/estimated SOC or ADSP source. */
    }
}
/* For the flashlight thermal guard: -273 is unknown, including expired native data. */
int hakios_battery_temperature(void)
{
    return battery_scalar(NATIVE_TEMPERATURE,battery_temperature_c);
}
static int battery_scalar_sysctl SYSCTL_HANDLER_ARGS
{
    int value=battery_scalar((unsigned)arg2,*(int *)arg1);
    return sysctl_handle_int(oidp,&value,0,req);
}
SYSCTL_NODE(_kern, OID_AUTO, hakios, CTLFLAG_RW | CTLFLAG_LOCKED, 0, "redwood phone bits");
#define BATTERY_SCALAR(name,variable,field,description) \
    SYSCTL_PROC(_kern_hakios,OID_AUTO,name,CTLTYPE_INT|CTLFLAG_RD|CTLFLAG_LOCKED, \
        &variable,field,battery_scalar_sysctl,"I",description)
BATTERY_SCALAR(battery_soc,battery_soc_percent,NATIVE_SOC,"Battery SOC, -1 unknown");
BATTERY_SCALAR(battery_voltage_mv,battery_voltage_mv,NATIVE_VOLTAGE,"Battery voltage mV, -1 unknown");
BATTERY_SCALAR(battery_current_ma,battery_current_ma,NATIVE_CURRENT,"Battery current mA; INT_MIN unknown native MT6762");
BATTERY_SCALAR(battery_temperature_c,battery_temperature_c,NATIVE_TEMPERATURE,"Battery temperature C, -273 unknown");
BATTERY_SCALAR(battery_present,battery_present,NATIVE_PRESENT,"Battery present0/1, -1 unknown native MT6762");
BATTERY_SCALAR(battery_charger_present,battery_charger_present,NATIVE_EXTERNAL,"Charger present0/1, -1 unknown native MT6762");
BATTERY_SCALAR(battery_charging,battery_charging,NATIVE_CHARGING,"Charging0/1, -1 unknown native MT6762");
BATTERY_SCALAR(battery_soc_estimated,battery_soc_estimated,NATIVE_ESTIMATED,"SOC estimated from voltage");
BATTERY_SCALAR(battery_charger_action,battery_charger_action,NATIVE_ACTION,"Last charger action; -1 unknown native MT6762");

static bool
battery_snapshot(struct loader_battery *out)
{
	uint32_t before, after;

	for (unsigned retry = 0; retry < 4; retry++) {
		before = shared_battery->sequence;
		if (before & 1) continue;
		__asm__ volatile ("dmb ishld" ::: "memory");
		memcpy(out, (const void *)(uintptr_t)shared_battery, sizeof(*out));
		__asm__ volatile ("dmb ishld" ::: "memory");
		after = shared_battery->sequence;
		if (before == after && !(after & 1)) return true;
	}
	return false;
}

static void
battery_poll(void)
{
	struct loader_battery sample;

	if (!battery_snapshot(&sample) || sample.magic != LOADER_BATTERY_MAGIC ||
	    sample.version != LOADER_BATTERY_VERSION || sample.size < sizeof(sample) ||
	    !(sample.flags & LOADER_BATTERY_VALID) || sample.soc_percent < 0 || sample.soc_percent > 100) {
		battery_failures++;
		return;
	}
	battery_soc_percent = sample.soc_percent;
	battery_voltage_mv = (sample.flags & LOADER_BATTERY_VOLTAGE_VALID) ? sample.voltage_mv : -1;
	battery_current_ma = sample.current_ma;
	battery_temperature_c = sample.temperature_c;
	battery_present = (sample.flags & LOADER_BATTERY_PRESENT) != 0;
	battery_charger_present = (sample.flags & LOADER_BATTERY_CHARGER_PRESENT) != 0;
	battery_charging = (sample.flags & LOADER_BATTERY_CHARGING) != 0;
	battery_soc_estimated = (sample.flags & LOADER_BATTERY_SOC_ESTIMATED) != 0;
	battery_charger_action = (int)sample.charger_action;
	battery_updates++;
}

/*
 * What the audio DSP's battery manager says (bsd/dev/hakios.adsp.c, with adsp=1 unless battmgr=0):
 * the values that Android shows, from where Android takes them. They are kept here for the sysctls
 * and passed on to the power source that iOS reads (iokit/Kernel/hakios.battery.cpp).
 */
static int battery_full_uah, battery_design_uah, battery_cycles, battery_source_dsp;

BATTERY_SCALAR(battery_full_uah,battery_full_uah,NATIVE_FULL,"Learned full charge uAh,0unknown");
BATTERY_SCALAR(battery_design_uah,battery_design_uah,NATIVE_DESIGN,"Design charge uAh,0unknown");
BATTERY_SCALAR(battery_cycles,battery_cycles,NATIVE_CYCLES,"Battery cycles,0unknown");
BATTERY_SCALAR(battery_from_dsp,battery_source_dsp,NATIVE_DSP,"Battery source is ADSP");
#undef BATTERY_SCALAR

extern void HakiosBatteryReport(const void *state, unsigned size);     /* iokit/Kernel/hakios.battery.cpp */

void
hakios_battery_report(const struct hakios_battery_state *b)
{
	int percent = (b->percent_hundredths + 50) / 100;

	battery_soc_percent = percent < 0 ? 0 : percent > 100 ? 100 : percent;
	battery_voltage_mv = b->voltage_uv / 1000;
	battery_current_ma = b->current_ua / 1000;
	battery_temperature_c = (b->temperature_hundredths + 50) / 100;
	battery_present = b->present != 0;
	battery_charger_present = b->external != 0;
	battery_charging = b->status == 1;      /* POWER_SUPPLY_STATUS_CHARGING */
	battery_soc_estimated = 0;
	battery_charger_action = b->status;
	if (b->full_uah > 0) {
		battery_full_uah = b->full_uah;
	}
	if (b->design_uah > 0) {
		battery_design_uah = b->design_uah;
	}
	if (b->cycles > 0) {
		battery_cycles = b->cycles;
	}
	battery_source_dsp = 1;
	battery_updates++;
	HakiosBatteryReport(b, sizeof(*b));
}

/* Native MT6762 samples are partial. Unknown values must not become 0% or
 * the stock driver's constant 25 C. The validity mask accompanies sysctls. */
extern void HakiosBatteryReportPartial(const void *state, unsigned size);
void
mt6762_battery_report(const struct mt6762_battery_sample *b)
{
    struct mt6762_battery_sample report;
    uint64_t now,maximum_age;
    int action;
    if(!b || b->size!=sizeof(*b))return;
    report=*b;
    clock_interval_to_absolutetime_interval(2000,NSEC_PER_MSEC,&maximum_age);
    lck_mtx_lock(&native_battery_mutex);
    clock_get_uptime(&now);
    action=mt6762_report_receive(&native_battery_age,b->acquired_abs,b->expires_abs,
                                now,b->valid,maximum_age);
    if(action!=MT6762_REPORT_IGNORE) {
        native_battery_seen=1;
        if(action==MT6762_REPORT_CLEAR)report.valid=0;
        native_battery_sample=report;
        battery_updates++;
    }
    lck_mtx_unlock(&native_battery_mutex);
    /* A delayed older report cannot replace newer BSD or IOKit observations.
     * No BSD snapshot lock crosses into the IOKit workloop. */
    if(action!=MT6762_REPORT_IGNORE)HakiosBatteryReportPartial(&report,sizeof(report));
}

static void
battery_thread(__unused void *parameter, __unused wait_result_t result)
{
	for (unsigned tick = 0;; tick++) {
		battery_poll();
		if (tick % 12 == 0) {
			printf("battery: SOC=%d%%%s, V=%d mV, I=%d mA, T=%d C, battery=%d charger=%d charging=%d "
			    "action=%d (%llu reads, %llu failed)\n", battery_soc_percent,
			    battery_soc_estimated ? " (voltage estimate)" : "", battery_voltage_mv,
			    battery_current_ma, battery_temperature_c, battery_present, battery_charger_present,
			    battery_charging, battery_charger_action, battery_updates, battery_failures);
		}
		delay_for_interval(5000, NSEC_PER_MSEC);
	}
}

void
hakios_battery_init(void)
{
	uint32_t enabled = 0;
	uint64_t shared_pa = 0;
	vm_offset_t page;
	thread_t thread;

	if (!PE_parse_boot_argn("battery", &enabled, sizeof(enabled)) || !enabled) return;
	if (!PE_parse_boot_argn("battery_shared_pa", &shared_pa, sizeof(shared_pa)) || shared_pa == 0) {
		printf("battery: xnuloader did not provide battery_shared_pa\n");
		return;
	}
	page = ml_io_map((vm_offset_t)(shared_pa & ~(LOADER_PAGE_SIZE - 1)), LOADER_PAGE_SIZE);
	shared_battery = (volatile struct loader_battery *)(page + (shared_pa & (LOADER_PAGE_SIZE - 1)));
	if (shared_battery->magic != LOADER_BATTERY_MAGIC || shared_battery->version != LOADER_BATTERY_VERSION ||
	    shared_battery->size < sizeof(struct loader_battery)) {
		printf("battery: bad xnuloader cache at %#llx (magic %#llx version %u size %u)\n", shared_pa,
		    shared_battery->magic, shared_battery->version, shared_battery->size);
		return;
	}
	printf("battery: Qualcomm UEFI cache at pa %#llx; polling every 5 seconds\n", shared_pa);
	if (kernel_thread_start(battery_thread, NULL, &thread) == KERN_SUCCESS) thread_deallocate(thread);
}
