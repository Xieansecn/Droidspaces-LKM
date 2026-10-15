// SPDX-License-Identifier: GPL-2.0-only
/*
 * Load-time probe for ksud behaviour on unresolvable symbols.
 *
 * init_ipc_ns and mq_lock exist only when the target kernel provides IPC
 * namespaces and POSIX message queues. Both references live behind a module
 * parameter that defaults to off, so loading the module never dereferences
 * them; the probe only reports whether the loader tolerates the missing
 * symbols, loads the module anyway, or refuses to load it.
 */
#define pr_fmt(fmt) "ds_symbol_probe: " fmt

#include <linux/init.h>
#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/moduleparam.h>

extern int init_ipc_ns;
extern int mq_lock;

static bool poke;
module_param(poke, bool, 0400);
MODULE_PARM_DESC(poke, "Print the probe symbol addresses; leave disabled");

static int __init ds_missing_symbol_probe_init(void)
{
	if (poke)
		pr_info("poke: init_ipc_ns=%px mq_lock=%px\n",
			&init_ipc_ns, &mq_lock);
	pr_info("loaded without touching the probe symbols\n");
	return 0;
}

static void __exit ds_missing_symbol_probe_exit(void)
{
	pr_info("unloaded\n");
}

module_init(ds_missing_symbol_probe_init);
module_exit(ds_missing_symbol_probe_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Droidspaces ksud missing-symbol handling probe");
