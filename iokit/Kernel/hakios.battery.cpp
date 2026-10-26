/*
 * HakiosBattery: the phone's battery as iOS looks for it, an IOPMPowerSource.
 *
 * powerd finds every service of the class IOPMPowerSource (it calls the first "InternalBattery-0"),
 * listens for its kIOPMMessageBatteryStatusHasChanged and then reads its properties: whether a
 * battery is installed, CurrentCapacity and MaxCapacity (without both it gives up on the battery),
 * whether a charger is connected and charging, voltage, current, cycles, the charger's details.
 * From them it makes the power sources list (IOPSCopyPowerSourcesInfo) and posts its notifications,
 * and everything else follows from that: the status bar's battery, the lock screen's "Charging",
 * the Batteries widget, Settings > Battery.
 *
 * What the values are comes from the audio DSP's battery manager (bsd/dev/hakios.adsp.c,
 * with adsp=1, unless battmgr=0), by way of bsd/dev/hakios.battery.c, which calls
 * HakiosBatteryReport() with every reading; the first one makes the service. Nothing here asks
 * the charger anything or tells it anything.
 *
 * As on Apple's newer batteries, CurrentCapacity is the percentage that the fuel gauge shows (and
 * MaxCapacity 100); the charges in mAh are AppleRawCurrentCapacity, AppleRawMaxCapacity (what the
 * gauge has learnt a full charge to be), NominalChargeCapacity and DesignCapacity.
 */

#include <IOKit/IOLib.h>
#include <IOKit/IOWorkLoop.h>
#include <IOKit/IOTimerEventSource.h>
#include <kern/clock.h>
#include <sys/mt6762_power.h>
#include "../../tools/mt6762/hardware/power/report_expiry.h"
#include <IOKit/IOPlatformExpert.h>
#include <IOKit/pwr_mgt/IOPM.h>
#include <IOKit/pwr_mgt/IOPMPowerSource.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSDictionary.h>
#include <libkern/c++/OSNumber.h>
#include <libkern/c++/OSSymbol.h>

/* The same as struct hakios_battery_state in bsd/sys/hakios.input.h, which is not seen from here. */
struct hakios_battery_state {
	uint32_t size;
	int32_t percent_hundredths;
	int32_t voltage_uv;
	int32_t current_ua;             /* more than 0 while the battery takes charge */
	int32_t temperature_hundredths;
	int32_t present, external, status;
	int32_t charge_uah, full_uah, design_uah, cycles;
	int32_t usb_type;
	int32_t usb_voltage_uv, usb_current_ua;
};

extern "C" void HakiosBatteryReport(const void * state, unsigned size);
extern "C" void HakiosBatteryReportPartial(const void * state, unsigned size);

class HakiosBattery : public IOPMPowerSource
{
	OSDeclareDefaultStructors(HakiosBattery);

public:
	void report(const struct hakios_battery_state * b);
	void reportPartial(const struct mt6762_battery_sample * b);
	bool preparePartialExpiry(void);
	void stop(IOService *provider) APPLE_KEXT_OVERRIDE;
	void free(void) APPLE_KEXT_OVERRIDE;

private:
	void number(const char * key, long long value);
	void flag(const char * key, bool value);
	void object(const char * key, OSObject * value);
	void forget(const char * key);
	void publishPartial(const struct mt6762_battery_sample * b);
	void clearPartial(bool expired);
	void partialTimer(void);
	static void partialTimerFired(OSObject *owner, IOTimerEventSource *timer);
	IOWorkLoop * fPartialLoop = NULL;
	IOTimerEventSource * fPartialTimer = NULL;
	bool fPartialTimerAdded = false;
	struct mt6762_report_expiry fPartialExpiry = {};
	uint64_t fMaximumAge = 0;
};

OSDefineMetaClassAndStructors(HakiosBattery, IOPMPowerSource);

static HakiosBattery * battery;
/* Native and legacy publishers cannot share a service/timer by accident. */
static HakiosBattery * nativeBattery;

void
HakiosBattery::number(const char * key, long long value)
{
	const OSSymbol * symbol = OSSymbol::withCString(key);
	OSNumber * n = OSNumber::withNumber((unsigned long long) value, 32);

	if (symbol != NULL && n != NULL) {
		setPSProperty(symbol, n);
	}
	OSSafeReleaseNULL(n);
	OSSafeReleaseNULL(symbol);
}

void
HakiosBattery::flag(const char * key, bool value)
{
	const OSSymbol * symbol = OSSymbol::withCString(key);

	if (symbol != NULL) {
		setPSProperty(symbol, value ? kOSBooleanTrue : kOSBooleanFalse);
	}
	OSSafeReleaseNULL(symbol);
}

void
HakiosBattery::object(const char * key, OSObject * value)
{
	const OSSymbol * symbol = OSSymbol::withCString(key);

	if (symbol != NULL && value != NULL) {
		setPSProperty(symbol, value);
	}
	OSSafeReleaseNULL(symbol);
}

/*
 * What iOS calls the charger by (IOPSKeysPrivate.h's kIOPSFamilyCode*, iokit_family_err(sub_iokit_usb, n)),
 * from Linux's POWER_SUPPLY_USB_TYPE_*, as the DSP gives it.
 */
static unsigned
family_code(int usb_type)
{
	switch (usb_type) {
	case 1: return 0xe0004000;      /* SDP, a computer's port: kIOPSFamilyCodeUSBHost */
	case 2: return 0xe0004004;      /* DCP, a charger: kIOPSFamilyCodeUSBChargingPortDedicated */
	case 3: return 0xe0004005;      /* CDP, a computer's charging port: kIOPSFamilyCodeUSBChargingPortDownstream */
	case 5: return 0xe0004009;      /* USB-C: kIOPSFamilyCodeUSBCTypeC */
	case 6: case 7: case 8: return 0xe000400a;      /* USB Power Delivery: kIOPSFamilyCodeUSBCPD */
	default: return 0xe0004007;     /* kIOPSFamilyCodeUSBUnknown */
	}
}

void
HakiosBattery::report(const struct hakios_battery_state * b)
{
	int percent = (b->percent_hundredths + 50) / 100;
	bool charging = b->external && b->status == 1;          /* POWER_SUPPLY_STATUS_CHARGING */

	percent = percent < 0 ? 0 : percent > 100 ? 100 : percent;
	setBatteryInstalled(b->present != 0);
	setExternalConnected(b->external != 0);
	setExternalChargeCapable(b->external != 0);
	setIsCharging(charging);
	flag("FullyCharged", b->external && (b->status == 4 || percent == 100));    /* POWER_SUPPLY_STATUS_FULL */
	flag("AppleRawExternalConnected", b->external != 0);
	setCurrentCapacity((unsigned) percent);
	setMaxCapacity(100);
	setVoltage((unsigned) (b->voltage_uv / 1000));
	setAmperage(b->current_ua / 1000);
	number("InstantAmperage", b->current_ua / 1000);
	number("Temperature", b->temperature_hundredths);
	if (b->charge_uah > 0) {
		number("AppleRawCurrentCapacity", b->charge_uah / 1000);
	}
	if (b->full_uah > 0) {
		number("AppleRawMaxCapacity", b->full_uah / 1000);
		number("NominalChargeCapacity", b->full_uah / 1000);
	}
	if (b->design_uah > 0) {
		number("DesignCapacity", b->design_uah / 1000);
	}
	if (b->cycles > 0) {
		setCycleCount((unsigned) b->cycles);
	}

	if (b->external) {
		OSDictionary * adapter = OSDictionary::withCapacity(6);
		long long mv = b->usb_voltage_uv / 1000, ma = b->usb_current_ua / 1000;
		OSNumber * n;

		if (adapter != NULL) {
			if ((n = OSNumber::withNumber((unsigned long long) ((mv * ma + 500000) / 1000000), 32)) != NULL) {
				adapter->setObject(kIOPMPSAdapterDetailsWattsKey, n);
				n->release();
			}
			if ((n = OSNumber::withNumber((unsigned long long) ma, 32)) != NULL) {
				adapter->setObject(kIOPMPSAdapterDetailsAmperageKey, n);
				n->release();
			}
			if ((n = OSNumber::withNumber((unsigned long long) mv, 32)) != NULL) {
				adapter->setObject(kIOPMPSAdapterDetailsVoltage, n);
				n->release();
			}
			if ((n = OSNumber::withNumber((unsigned long long) family_code(b->usb_type), 32)) != NULL) {
				adapter->setObject(kIOPMPSAdapterDetailsFamilyKey, n);
				n->release();
			}
			adapter->setObject("IsWireless", kOSBooleanFalse);
			object(kIOPMPSAdapterDetailsKey, adapter);
			adapter->release();
		}
	} else {
		OSDictionary * none = OSDictionary::withCapacity(1);
		OSNumber * n = OSNumber::withNumber(0ULL, 32);    /* kIOPSFamilyCodeDisconnected */

		if (none != NULL && n != NULL) {
			none->setObject(kIOPMPSAdapterDetailsFamilyKey, n);
			object(kIOPMPSAdapterDetailsKey, none);
		}
		OSSafeReleaseNULL(n);
		OSSafeReleaseNULL(none);
	}
	updateStatus();
}

/* With every reading of the battery (bsd/dev/hakios.battery.c); the first one makes the service. One caller at a time. */
void
HakiosBatteryReport(const void * state, unsigned size)
{
	const struct hakios_battery_state * b = (const struct hakios_battery_state *) state;
	IOService * platform;

	if (size != sizeof(struct hakios_battery_state) || b->size != sizeof(struct hakios_battery_state)) {
		static bool said;

		if (!said) {
			said = true;
			IOLog("HakiosBattery: the battery's state is %u bytes, not %lu: bsd/sys/hakios.input.h and this file disagree\n",
			    size, sizeof(struct hakios_battery_state));
		}
		return;
	}
	if (battery == NULL) {
		HakiosBattery * made = OSTypeAlloc(HakiosBattery);

		if ((platform = IOService::getPlatform()) == NULL || made == NULL || !made->init()) {
			OSSafeReleaseNULL(made);
			return;
		}
		made->report(b);        /* (the properties are there before anybody finds the service) */
		if (!made->attach(platform)) {
			made->release();
			return;
		}
		made->setName("HakiosBattery");
		if (!made->start(platform)) {
			made->detach(platform);
			made->release();
			return;
		}
		made->registerService();
		battery = made;
		IOLog("HakiosBattery: the battery's power source is up: %d%%, %s\n", (b->percent_hundredths + 50) / 100,
		    b->external ? (b->status == 1 ? "charging" : "on a charger, not charging") : "not on a charger");
		return;
	}
	battery->report(b);
}

/* updateStatus copies present properties; it does not remove absent ones. */
void
HakiosBattery::forget(const char * key)
{
	if (properties->getObject(key) != NULL || getProperty(key) != NULL) {
		properties->removeObject(key);
		removeProperty(key);
		settingsChangedSinceUpdate = true;
	}
}

void
HakiosBattery::publishPartial(const struct mt6762_battery_sample * b)
{
	const uint32_t v = b->valid;
	if (v & MT6762_BAT_PRESENT) setBatteryInstalled(b->present != 0);
	else forget(kIOPMPSBatteryInstalledKey);
	if (v & MT6762_BAT_EXTERNAL) {
		setExternalConnected(b->external != 0);
		flag("AppleRawExternalConnected", b->external != 0);
	} else {
		forget(kIOPMPSExternalConnectedKey);
		forget("AppleRawExternalConnected");
	}
	if ((v & (MT6762_BAT_STATUS | MT6762_BAT_EXTERNAL)) ==
	    (MT6762_BAT_STATUS | MT6762_BAT_EXTERNAL)) {
		setIsCharging(b->external && b->status == 1);
		flag("FullyCharged", b->external && b->status == 4);
	} else {
		forget(kIOPMPSIsChargingKey);
		forget("FullyCharged");
	}
	if ((v & MT6762_BAT_SOC) && b->percent_hundredths >= 0 && b->percent_hundredths <= 10000) {
		setCurrentCapacity((unsigned)(b->percent_hundredths + 50) / 100);
		setMaxCapacity(100);
	} else {
		forget(kIOPMPSCurrentCapacityKey);
		forget(kIOPMPSMaxCapacityKey);
	}
	if (v & MT6762_BAT_VOLTAGE) setVoltage((unsigned)(b->voltage_uv / 1000));
	else forget(kIOPMPSVoltageKey);
	if (v & MT6762_BAT_CURRENT) {
		setAmperage(b->current_ua / 1000);
		number("InstantAmperage", b->current_ua / 1000);
	} else {
		forget(kIOPMPSAmperageKey);
		forget("InstantAmperage");
	}
	if (v & MT6762_BAT_TEMP) number("Temperature", b->temperature_hundredths);
	else forget("Temperature");
	/* No capacity, charge capability, adapter budget or calibration is inferred
	 * from voltage/presence. These fields are outside the partial contract. */
	const char * unknown[] = { kIOPMPSExternalChargeCapableKey, kIOPMPSAdapterDetailsKey,
	    "AppleRawCurrentCapacity", "AppleRawMaxCapacity", "NominalChargeCapacity",
	    kIOPMPSDesignCapacityKey, kIOPMPSCycleCountKey, kIOPMPSTimeRemainingKey };
	for (unsigned i = 0; i < sizeof(unknown) / sizeof(unknown[0]); i++) forget(unknown[i]);
	number("MT6762ValidFields", v);
	updateStatus();
}

bool
HakiosBattery::preparePartialExpiry(void)
{
	if (fPartialLoop) return false;
	nanoseconds_to_absolutetime(2 * NSEC_PER_SEC, &fMaximumAge);
	fPartialLoop = IOWorkLoop::workLoop();
	fPartialTimer = IOTimerEventSource::timerEventSource(this, &HakiosBattery::partialTimerFired);
	if (!fMaximumAge || !fPartialLoop || !fPartialTimer ||
	    fPartialLoop->addEventSource(fPartialTimer) != kIOReturnSuccess) return false;
	fPartialTimerAdded = true;
	return true;
}

/* All partial property changes, including invalidation, run under this same
 * workloop gate. Never hold a BSD snapshot mutex while entering this gate. */
void
HakiosBattery::reportPartial(const struct mt6762_battery_sample * b)
{
	if (!fPartialLoop || !b) return;
	fPartialLoop->runActionBlock(^IOReturn (void) {
		uint64_t now = mach_absolute_time();
		bool oldReportExpiredCurrent = fPartialExpiry.seen &&
		    b->acquired_abs <= fPartialExpiry.last_acquired &&
		    fPartialExpiry.active && now >= fPartialExpiry.expires;
		int action = mt6762_report_receive(&fPartialExpiry, b->acquired_abs,
		    b->expires_abs, now, b->valid, fMaximumAge);
		if (action == MT6762_REPORT_IGNORE) return kIOReturnSuccess;
		fPartialTimer->cancelTimeout();
		if (action == MT6762_REPORT_APPLY) {
			/* Arm before publishing, so allocation/notification work cannot
			 * postpone when the observation is eligible for invalidation. */
			if (fPartialTimer->wakeAtTime(fPartialExpiry.expires) == kIOReturnSuccess) {
				flag("MT6762ReportExpired", false);
				publishPartial(b);
				return kIOReturnSuccess;
			}
			fPartialExpiry.active = 0;
			clearPartial(true);
			return kIOReturnError;
		}
		clearPartial(oldReportExpiredCurrent ||
		    !mt6762_report_fresh(b->acquired_abs, b->expires_abs, now, fMaximumAge));
		return kIOReturnSuccess;
	});
}

void
HakiosBattery::clearPartial(bool expired)
{
	struct mt6762_battery_sample unavailable = {};
	unavailable.size = sizeof(unavailable);
	flag("MT6762ReportExpired", expired);
	/* Removal is explicit: updateStatus alone only copies present keys. */
	publishPartial(&unavailable);
}

void
HakiosBattery::partialTimer(void)
{
	if (fPartialExpiry.stopped) return;
	if (mt6762_report_expire(&fPartialExpiry, mach_absolute_time()) == MT6762_REPORT_CLEAR) {
		clearPartial(true);
	} else if (fPartialExpiry.active &&
	    fPartialTimer->wakeAtTime(fPartialExpiry.expires) != kIOReturnSuccess) {
		fPartialExpiry.active = 0;
		clearPartial(true);
	}
}

void
HakiosBattery::partialTimerFired(OSObject *owner, IOTimerEventSource *timer)
{
	(void)timer;
	HakiosBattery *source = OSDynamicCast(HakiosBattery, owner);
	if (source) source->partialTimer();
}

void
HakiosBattery::stop(IOService *provider)
{
	if (fPartialLoop) fPartialLoop->runActionBlock(^IOReturn (void) {
		mt6762_report_stop(&fPartialExpiry);
		if (fPartialTimer) fPartialTimer->cancelTimeout();
		clearPartial(true);
		return kIOReturnSuccess;
	});
	IOPMPowerSource::stop(provider);
}

void
HakiosBattery::free(void)
{
	/* Gate acquisition drains any running timer/report before removal. Initial
	 * attach/start failures use this path too, before nativeBattery is set. */
	if (fPartialLoop) fPartialLoop->runActionBlock(^IOReturn (void) {
		mt6762_report_stop(&fPartialExpiry);
		if (fPartialTimer) fPartialTimer->cancelTimeout();
		return kIOReturnSuccess;
	});
	if (fPartialTimerAdded && fPartialLoop) fPartialLoop->removeEventSource(fPartialTimer);
	OSSafeReleaseNULL(fPartialTimer);
	OSSafeReleaseNULL(fPartialLoop);
	IOPMPowerSource::free();
}

/* One native worker owns this entry point. Missing capacity intentionally
 * leaves the iOS percentage unavailable until a calibrated fuel gauge exists. */
void
HakiosBatteryReportPartial(const void * state, unsigned size)
{
	const struct mt6762_battery_sample * b = (const struct mt6762_battery_sample *)state;
	if (!b || size != sizeof(*b) || b->size != sizeof(*b)) return;
	if (nativeBattery == NULL) {
		if (!b->valid) return;
		IOService * platform = IOService::getPlatform();
		HakiosBattery * made = OSTypeAlloc(HakiosBattery);
		if (platform == NULL || made == NULL || !made->init() || !made->preparePartialExpiry()) {
			OSSafeReleaseNULL(made);
			return;
		}
		made->reportPartial(b);
		if (!made->attach(platform)) { made->release(); return; }
		made->setName("MT6762Battery");
		if (!made->start(platform)) {
			made->detach(platform);
			made->release();
			return;
		}
		made->registerService();
		nativeBattery = made;
		IOLog("MT6762Battery: partial observation service registered with acquisition expiry\n");
		return;
	}
	nativeBattery->reportPartial(b);
}
