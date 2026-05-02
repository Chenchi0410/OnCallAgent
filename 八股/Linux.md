# Linux 面试八股（速答版）

> 目标：不只背命令，还能按“排障/部署场景”串起来讲清楚。

---

## 1) 文件与目录：ls / cd / pwd / mkdir / rm / cp / mv / tar

### 一句话回答
Linux 文件操作的核心是“路径 + 通配符 + 递归/强制参数”，常用 `ls/cd/pwd/mkdir/rm/cp/mv` 完成日常管理，打包用 `tar`。

### 常用命令（面试口述即可）
- 查看：`ls -lah`（长格式 + 隐藏 + 人类可读）
- 进入/定位：`cd /path`、`pwd`
- 创建目录：`mkdir -p a/b/c`
- 删除：
  - `rm file` 删除文件
  - `rm -r dir` 递归删目录
  - `rm -rf dir` 强制递归（谨慎）
- 拷贝/移动：`cp -r src dst`、`mv old new`
- 打包解包（tar 最常考）：
  - 打包：`tar -czf app.tar.gz app/`
  - 解包：`tar -xzf app.tar.gz`

### 常见追问
- **rm 误删怎么救？**
  - 真实生产通常靠：备份/快照、文件系统恢复工具（ext4 的 extundelete 等但不保证），以及“权限隔离 + 最小化误操作”。

---

## 2) 日志：tail -f 实时看，grep 过滤

### 一句话回答
线上排障日志优先“实时跟踪 + 关键字过滤 + 时间范围定位”：用 `tail -f` 跟踪，用 `grep` / `egrep`（`grep -E`）过滤。

### 常用套路（面试高频）
- 实时看最新：`tail -n 200 -f app.log`
- 关键字过滤：
  - `grep "ERROR" app.log`
  - `grep -n "Exception" app.log`（带行号）
  - `grep -E "ERROR|WARN" app.log`
- 结合管道（展示你会用）：
  - `tail -f app.log | grep -E "ERROR|timeout"`

### systemd/journald 日志（加分）
- 看服务日志：`journalctl -u myapp -f`
- 按时间：`journalctl -u myapp --since "2026-04-24 10:00"`

---

## 3) 进程：ps / kill / top

### 一句话回答
定位问题一般先确认“进程在不在、CPU/内存高不高、线程卡在哪”：用 `ps` 查进程，用 `top/htop` 看资源，用 `kill` 发送信号优雅退出或强杀。

### 常用命令
- 查进程：
  - `ps -ef | grep java`
  - `ps aux | grep myapp`
- 监控：`top`（或 `htop` 更友好）
- 终止：
  - 优雅：`kill PID`（默认 SIGTERM）
  - 强制：`kill -9 PID`（SIGKILL，最后手段）

### 常见追问
- **SIGTERM vs SIGKILL 区别？**
  - SIGTERM 可被程序捕获做清理；SIGKILL 立即终止，无法捕获，可能导致数据不一致。

---

## 4) 权限：chmod / chown

### 一句话回答
Linux 权限本质是 `rwx` 作用于 owner/group/other；`chmod` 改权限位，`chown` 改属主/属组。

### 你要会讲清楚的点
- 权限表示：
  - 数字法：`chmod 755 file`（owner=7 rwx，group=5 r-x，other=5 r-x）
  - 符号法：`chmod u+x file`、`chmod g-w file`
- 改属主：`chown user:group file`（目录常用 `-R` 递归）

### 常见追问
- **文件能执行但报 Permission denied？** 可能是：没有 x 权限、挂载为 noexec、SELinux 限制等。

---

## 5) 部署：nohup 后台跑、端口查看（netstat/ss）

### 一句话回答
简单部署常用 `nohup`/后台运行，生产更推荐用 systemd 托管；端口占用用 `ss`/`netstat` 定位，配合 `lsof` 找到进程。

### nohup 方式（面试常见，但要说清局限）
- 启动：`nohup java -jar app.jar > app.log 2>&1 &`
- 查看：`ps -ef | grep app.jar`
- 局限：不便于自动拉起、日志轮转、健康检查；生产更推荐 systemd。

### 端口排查（高频）
- 新系统优先：`ss -lntp`（监听 TCP + 进程）
- 旧系统：`netstat -lntp`
- 精确找端口：
  - `ss -lntp | grep :8080`
  - `lsof -i :8080`

---

## 6) 环境：vim / scp / systemd

### 6.1 vim（会最基本就够）
- 常用：`/pattern` 搜索，`n` 下一个，`i` 插入，`Esc` 退出编辑，`:wq` 保存退出，`:q!` 强退。

### 6.2 scp（传文件）
- 上传：`scp app.jar user@host:/opt/app/`
- 下载：`scp user@host:/opt/app/app.log ./`
- 目录：`scp -r dir user@host:/opt/app/`

### 6.3 systemd 托管（强烈建议能答）
- 基本操作：
  - `systemctl start|stop|restart myapp`
  - `systemctl status myapp`
  - `systemctl enable myapp`（开机自启）
- 看日志：`journalctl -u myapp -f`

#### service 文件示例（面试展示用）
```ini
# /etc/systemd/system/myapp.service
[Unit]
Description=My Java App
After=network.target

[Service]
User=app
WorkingDirectory=/opt/myapp
ExecStart=/usr/bin/java -jar /opt/myapp/app.jar
Restart=always
RestartSec=3
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

---

## 7) 常考补充：网络/磁盘/内存/定位占用

### 7.1 网络连通性
- DNS/解析：`nslookup domain`（或 `dig`）
- 连通：`ping host`（有时被禁）
- 端口连通：`curl -v http://host:port/health`

### 7.2 磁盘与目录占用（非常高频）
- 磁盘：`df -h`
- 目录大小：`du -sh * | sort -h`
- 找大文件：`find /var/log -type f -size +100M`

### 7.3 内存/负载
- 内存：`free -h`
- 负载：`uptime`（load average）

### 7.4 定位哪个进程最吃资源
- CPU/内存：`top`（按 P/M 排序）
- 打开文件数：`lsof -p PID | wc -l`

---

## 8) 面试“线上排障”串讲模板（背这段最顶用）

当被问“线上接口变慢/服务不可用你怎么排查”：
1. 先确认是否存活：`systemctl status` / `ps`，是否频繁重启。
2. 看资源：`top`（CPU/内存）、`df -h`（磁盘满）、`ss -lntp`（端口是否监听）。
3. 看日志：`tail -f` 或 `journalctl -u xxx -f`，grep 错误关键字。
4. 定位根因：是 JVM/应用异常、磁盘满、端口冲突、依赖超时、流量突增。
5. 处置：限流/回滚/重启（优雅）/扩容，并补监控与告警。

---

## 面试快速结尾句（可选）
- “我线上更倾向用 systemd 托管，配合 journalctl 查看日志，避免 nohup 方式的不可控问题。”
- “排障我会按：存活 → 资源 → 端口 → 日志 → 根因 的顺序，尽快缩小范围。”
