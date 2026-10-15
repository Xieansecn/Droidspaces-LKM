# port61-nomq 移植评估

给 6.1 模块补上**自持的 IPC namespace 与 POSIX mqueue 后端**，让它在
`CONFIG_SYSVIPC=n`、`CONFIG_POSIX_MQUEUE=n`（因此 `CONFIG_IPC_NS` 不提供）的厂商
内核上也能加载。项目定义见 [build/port61-nomq.json](../build/port61-nomq.json)，
目标设备档案见
[build/device-profiles/6.1.138-android14-11.json](../build/device-profiles/6.1.138-android14-11.json)，
代码脚手架在 [src/port61nomq/](../src/port61nomq/ORIGIN)。

## 结论摘要

| 项目 | 评估 |
| --- | --- |
| 可行性 | 高。不是新设计，而是把仓库里已经存在四份的「自持后端」移植回来 |
| 规模 | 新增约 1,890 行（`mqueue.c` + `mq_sysctl.c`）+ 约 300 行适配 |
| 最近模板 | 后端取 `src/port515`（5.15，其 VFS/sysctl 调用形式 6.1 仍在用），`src/port66`（6.6）作为交叉参照 |
| 主要风险 | `mqueue.c` 的 5.15→6.1 API 适配；测试内核能否代表设备（DDK 内核自带原生 mqueue） |
| 不改动 | 不启用 `CONFIG_SYSVIPC`，因此不动 `task_struct`/kABI，这是本路线相对「重刷内核」的核心优势 |
| 不在本次范围 | devtmpfs（`CONFIG_DEVTMPFS=n`）与 user namespace 沙箱（`CONFIG_USER_NS=n`），另立 M4 |

## 1. 目标设备与失败原因

设备：`6.1.138-android14-11-g0c3d559bcd85-ab14529422`（KMI `android14-6.1`，
Xiaomi 厂商内核，clang 17.0.2 r487747c 构建）。内核**有** `CONFIG_NAMESPACES`、
`CONFIG_UTS_NS`、`CONFIG_NET_NS`、`CONFIG_KALLSYMS_ALL`、`CONFIG_MODVERSIONS`、
`CONFIG_DEBUG_INFO_BTF`、`CONFIG_CFI_CLANG`、`CONFIG_SHADOW_CALL_STACK`；
**没有** `CONFIG_SYSVIPC`、`CONFIG_POSIX_MQUEUE`、`CONFIG_PID_NS`、
`CONFIG_USER_NS`、`CONFIG_DEVTMPFS`、`CONFIG_CGROUP_PIDS`、`CONFIG_CGROUP_DEVICE`。
`CONFIG_IPC_NS` 因依赖不满足而根本不出现在配置里，`/proc/self/ns/` 只有
cgroup/mnt/net/time/uts。

现成产物 `droidspaces_ns-android14-6.1-gki.ko`（`src/port61`，DDK
`android14-6.1-20260313`）在这台机器上的实测结果：

```text
ksud insmod droidspaces_ns-android14-6.1-gki.ko gki=1 activate=1   # exit 1
droidspaces_ns: Unknown symbol mq_init_ns (err -2)
droidspaces_ns: Unknown symbol setup_mq_sysctls (err -2)
droidspaces_ns: Unknown symbol retire_mq_sysctls (err -2)
droidspaces_ns: Unknown symbol mq_clear_sbinfo (err -2)
droidspaces_ns: Unknown symbol mq_lock (err -2)
droidspaces_ns: Unknown symbol init_ipc_ns (err -2)
droidspaces_ns: Unknown symbol mq_put_mnt (err -2)
```

`/sys/module/droidspaces_ns` 不存在、无 oops、无持久化改动。用「只引用不存在
符号、引用路径永不执行」的探针证明：ksud 不会把无法解析的符号清零强载，失败发生
在内核 `simplify_symbols()` 阶段，模块代码一行都不会执行
（[tests/probe/missing-symbol-probe.c](../tests/probe/missing-symbol-probe.c)）。

## 2. 为什么自持后端可行

1. **`struct nsproxy` 的字段与配置无关。** 设备 BTF 实测：72 字节，
   `uts_ns@8`、`ipc_ns@16`、`mnt_ns@24`、`pid_ns_for_children@32`、`net_ns@40`、
   `time_ns@48`、`time_ns_for_children@56`、`cgroup_ns@64`。即使 `CONFIG_IPC_NS=n`，
   模块仍可把自己的 IPC namespace 指针发布到这个字段。
2. **没有已编译的内核代码会碰 `nsproxy->ipc_ns`。** `copy_ipcs()`、`free_ipc_ns()`、
   `ipcns_*` 都不存在，因此模块可以完全拥有该对象的布局与生命周期（PID 侧已经是
   这个模式：设备缺 `create_pid_namespace`/`pidns_operations`/`get_pid_ns`，
   模块自己提供）。
3. **IPC 系统调用只剩 ENOSYS 弱别名，`sys_call_table` 可写。**
   设备 kallsyms 中 `__arm64_sys_mq_open`、`__arm64_sys_msgget`、
   `__arm64_sys_semget`、`__arm64_sys_shmget` 都是 `W`（weak，指向
   `__arm64_sys_ni_syscall`），`sys_call_table` 是 `D`。模块安装自己的处理函数即可。
4. **`struct ipc_namespace` 的 6.1 完整布局就在设备 BTF 里**（1272 字节，
   `mq_mnt@984`、`mq_set@1016`、`mq_sysctls@1112`、`ipc_set@1120`、
   `ipc_sysctls@1216`、`ns@1248`），可以直接和 DDK 头文件做离线 ABI 对比，不必靠猜。
5. **后端代码仓库里已经有四份。** `src/port515`、`src/port66`、`src/port`(6.12)、
   `src/port618` 都自行定义 `DEFINE_SPINLOCK(mq_lock)`、
   `struct ipc_namespace init_ipc_ns`、自己的 `copy_ipcs`/`free_ipc_ns`/
   `ipcns_operations`，并各自带 `mqueue.c` 与 `mq_sysctl.c`。只有
   `src/port61` 改成了复用原生对象——这正是它在厂商内核上加载失败的原因。

## 3. 工作量：与参考端口的实际差距

所有自持端口的文件集合都比 `src/port61` 多 `mqueue.c`、`mq_sysctl.c` 两个文件，
其余同名文件的差异行数（`diff` 行计数，含上下文；左列对比 `src/port66`，右列对比
`src/port515`）：

| 文件 | p61 vs p66 | p61 vs p515 | 说明 |
| --- | --- | --- | --- |
| ipc.c | 101 | 56 | 自持 `init_ipc_ns`/`mq_lock`/`copy_ipcs`/`free_ipc_ns`/`ipcns_operations` |
| ipc-task.c | 66 | 67 | 自持 init namespace 路径，去掉 `ds_ipc_ensure` 机器 |
| ipc_sysctl.c | 17 | 243 | 注册自己的 ipc/mqueue sysctl 树；5.15 用老的 `register_sysctl_table` 风格 |
| exit.c / hooks.c / nsproxy.c / main.c | 14 / 38 / 44 / 7 | 154 / 79 / 0 / 7 | 生命周期与挂钩；**nsproxy.c 的 44 行是 6.6 专属改动，不可回移**（p61 与 p515 完全一致） |
| ipc-util.c/h、ipc-backend.h、names.h、fork.c、pid.c、sem.c、shm.c | 各 4–12 | 各 4–65 | 小幅适配 |
| msg.c、proc_ns.c、selftest.c | 0 | 50 / 0 / 0 | `msg.c` 已是 6.x 形式，必须保留 p61 版本 |
| mqueue.c / mq_sysctl.c | 新增 | 新增 | 1,768 + 121 行（取 p515 文本） |

关键判据：`src/port66/names.h` 相对 `src/port61/names.h` **只多两行**
（`init_ipc_ns → ds_init_ipc_ns`、`mq_lock → ds_mq_lock`），`hooks.c` 则从「包装
原生 `copy_ipcs`/`put_ipc_ns`/`ipcns_put`/`ipcns_install`」变成「自己拥有这些
入口」并新增六个 mq 系统调用槽位。也就是说这次移植的主体是**把已有的自持后端搬
回来**，不是重新设计 IPC。

模板为什么选 5.15 而不是 6.6：`mqueue.c` 需要能在 6.1 上编译并只引用设备存在的
符号，而 6.6 文本用到 `mnt_idmap`、`nop_mnt_idmap`、`alloc_inode_sb`、
`mnt_make_shortterm`（6.3–6.8 引入），设备 kallsyms 里全部缺失；5.15 文本用的
`current_time()`、`kern_unmount()`、`mnt_userns`、`register_sysctl_table()`/
`__register_sysctl_table()` 在设备上全部存在（见第 3.1 节实测）。

完整文件级清单、里程碑与验收门禁见
[build/port61-nomq.json](../build/port61-nomq.json)（`change_list`、`milestones`、
`gates`、`open_decisions`）。

### 3.1 符号证据（CI 实测）

用 [build-port61-nomq.yml](../.github/workflows/build-port61-nomq.yml) 的
`mode=reference` 在各自 DDK 里真实构建三份自持后端，把模块的未定义符号与设备
kallsyms 对照：

| 模板端口 | 导入符号 | 命中设备缺失的 IPC 阻塞符号 | 其余设备缺失符号 |
| --- | --- | --- | --- |
| `src/port515`（5.15） | 402 | **0** | 10 个，全部是该代际特有（`PDE_DATA`、`__find_vma`、`sysctl_vals_new` 等） |
| `src/port66`（6.6） | 410 | **0** | 10 个，全部是该代际特有（`mnt_make_shortterm`、`__percpu_counter_init_many`、`register_sysctl_sz` 等） |
| `src/port`（6.12） | 418 | **0** | 29 个，全部是该代际特有 |

两点结论：自持设计本身**不依赖**设备缺失的任何 IPC/mqueue 对象；剩余差异都是内核
代际差异，会随「在 6.1 DDK 下编译」自然收敛。差异里已经能看到具体适配点，例如
`src/port66/ipc.c:195` 的 `mnt_make_shortterm()`（6.8 API，设备缺失）。

### 3.2 5.15→6.1 的关键差异（上游源码核对 + 设备实测）

对上游 v5.15 与 v6.1 的 `ipc/`、`kernel/pid*.c`、`kernel/nsproxy.c`、`fs/proc/` 逐项
比对后，真正影响本次移植的只有下面几条，其余（`struct pid_namespace`、`struct pid`、
`nsproxy.c`、`ns_common.h`、`ipc/Makefile`、`struct ctl_table`）在两个版本间**逐字节
相同**：

| 差异 | 6.1 要求 | 本次处理 |
| --- | --- | --- |
| `msg_init_ns()` | `void` → **`int`**（要处理 percpu 计数初始化失败） | `src/port61/msg.c:1307` 已是 `int` 形式，保留 port61 版本 |
| `struct ipc_namespace` 计数 | `atomic_t msg_bytes/msg_hdrs` → `percpu_counter`；新增 `mq_set/mq_sysctls/ipc_set/ipc_sysctls` | 模块直接用 6.1 头文件里的结构；设备 BTF 实测 1272 字节、各字段偏移与模块 DWARF 一致 |
| mqueue 挂载 | `struct mqueue_fs_context` 新增 `bool newns`，`get_tree_nodev()` 用于新建 namespace | port515 文本里已经带 `newns` 逻辑（`mqueue.c:49/436/485`），无需自造 |
| inode 分配 | 上游 6.1 用 `alloc_inode_sb()` | **设备无此符号**，且 6.1 DDK 头文件会把 `kmem_cache_alloc()` 内联成设备存在的 `kmem_cache_alloc`，因此保留 5.15 形式 |
| `kern_mount/kern_unmount` | 两版本都存在且导出；6.1 只把声明挪到 `<linux/mount.h>` | 视为「需补 include」的编译期小事 |
| sysctl | `register_sysctl_table()`（全局表）与 `__register_sysctl_table()`/`setup_sysctl_set()`（按 namespace）在设备上**都存在** | 两种风格都可行，M1 再定（见 `open_decisions`） |
| 非导出符号 | `__register_sysctl_table`、`proc_alloc_inum`、`setup_sysctl_set` 等都没有 `EXPORT_SYMBOL` | **不构成本项目的约束**：ksud/kallrecon 按 kallsyms 名字重定位，已建成的 6.1 模块正是这样导入它们的 |
| `CLONE_NEWIPC/NEWPID` | 配置关闭时 `copy_ipcs()`/`copy_pid_ns()` 被编译成返回 `-EINVAL` 的 inline 存根；`exit_sem/exit_shm/exit_task_namespaces` 同样是空存根 | 本项目本来就不依赖内核调用模块，而是由 `hooks.c` 挂钩 `copy_namespaces`/`unshare_nsproxy_namespaces`/`do_exit` 等**调用者** |
| `sys_call_table` | `const` 且未导出 | 模块自带地址发现与写保护绕过（`hooks.c` 里以两个 32 位半字写入，`stop_machine` 保护） |
| 6.1 GKI 自带 mqueue | `register_filesystem("mqueue")` 在 `POSIX_MQUEUE=y` 的内核上会返回 `-EBUSY` | 必须在 init 里降级而不是失败；M2 的测试内核要从配置上关掉 `POSIX_MQUEUE`，否则测不出真正的目标场景 |

### 3.3 需要一并纳入门禁的「诱人但设备没有」的符号

自持后端容易顺手用上、但设备 kallsyms 里并不存在的符号（已逐个核对，已加入
[scripts/port61-nomq-gate.py](../scripts/port61-nomq-gate.py) 的拒绝清单）：
`alloc_inode_sb`、`kmem_cache_alloc_trace`、`__kmalloc_track_caller`、`mnt_idmap`、
`nop_mnt_idmap`、`mnt_make_shortterm`、`register_sysctl_sz`、
`__percpu_counter_init_many`、`percpu_counter_destroy_many`、`PDE_DATA`。




## 4. 外部检索：先例、主流做法与本仓库路线的取舍

### 4.1 同类先例（都是 LKM 路线，不是新发明）

| 项目 | 做法 | 对本项目的价值 |
| --- | --- | --- |
| [`cyanmint/lkm4ctr`](https://github.com/cyanmint/lkm4ctr) | 单个 arm64 GKI 模块把 namespace + SysV IPC + POSIX mqueue + overlayfs 全部 vendor 进来并挂钩系统调用；**其 `ipc/` 源码取自 ACK `android14-6.1`（6.1.124）**，也就是本项目的同一条 6.1→LKM 路线 | 最直接的对照实现；[`docs/en/developer/VENDOR_KERNEL.md`](https://github.com/cyanmint/lkm4ctr/blob/master/docs/en/developer/VENDOR_KERNEL.md) 是检索到的最密集的踩坑文档 |
| [`Dere3046/_patchHarmony`](https://github.com/Dere3046/_patchHarmony)（droid_lkm） | 三个模块给出 pid/ipc namespace（含 clone/clone3/setns 的 `CLONE_NEWPID/NEWIPC`）、SysV IPC、POSIX mqueue、`/proc/<pid>/ns/*`、`NSpid` 等，明确声明「不移动任何一个结构体成员，prebuilt 厂商模块继续可用」 | 与本项目目标一致；Droidspaces 维护者在 [issue #354](https://github.com/ravindu644/Droidspaces-OSS/issues/354) 里称其「approach works without any issues，需求检查全绿、容器能起」 |
| [`Dere3046/KallRecon`](https://github.com/Dere3046/KallRecon) | 从内核镜像内存重建 kallsyms 表以在 LKM 内拿到符号地址 | 本仓库 `vendor/kallrecon` 已内置，且真机探针已验证可用 |
| 官方/社区的另一条路：[`Goldzxcbug/Droidspaces_Kernel_patch`](https://github.com/Goldzxcbug/Droidspaces_Kernel_patch) | 按 KMI 发布 kABI padding 补丁（`GKI/6.1/GKI-6.1-sysvipc_kabi_6_7_8.patch` 等），改内核后重刷；槽位需按机型试 `1_2_3`/`3_4_5`/`5_6_7`，否则 bootloop | 与本项目互斥的备选方案，本项目选它不选的原因见 4.2 |

Droidspaces 官方对 LKM 的态度也变了：[issue #97](https://github.com/ravindu644/Droidspaces-OSS/issues/97)（2026-05）里维护者称「技术上不可能，模块补不了这些基础数据结构」，五个月后的 #354 则给出可用的模块先例；但**至今没有官方 opt-in 去识别模块提供的 namespace**，这属于产品侧风险。

### 4.2 与本项目路线的取舍

Droidspaces 官方文档（[Kernel-Configuration.md](https://github.com/ravindu644/Droidspaces-OSS/blob/main/Documentation/Kernel-Configuration.md)）
列出容器所需的全部选项，并明确写下 GKI 上的结论：`CONFIG_SYSVIPC`、
`CONFIG_IPC_NS`、`CONFIG_POSIX_MQUEUE` **会给核心结构加字段、移动 ABI**，直接打开会让
厂商 prebuilt 模块拒绝加载、设备 bootloop；因此官方做法是给内核打 kABI padding 补丁
后重新编译并刷写内核。同一文档还强调「不要为了绕过校验而关闭 `CONFIG_MODVERSIONS`
或强载模块；结构确实变了」，以及 `CONFIG_CFS_BANDWIDTH`/`CONFIG_CGROUP_PIDS` 会改变
调度器与 cgroup 结构、没有 padding 覆盖。

| 需求 | 官方路线（改内核重刷） | 本仓库 LKM 路线 |
| --- | --- | --- |
| PID / IPC namespace | 打开 `CONFIG_PID_NS`、`CONFIG_IPC_NS`（需 kABI 补丁） | 模块提供（PID 已具备，IPC 为本次项目） |
| POSIX mqueue / SysV IPC | 打开 `CONFIG_POSIX_MQUEUE`、`CONFIG_SYSVIPC`（需 kABI 补丁） | 模块提供后端，**不打开 `CONFIG_SYSVIPC`，因此不动 `task_struct`/kABI** |
| devtmpfs | 打开 `CONFIG_DEVTMPFS` | 需要单独的 devtmpfs 移植（M4） |
| user namespace 沙箱 | 打开 `CONFIG_USER_NS` | 需要单独的 userns 移植（M4） |
| `--cpus` / `--pids-limit` | 需 `CONFIG_CFS_BANDWIDTH`/`CONFIG_CGROUP_PIDS`，官方也标注为破坏 ABI、默认不推荐 | 本设备两者皆无，本次不覆盖，属于已知功能缺失 |

### 4.3 社区经验中真正影响本次移植的几条

- **ksud 的加载机制**：它把模块里每一个 `SHN_UNDEF` 符号改写成 `SHN_ABS` 并填入
  `/proc/kallsyms` 里的地址（期间临时放宽 `kptr_restrict`），失败后再按内核报的
  `version magic` 改写 `.modinfo` 并重试。因为内核 `simplify_symbols()` 对
  `SHN_ABS` 直接跳过，**逐符号的 `CONFIG_MODVERSIONS` CRC 校验实际上被绕过**，真正的
  门槛变成「名字在 `/proc/kallsyms` 里存在」；但 `check_modstruct_version()` 与
  vermagic 仍然生效。这解释了 8 个缺失符号为何是硬失败，也解释了本项目为何能使用
  非导出符号。
- **slab 缓存归属**：模块自建的 `pid_namespace`/`uts_namespace`/`user_namespace`
  必须用模块自己的 `kmem_cache` 分配与释放；而 `nsproxy` 是 `obj-y`，真实
  `free_nsproxy()` 永远存在，混用会在别的路径上触发 SLUB 「wrong slab cache」。
  本仓库既有端口已经这么做了（见 4.4）。
- **`CONFIG_PID_NS=n` 的 `BUG()`**：`zap_pid_ns_processes()` 在关闭时被编译成内联
  `BUG()`，而 `kernel/exit.c` 在该 namespace 的 `child_reaper` 退出时会调用它。
- **CFI 要按对象处理**：设备是 KCFI（见 6.2 节实测）。若把「内核会回调进模块」的函数
  （kprobe handler、`proc_ns_operations`、`file_system_type.init_fs_context`、
  `file_operations`、`work_struct` 回调）的 CFI 关掉，内核侧检查会失败并 panic
  （社区实测 `CFI failure at alloc_fs_context (target: mqueue_init_fs_context)`、
  `… at process_one_work (target: free_ipc)`）；反之只有「调用运行时解析指针」的目标
  文件才应关 CFI。
- **`/dev/mqueue`**：必须用真实名字 `"mqueue"` 注册文件系统（否则 runc/containerd 的
  `mount -t mqueue` 找不到），`register_filesystem()` 返回 `-EBUSY` 时要降级而不是
  失败；模块是开机后 `post-fs-data` 阶段才加载的，`/dev/mqueue` 需要模块自己挂载。
- **不要往 `task_struct` 加状态**：`sysvsem`/`sysvshm` 在 `SYSVIPC=n` 上不存在，模块用
  自己的按 task 侧表；本仓库 `docs/port-status.md` 也是同一纪律。

### 4.4 这些风险在既有端口中是否已解决（已核对代码）

`src/port61` 与其它自持端口共享的那套机制已经覆盖了社区报告的主要坑：

| 坑 | 既有端口里的处理 |
| --- | --- |
| `PID_NS=n` 的 `zap_pid_ns_processes()` 内联 `BUG()` | `names.h:8` 把 `zap_pid_ns_processes` 改名为 `ds_zap_pid_ns_processes`，`pid.c:173` 给出实现，`hooks.c:166` 挂钩 `do_exit` |
| `free_nsproxy()` 永远存在、缓存归属 | `hooks.c:170` 挂钩 `free_nsproxy`（`names.h:17`），nsproxy 沿用内核 `nsproxy_cachep`；`pid.c:481` 为 pid namespace 自建 `ds_pid_namespace` 缓存 |
| 文本改写与 ftrace/`text_poke` 缺失 | 设备没有 `text_poke`/`register_ftrace_function`，模块也不用：只导入 `set_memory_rw` 并自行改写 `sys_call_table` |
| 设备侧符号可用性 | 13 个 path/fs_context 符号、19 个 mqueue VFS 符号、`kern_mount/kern_unmount`、`register_filesystem` 全部存在（`CONFIG_TRIM_UNUSED_KSYMS` 那类缺失在本设备**不适用**） |
| mqueue 相关 | **未继承**：`"mqueue"` 真实名注册、`-EBUSY` 降级、主动挂载 `/dev/mqueue` 是本项目 M1/M3 的新增项 |


## 5. 验证计划（按里程碑）

- **M1 自持后端**：CI 用 6.1 DDK 构建 `src/port61nomq`；门禁脚本
  [scripts/port61-nomq-gate.py](../scripts/port61-nomq-gate.py) 读取设备档案，
  要求模块既不导入任何「设备缺失符号」，又确实定义了 `ds_init_ipc_ns`、
  `ds_mq_lock`、`ds_copy_ipcs`、`ds_ipcns_operations`；再对
  nsproxy/ipc_namespace/pid_namespace/pid 做 BTF 布局比对。
- **M2 有代表性的测试内核**：DDK 内核自带原生 IPC/mqueue，在它上面跑 VM 回归
  不能证明「没有原生对象时也工作」。需要用 ACK `android14-6.1` 编一个
  `SYSVIPC=n`、`POSIX_MQUEUE=n`、`PID_NS=n`、`USER_NS=n`、`DEVTMPFS=n` 的测试
  内核，再跑仓库既有的 `tests/vm` 回归。
- **M3 真机**：`ksud insmod` 无 oops、PID/IPC namespace 真实可建（ns id 不同、
  可嵌套）、Droidspaces 能起来一个容器、激活后拒绝热卸载且设备稳定。
- **M4 devtmpfs 与沙箱**：另立工作流（`CONFIG_DEVTMPFS=n`、`CONFIG_USER_NS=n`）。

### M0 实测（`mode=target`，run 38723856630）

把 `src/port61` 与 `src/port515` 的 `mqueue.c`/`mq_sysctl.c` 直接放进 6.1 DDK 编译，
结果只有一处编译错误，且正是 3.2 节预测的差异：

```text
src/port61nomq/mqueue.c:1735: error: call to undeclared function 'mq_register_sysctl_table'
note: did you mean '__register_sysctl_table'?   (include/linux/sysctl.h:221)
```

也就是说自持后端在 6.1 上的适配起点很窄：先按 6.1 的 sysctl 注册方式重写这一处
（`mq_register_sysctl_table()` 在 6.1 已被 `setup_mq_sysctls()`/`__register_sysctl_table()`
取代），再处理符号门禁列出的阻塞项。门禁与构建日志都随该 run 的 artifact 保留。

### M1 完成 + 真机验证（2026-10-15）

M1 的实际改动比预估更小：`src/port61nomq` 只改了 9 个文件、新增 2 个
（`names.h` 增加 5 个自持符号改名；`ipc.c` 自己定义 `init_ipc_ns`/`mq_lock` 并拥有
`copy_ipcs`/`free_ipc_ns`/`ipcns_operations`；`ipc-task.c` 去掉 `ds_ipc_ensure` 机器、
改由 `ds_mqueue_init/exit` 起停队列后端；`hooks.c` 去掉 4 个原生 IPC 命名空间挂钩、
新增 6 个 mq 系统调用槽位并把守护包装改为直接替换；`main.c` 门禁改为要求原生 IPC
命名空间缺失；`mqueue.c` 补一处 6.1 已删除的声明）。CI 一次通过：

```text
run 38737237821  imports=409 defined=476 blocking_list=36
gate: pass - the module neither imports a blocking symbol nor misses a backend symbol
```

409 个导入符号在本机 kallsyms 中**全部存在**。随后在 6.1.138 真机上：

| 步骤 | 结果 |
| --- | --- |
| `ksud insmod …`（不带 `gki=1`） | 模块自身门禁拒绝，`-EOPNOTSUPP`，未加载（设计如此） |
| `ksud insmod … gki=1` | **加载成功**，自检全过：`entry preflight passed: 19 functions, 19 syscalls, 6 BPF callbacks`、`PID/IPC … checks passed` |
| 未激活时卸载 | `rmmod` 干净退出 |
| `ksud insmod … gki=1 activate=1` | `activate=Y`，`experimental namespace hooks active; module stays pinned until reboot` |
| `/proc/self/ns/` | 出现 `ipc`、`pid`、`pid_for_children`（此前只有 cgroup/mnt/net/time/uts） |
| `unshare -i` | `ipc:[4026535514]`，与初始 `ipc:[4026531839]` 不同 |
| `unshare -p -f` | 内部 PID = **1**，新的 pid namespace |
| 嵌套 `unshare -p -f unshare -p -f` | 内部 PID = 1，再次得到新 id `[4026535515]` |
| `unshare -i -p -f` | 同时创建 IPC + PID namespace 正常 |
| `mount -t mqueue none /dev/mqueue-ds`（在新 IPC 命名空间内） | **挂载成功**，自持 POSIX mqueue 后端可用 |
| `/proc/sysvipc/{msg,sem,shm}`、`/proc/sys/fs/mqueue/*`、`/proc/sys/kernel/msgmax` | 加载后出现 |

运行中的模块 sha256 为 `1f70603e…cff2d`，与 CI artifact 一致。注意事项：激活后的
模块**在重启前无法热卸载**（模块自身设计），且没有持久化（`/data/adb/modules` 无条目），
重启即恢复出厂行为。仍未完成的是：真正的 Droidspaces 容器启动（本机未安装配套
runtime）、该画像的载荷选择与 KernelSU 打包。



## 6. 风险与未决问题

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 5.15→6.1 API 适配 | `mqueue.c`/`mq_sysctl.c` 取自 5.15；M0 实测只到 `mq_register_sysctl_table()`（6.1 已删除）就编译失败，后面还可能有 `ctl_table`/挂载/percpu 计数的差异；6.6 侧则确认 `mnt_make_shortterm()`（6.8 API）不可用 | M1 的编译循环 + 以 `mode=reference` 的三份导入符号表为基线；第 3.2 节差异表为起点 |
| 符号重名 | 模块自持的 `mq_init_ns`/`mq_clear_sbinfo`/`mq_put_mnt` 在「自带原生 mqueue 的 DDK 内核」里同名；`names.h` 目前只重命名 `init_ipc_ns`/`mq_lock` | M1 用 `llvm-nm` 检查重复定义；必要时把这几个也改成 `ds_` 前缀 |
| 测试内核代表性 | 见 M2 | M2 必须完成，否则 VM 通过不代表设备可用 |
| CFI 按对象处理 | 设备是 KCFI（见 `device-profiles` 的 `cfi_implementation`）。社区实测：把「内核会回调进模块」的函数关掉 CFI 会导致内核侧 `CFI failure at alloc_fs_context (target: mqueue_init_fs_context)`、`… at process_one_work (target: free_ipc)` 而 panic；只有「调用运行时解析指针」的目标文件才可关 CFI | M1 逐文件设置：`mqueue_init_fs_context`/`file_operations`/`proc_ns_operations`/`work_struct` 回调保留 CFI，必要时只对单个函数 `__nocfi`；`activate=1` 真机确认 |
| 社区已报的 PID/slab 坑 | `PID_NS=n` 时 `zap_pid_ns_processes()` 是内联 `BUG()`；`free_nsproxy()` 永远存在，混用缓存会 SLUB 崩 | 既有端口已解决（4.4 节逐条对照），本项目继承并复核 |
| `/dev/mqueue` | 模块加载晚于 init，`/dev/mqueue` 需要模块自己挂；文件系统必须用真实名 `"mqueue"` 注册，`-EBUSY` 要降级 | 列入 M1/M3 验收项 |
| 分配器/内联差异 | 照抄上游 6.1 的 `alloc_inode_sb()` 会引入设备不存在的符号 | 已加入门禁拒绝清单（3.3 节） |
| 同一 KMI 的载荷选择 | `android14-6.1` 现指向 `src/port61`，而这个厂商画像同样匹配该 KMI | 安装器需按运行时能力（原生 `init_ipc_ns`/`mq_lock` 是否存在）而非 KMI 选择载荷；见 `open_decisions` |
| 产品侧 opt-in | Droidspaces 的检查走运行时探测，但官方至今没有正式承认「模块提供的 namespace」（issue #354 仍开着） | 本项目的目标是让检查自然通过；是否需要上游配合记在 `open_decisions` |
| 真机风险 | 模块激活后挂钩核心路径，激活状态下拒绝热卸载 | 未持久化安装，重启即恢复；先在 M2 内核上跑回归 |

## 7. 参考文献

- Droidspaces 官方内核配置指南（所需选项、GKI kABI padding 补丁与告警）：
  [Droidspaces-OSS/Documentation/Kernel-Configuration.md](https://github.com/ravindu644/Droidspaces-OSS/blob/main/Documentation/Kernel-Configuration.md)
- 内核模块加载期符号解析（非 weak 未定义符号 → `-ENOENT`）：
  `kernel/module/main.c` 的 `simplify_symbols()`（设备实测错误 `Unknown symbol … (err -2)` 与之一致）
- 空 `__versions` 段不是致命错误（「Broken toolchain. Warn once, then let it go」）：
  [kernel/module/version.c (v6.1)](https://raw.githubusercontent.com/torvalds/linux/v6.1/kernel/module/version.c)
- 上游 6.1 `ipc/mqueue.c`、`ipc/namespace.c`、`ipc/mq_sysctl.c` 作为 M1 的对照实现
- 上游 v5.15 ↔ v6.1 逐文件比对（`ipc/`、`kernel/pid*.c`、`kernel/nsproxy.c`、
  `fs/proc/namespaces.c`、`include/linux/{ipc_namespace,pid_namespace,nsproxy}.h`、
  `init/Kconfig`、`arch/arm64/configs/gki_defconfig`），见第 3.2 节结论
- 本仓库内的自持后端参考：`src/port515/{ipc.c,mqueue.c,mq_sysctl.c}`（主模板）、
  `src/port66/`、`src/port/`、`src/port618/`
- 同类先例：[lkm4ctr](https://github.com/cyanmint/lkm4ctr)（内含取自 ACK
  `android14-6.1` 的 `ipc/` 源码，以及
  [VENDOR_KERNEL.md](https://github.com/cyanmint/lkm4ctr/blob/master/docs/en/developer/VENDOR_KERNEL.md)）、
  [_patchHarmony](https://github.com/Dere3046/_patchHarmony)、
  [KallRecon](https://github.com/Dere3046/KallRecon)
- Droidspaces 侧态度变化与产品缺口：
  [issue #97](https://github.com/ravindu644/Droidspaces-OSS/issues/97)、
  [issue #354](https://github.com/ravindu644/Droidspaces-OSS/issues/354)
- KernelSU 加载机制（`SHN_UNDEF` → `SHN_ABS` 重定位、vermagic 改写重试）：
  [userspace/ksuinit/src/lib.rs](https://github.com/tiann/KernelSU/blob/main/userspace/ksuinit/src/lib.rs)、
  [userspace/ksud/src/debug.rs](https://github.com/tiann/KernelSU/blob/main/userspace/ksud/src/debug.rs)
- AOSP 安全特性：[KCFI](https://source.android.com/docs/security/test/kcfi)、
  [ShadowCallStack](https://source.android.com/docs/security/test/shadow-call-stack)
- 备选路线（改内核重刷 + kABI padding）：
  [Goldzxcbug/Droidspaces_Kernel_patch](https://github.com/Goldzxcbug/Droidspaces_Kernel_patch)

## 8. 使用与验证

### 8.1 模块名与产物位置

模块名（内核里的名字、`/sys/module` 下的目录名、`rmmod` 用的名字）：
**`droidspaces_ns`**；文件名 `droidspaces_ns.ko`。

| 位置 | 路径 |
| --- | --- |
| CI 产物 | workflow `build-port61-nomq`（`mode=target`）的 artifact `port61-nomq-target`，内含 `droidspaces_ns.ko` |
| 本机已下载的副本 | `out/nomq/droidspaces_ns.ko`（git 忽略） |
| 真机上正在运行的那一份 | `/data/local/tmp/ds-nomq.ko`，sha256 `1f70603e…cff2d` |

⚠️ 与 `src/port61` 的 GKI 包**同名但不同物**：`build-android14-6.1-gki` 产出的
`droidspaces_ns.ko` 在本机会因 7 个缺失符号加载失败，只有 `src/port61nomq` 的
这一份能在缺少 `CONFIG_POSIX_MQUEUE`/`CONFIG_IPC_NS` 的内核上工作。

### 8.2 重新构建

GitHub Actions 上仅手动触发（`mode=target`）：

```sh
gh workflow run build-port61-nomq.yml -R Xieansecn/Droidspaces-LKM --ref main -f mode=target
gh run watch "$(gh run list -R Xieansecn/Droidspaces-LKM --workflow build-port61-nomq.yml \
  --limit 1 --json databaseId --jq '.[0].databaseId')"
gh run download <run-id> -R Xieansecn/Droidspaces-LKM -n port61-nomq-target -D out/nomq
```

该模式会顺带跑设备符号门禁（`scripts/port61-nomq-gate.py`）：必须「不导入任何设备
缺失符号」且「定义 `ds_init_ipc_ns`/`ds_mq_lock`/`ds_copy_ipcs`/`ds_ipcns_operations`」，
否则 job 失败。

### 8.3 加载命令

必须在**内核态 root**（KernelSU 的 `su`）下用 ksud 加载：

```sh
su -c '/data/adb/ksud insmod /data/local/tmp/ds-nomq.ko gki=1 activate=1'
```

| 参数 | 说明 |
| --- | --- |
| `gki=1` | **必需**。`src/gki-target.h` 的 GKI 门禁要求：要么在构建 VM 内，要么显式 `gki=1` 且 `uname -r` 形如 `6.1.*-android14-*`。不传会被模块自己拒绝（`-EOPNOTSUPP`，dmesg 打印 `requires matching android14-6.1 with gki=1 or the build VM`） |
| `activate=1` | 安装挂钩并激活（19 个函数入口、19 个系统调用槽、6 个 BPF 回调）。**只有激活后** `/proc/self/ns/{pid,ipc}` 才出现 |
| `plc110_test=1` | 仅用于 PLC110/6.6 测试画像，本机不要用 |

只传 `gki=1` 即「只加载不激活」：会跑自检并注册 `/proc/sysvipc/*`、
`/proc/sys/fs/mqueue/*`、`/proc/sys/kernel/msgmax`，但不写任何内核代码补丁，
此时可以干净 `rmmod`。

### 8.4 如何确认加载成功

三层验证，从快到强：

```sh
# 1) 模块态：存在 + 参数
su -c 'ls -d /sys/module/droidspaces_ns && cat /sys/module/droidspaces_ns/parameters/activate'
#   -> /sys/module/droidspaces_ns      activate=Y

# 2) 内核日志：门禁 / 自检 / 激活
su -c 'dmesg | grep droidspaces_ns'
#   -> entry preflight passed: 19 functions, 19 syscalls, 6 BPF callbacks; no patches written
#   -> PID: allocation, parent, IDR, sharing and invalid-parent checks passed
#   -> IPC: allocation, namespace identity, owner and sharing checks passed
#   -> experimental namespace hooks active; module stays pinned until reboot

# 3) 功能：接口出现 + 真的能建命名空间
su -c 'ls /proc/self/ns/'                      # 必须能看到 ipc / pid / pid_for_children
su -c 'unshare -i sh -c "readlink /proc/self/ns/ipc"'   # 与初始 ipc:[4026531839] 不同的新 id
su -c 'unshare -p -f sh -c "echo \$\$"'                 # 1（新 PID 命名空间内的 PID 1）
su -c 'unshare -p -f unshare -p -f sh -c "echo \$\$"'   # 1（嵌套 PID 命名空间）
su -c 'mkdir -p /dev/mqueue-ds && unshare -i sh -c \
  "mount -t mqueue none /dev/mqueue-ds && umount /dev/mqueue-ds && echo mqueue_mount_ok"'
```

补充判据：`dmesg | grep -icE "Unable to handle kernel|kernel BUG at|Call trace"` 应为
0；看不到 `/proc/self/ns/ipc` 就说明没激活或加载失败。

### 8.5 卸载与恢复

| 状态 | 卸载方式 |
| --- | --- |
| 只加载未激活（`gki=1`） | `su -c '/data/adb/ksu/bin/busybox rmmod droidspaces_ns'` |
| 已激活（`activate=1`） | **无法热卸载**（`rmmod` 报 `Try again`），重启即可；模块不持久化（`/data/adb/modules` 无条目），重启后回到出厂行为 |

开机自动加载需要做成 KernelSU 模块包（仓库 `kernelsu/` 里有现成脚本框架），并且要
先解决「同一 KMI 两个画像」的载荷选择：安装器应检查内核是否已有原生
`mq_lock`/`init_ipc_ns`/`ipcns_operations`（有 → 用 `src/port61` 的包，没有 → 用本项目的包），
而不是只看 KMI。
