/* Experimental MT6762 platform. See doc/mt6762.md for provenance and limits. */
#ifndef _PEXPERT_ARM_MT6762_H
#define _PEXPERT_ARM_MT6762_H
#define MT6762 1
#define NO_MONITOR 1
#define NO_ECORE 1
#define ARM_ARCH_TIMER 1
#define GENERIC_GIC_V3_IRQ 1
#define GENERIC_PSCI_SMP 1
/* MPIDR.Aff1 distinguishes two A53 clusters. HAS_CLUSTER also enables Apple
 * implementation registers, so use a topology-only switch on this platform. */
#define ARM64_GENERIC_CLUSTERED_AFFINITY 1
#define __ARM_ARCH__ 8
#define __ARM_VMSA__ 8
#define __ARM_VFP__ 4
#define __ARM_COHERENT_CACHE__ 1
#define __ARM_DEBUG__ 7
#define __ARM64_PMAP_SUBPAGE_L1__ 1
/* A53 has no PAN, LSE, or 16K translation granule. Keep ARM_PGSHIFT=12;
 * arm_init selects 16K VM pages backed by four hardware PTEs (PAGE_RATIO=4). */
#define MT6762_VM_PAGE_SHIFT 14
#ifndef ASSEMBLER
#define MTK_UART 1
#endif
#endif
