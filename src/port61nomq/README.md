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

状态：**M0 种子脚手架**。本目录当前是 `src/port61` 的副本再加上
`src/port66` 的 `mqueue.c` / `mq_sysctl.c`，尚未完成 6.6→6.1 适配，不参与
`build/gki-targets.json`，也不随任何发布包发布。剩余工作见
[ORIGIN](ORIGIN) 与项目定义中的 `change_list` / `milestones`。
