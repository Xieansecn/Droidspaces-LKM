# port61-nomq

自持 IPC namespace / POSIX mqueue 后端的 6.1 目标，面向 `CONFIG_SYSVIPC=n`、
`CONFIG_POSIX_MQUEUE=n`（因此 `CONFIG_IPC_NS` 不可用）的厂商内核。现有
`src/port61` 依赖 6.1 GKI 基线的 `init_ipc_ns` / `mq_*`，在这类内核上会因内核
符号解析失败（-ENOENT）而无法加载。

- 评估与计划：[docs/port61-nomq.md](../../docs/port61-nomq.md)
- 机器可读项目定义：[build/port61-nomq.json](../../build/port61-nomq.json)
- 目标设备档案：[build/device-profiles/6.1.138-android14-11.json](../../build/device-profiles/6.1.138-android14-11.json)
- CI：`.github/workflows/build-port61-nomq.yml`（仅手动触发；`mode=reference`
  构建模板后端并记录其导入符号，`mode=target` 构建本目录并执行设备符号门禁）

状态：**M1 完成，已在真机验证**。本目录现在是 `src/port61` 加上自持的
IPC namespace 与 POSIX mqueue 后端（取自 `src/port515` 的 `mqueue.c` /
`mq_sysctl.c`，并按 6.1 调整调用形式）。CI 门禁通过（无阻塞符号、四个后端符号
均已定义），在 6.1.138 真机上 `ksud insmod … gki=1 activate=1` 成功，
`/proc/self/ns/{pid,ipc}` 出现，`unshare -i` / `unshare -p -f` / 嵌套 PID
namespace / 新命名空间内 `mount -t mqueue` 均通过。

仍不参与 `build/gki-targets.json`，也不随发布包发布：载荷选择（同一 KMI 两个
画像）与 KernelSU 打包尚未完成。细节见 [ORIGIN](ORIGIN)、
[docs/port61-nomq.md](../../docs/port61-nomq.md) 与
`build/device-profiles/6.1.138-android14-11.json` 的 `m1_device_validation`。
