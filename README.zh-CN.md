# UCanDrop

在 Ubuntu 上通过 AirDrop 传输内容，支持图片、视频、文档和网址等。
本项目基于 Omdrop 和 OWL，并在其基础上进行了文件完整性校验及无线传输优化。

简体中文 | [English](README.md)

## 快速安装（推荐）

目标系统是 **Ubuntu 26.04 桌面版**，GNOME 为参考桌面。需要蓝牙和兼容的无线网卡；
无线要求见下方「兼容范围」。

下载[发布附件](https://github.com/lazitech/ucandrop/releases/tag/v1.1.0)中的 **`ucandrop_1.1.0_amd64.deb`**，在该文件所在目录打开终端，运行：

```bash
sudo apt install ./ucandrop_1.1.0_amd64.deb
ucandrop setup
```

当前预编译包适用于 amd64（x86_64）。可用 `dpkg --print-architecture` 查看系统架构；
arm64 用户请使用文末的源码安装方式。

## 第一次接收

先检查环境，再开启一小时的接收窗口：

```bash
ucandrop doctor --json
ucandrop on 1h
```

如果检查或启动报告无线条件不满足，请按「兼容范围」核对连接和网卡。
启动前关闭其他 AirDrop 接收程序，避免争用无线接口和接收端口。

1. 在 iPhone 上开启 Wi-Fi 和蓝牙，让手机靠近电脑。
2. 打开照片或文件，选择「分享 → AirDrop」。
3. 选择电脑名称发送。名称读取本机主机名或用户设置。
4. 传输完成后，点击电脑上的 **AirDrop** 系统通知打开文件。


文件默认保存到系统下载目录。接收窗口到期后自动关闭，也可提前关闭：

```bash
ucandrop off
```

## 从电脑发送到 iPhone

先在 iPhone 上将 AirDrop 设为「所有人（10 分钟）」并保持亮屏，然后运行：

```bash
ucandrop send /path/to/file --pick
```

将 `/path/to/file` 替换为要发送的文件路径，在列表中选择手机。

## 常用命令

| 操作 | 命令 |
| --- | --- |
| 检查环境 | `ucandrop doctor --json` |
| 开启一小时接收 | `ucandrop on 1h` |
| 查看接收状态 | `ucandrop status --json` |
| 查看附近设备 | `ucandrop peers` |
| 发送文件并选择设备 | `ucandrop send /path/to/file --pick` |
| 修改保存目录 | `ucandrop dir /path/to/folder` |
| 关闭接收 | `ucandrop off` |

防火墙阻止接收时，可运行 `ucandrop firewall install` 添加限定范围的 AWDL 接收规则。
文件点击后无法打开时，请确认系统安装了对应的默认查看器。

## 兼容范围

需要 NetworkManager、systemd 用户服务和支持点击动作的桌面通知服务。
无线网卡及驱动必须支持适当的监控、注入和确认帧能力。

当前版本使用共享无线模式：电脑保持现有 Wi-Fi 连接，该连接的接入点频率需满足下表，
并且允许在当地使用：

| 频段 | 信道 | 实际频率 |
| --- | --- | --- |
| 2.4 GHz | 6 | 2437 MHz |
| 5 GHz | 44 | 5220 MHz |
| 5 GHz | 149 | 5745 MHz |

6 GHz 中相同编号的信道不能替代这些频率。程序读取实际连接及法规限制，
不依赖互联网或网关回应 ping，也不会修改路由器或自动断开 Wi-Fi。

未知驱动会被标为未经验证。查看检查结果后，若决定尝试，可运行：

```bash
sudo install -d -m 0755 /etc/ucandrop
printf '1\n' | sudo tee /etc/ucandrop/allow-untested >/dev/null
ucandrop doctor --json
```

删除 `/etc/ucandrop/allow-untested` 即可恢复默认策略。

## 从源码安装（可选）

需要自行构建、修改代码或使用 arm64 时，下载并解压[源码压缩包](https://github.com/lazitech/ucandrop/releases/download/v1.1.0/ucandrop-1.1.0-source.tar.gz)，
在项目目录中以普通桌面用户运行：

```bash
./tools/install.sh --install --install-build-deps
ucandrop setup
```

如只想检查源码构建环境，可运行 `./tools/install.sh --check`。该命令不安装任何东西；
缺少构建工具或运行依赖时会列出缺项并返回非零状态。

请在已登录的桌面会话中运行配置和收发命令。XDG 配置目录应与该会话的
systemd 用户管理器一致；只在终端修改变量不会改变服务搜索目录。
收发使用标准 `/run/user/<uid>` 运行目录，临时覆盖 `XDG_RUNTIME_DIR` 会被拒绝。

## 卸载

关闭接收后，通过 apt 卸载程序：

```bash
ucandrop off
sudo apt remove ucandrop
```

完整构建与验证说明见 [英文 README](README.md)和[发布验证记录](docs/validation.md)。
项目来源与许可证见[第三方来源说明](THIRD_PARTY_NOTICES.md)；版本变化见[变更记录](CHANGELOG.md)。
