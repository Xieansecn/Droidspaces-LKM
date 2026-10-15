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
| 规模 | 新增约 1,930 行（`mqueue.c` + `mq_sysctl.c`）+ 约 300 行适配 |
| 最近模板 | `src/port66`（6.6）——`src/port61/ORIGIN` 已记录 6.1 端口就是由它改编 |
| 主要风险 | `mqueue.c` 的 6.6→6.1 API 适配；测试内核能否代表设备（DDK 内核自带原生 mqueue） |
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

## 3. 工作量：与最近模板的实际差距

`src/port66` 与 `src/port61` 的文件集合只差 `mqueue.c`、`mq_sysctl.c` 两个文件，
其余同名文件的差异行数（`diff` 行计数，含上下文）：

| 文件 | p61 vs p66 | 说明 |
| --- | --- | --- |
| ipc.c | 101 | 自持 `init_ipc_ns`/`mq_lock`/`copy_ipcs`/`free_ipc_ns`/`ipcns_operations` |
| ipc-task.c | 66 | 自持 init namespace 路径 |
| ipc_sysctl.c | 17 | 注册自己的 ipc/mqueue sysctl 树 |
| exit.c / hooks.c / nsproxy.c / main.c | 14 / 38 / 44 / 7 | 生命周期与挂钩；**nsproxy.c 的 44 行是 6.6 专属改动，不可回移** |
| ipc-util.c/h、ipc-backend.h、names.h、fork.c、pid.c、sem.c、shm.c | 各 4–12 | 小幅适配 |
| msg.c、proc_ns.c、selftest.c | 0 | 已完全一致 |
| mqueue.c / mq_sysctl.c | 新增 | 1,761 + 170 行，随后做 6.6→6.1 适配 |

关键判据：`src/port66/names.h` 相对 `src/port61/names.h` **只多两行**
（`init_ipc_ns → ds_init_ipc_ns`、`mq_lock → ds_mq_lock`），`hooks.c` 则从「包装
原生 `copy_ipcs`/`put_ipc_ns`/`ipcns_put`/`ipcns_install`」变成「自己拥有这些
入口」。也就是说这次移植的主体是**把已有的自持后端搬回来**，不是重新设计 IPC。

完整文件级清单、里程碑与验收门禁见
[build/port61-nomq.json](../build/port61-nomq.json)（`change_list`、`milestones`、
`gates`）。

## 4. 外部检索：主流做法与本仓库路线的取舍

Droidspaces 官方文档（[Kernel-Configuration.md](https://github.com/ravindu644/Droidspaces-OSS/blob/main/Documentation/Kernel-Configuration.md)）
列出容器所需的全部选项，并明确写下 GKI 上的结论：`CONFIG_SYSVIPC`、
`CONFIG_IPC_NS`、`CONFIG_POSIX_MQUEUE` **会给核心结构加字段、移动 ABI**，直接打开
会让厂商 prebuilt 模块拒绝加载、设备 bootloop；因此他们的做法是给内核打
kABI padding 补丁（把新字段塞进 ABI 已保留的填充位）后**重新编译并刷写内核**。
同一文档还给出两条经验：

- 「不要为了绕过校验而关闭 `CONFIG_MODVERSIONS` 或强载模块；结构确实变了。」
- `CONFIG_CFS_BANDWIDTH` / `CONFIG_CGROUP_PIDS` 会改变调度器与 cgroup 结构，
  没有 padding 补丁覆盖，只能连带重编所有厂商模块。

对照到本设备：

| 需求 | 官方路线（改内核重刷） | 本仓库 LKM 路线 |
| --- | --- | --- |
| PID / IPC namespace | 打开 `CONFIG_PID_NS`、`CONFIG_IPC_NS`（需 kABI 补丁） | 模块提供（PID 已具备，IPC 为本次项目） |
| POSIX mqueue / SysV IPC | 打开 `CONFIG_POSIX_MQUEUE`、`CONFIG_SYSVIPC`（需 kABI 补丁） | 模块提供后端，**不打开 `CONFIG_SYSVIPC`，因此不动 `task_struct`/kABI** |
| devtmpfs | 打开 `CONFIG_DEVTMPFS` | 需要单独的 devtmpfs 移植（M4） |
| user namespace 沙箱 | 打开 `CONFIG_USER_NS` | 需要单独的 userns 移植（M4） |
| `--cpus` / `--pids-limit` | 需 `CONFIG_CFS_BANDWIDTH`/`CONFIG_CGROUP_PIDS`，官方也标注为破坏 ABI、默认不推荐 | 本设备两者皆无，本次不覆盖，属于已知功能缺失 |

这个对照说明两件事：本仓库的 LKM 路线在「不改布局」这一维度上比官方路线更保守
（也是它能免刷机的前提）；代价是 IPC/mqueue/devtmpfs/userns 必须由模块实现，
并且 `--cpus`/`--pids-limit` 这类依赖调度器与 cgroup 布局的能力无法提供。

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

## 6. 风险与未决问题

| 风险 | 说明 | 缓解 |
| --- | --- | --- |
| 6.6→6.1 API 适配 | `mqueue.c`/`mq_sysctl.c` 是 6.6 文本；sysctl 注册风格、`ctl_table`、挂载/`fs_context`、percpu 计数等需按上游 6.1 `ipc/mqueue.c` 核对 | M1 的编译循环 + 以上游 6.1 为参照；本文件第 3 节的差异表作为起点 |
| 符号重名 | 模块自持的 `mq_init_ns`/`mq_clear_sbinfo`/`mq_put_mnt` 在「自带原生 mqueue 的 DDK 内核」里同名；`names.h` 目前只重命名 `init_ipc_ns`/`mq_lock` | M1 用 `llvm-nm` 检查重复定义；必要时把这几个也改成 `ds_` 前缀 |
| 测试内核代表性 | 见 M2 | M2 必须完成，否则 VM 通过不代表设备可用 |
| CFI / SCS / LTO | 设备 `CFI_CLANG`、`SHADOW_CALL_STACK` 均为 y，模块自持函数指针路径需与之一致 | 沿用其它端口的既有做法；真机加载与功能测试为准 |
| 真机风险 | 模块激活后挂钩核心路径，激活状态下拒绝热卸载 | 未持久化安装，重启即恢复；先在 M2 内核上跑回归 |
| 未检索到的先例 | 尚未找到「LKM 自带 POSIX mqueue 后端」的外部先例；本仓库的 port515/66/6.12/6.18 是目前最直接的实现参考 | 继续跟踪上游与社区（见下方待办） |

## 7. 参考文献

- Droidspaces 官方内核配置指南（所需选项、GKI kABI padding 补丁与告警）：
  [Droidspaces-OSS/Documentation/Kernel-Configuration.md](https://github.com/ravindu644/Droidspaces-OSS/blob/main/Documentation/Kernel-Configuration.md)
- 内核模块加载期符号解析（非 weak 未定义符号 → `-ENOENT`）：
  `kernel/module/main.c` 的 `simplify_symbols()`（设备实测错误 `Unknown symbol … (err -2)` 与之一致）
- 空 `__versions` 段不是致命错误（「Broken toolchain. Warn once, then let it go」）：
  [kernel/module/version.c (v6.1)](https://raw.githubusercontent.com/torvalds/linux/v6.1/kernel/module/version.c)
- 上游 6.1 `ipc/mqueue.c`、`ipc/namespace.c`、`ipc/mq_sysctl.c` 作为 M1 的对照实现
- 本仓库内的自持后端参考：`src/port66/{ipc.c,mqueue.c,mq_sysctl.c}`、
  `src/port515/`、`src/port/`、`src/port618/`
