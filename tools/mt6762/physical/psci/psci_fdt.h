/* SPDX-License-Identifier: MIT */
#ifndef MT6762_PSCI_FDT_H
#define MT6762_PSCI_FDT_H
#include <stddef.h>
#include <stdint.h>
struct mtk_psci_topology {uint32_t count,mpidr[8],smc,observed_count;};
/* Validate the complete live FDT through the existing bounded parser, then
 * admit only this phone's observed 8-A53, 2x4 topology and PSCI 1.0/SMC binding.
 * requested must be 2, 4 or 8; boot MPIDR Aff3..0 must be 0. Output is zero on error.
 * Only RES1 bit 31/MT bit 24 may differ; U bit 30 is rejected.
 * This establishes topology, NOT firmware CPU_ON support or coherent startup.
 * Kernel 54 queries VERSION/FEATURES/AFFINITY_INFO again before every CPU_ON. */
int mtk_psci_fdt_topology(const void *blob,size_t accessible,uint64_t boot_mpidr,
    unsigned requested,struct mtk_psci_topology *out);
#endif
