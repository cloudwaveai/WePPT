# WePPT 容器部署

用户于 2026-10-27 指定采用容器化部署，并询问复用服务器 Codex 配置。部署文件已准备，尚未上传或启动。

## 服务器核验结果

此前已通过严格 known_hosts SSH 成功核验：Python 3.12.3、Node.js 22.23.1、Codex CLI 0.162.1；/opt 文件系统空闲约 13.9 GiB；/opt/weppt 不存在，8766 端口空闲。Webuddy 与 Caddy active，factory-web inactive。

服务器 /home/ubuntu/.codex/config.toml 存在且权限 0600，模型 gpt-6-luna，provider aiseat，Responses 协议，端点主机 ai.cloudwaveai.cn。没有输出凭据或验证模型调用。配置如何认证、是否依赖环境变量、容器内兼容性仍需核验。

随后一次 SSH 返回 Permission denied (publickey)，之后重新连接恢复成功，原因未知。恢复后确认 Docker context=rootless、Docker 29.6.2、Compose v5.3.1。Codex provider 包含 experimental_bearer_token 和 http_headers 字段；未读取输出这些字段的值。当前适配器的白名单没有转发这两个认证字段，因此不能声称仅挂载配置就能调用；部署时需要在服务器内最小认证适配及防泄漏验证。尚未上传文件或启动容器。

## WePPT 独立模型选择

可用 WEPPT_CODEX_MODEL 指定 WePPT 的模型，不修改全局 Codex 配置。2026-10-27 本机模型目录列出 commandcode-plan/gpt-6.1-terra，但真实调用返回 403 / MODEL_NOT_IN_PLAN，提示需要 Pro 及以上套餐或额外按量使用权限。因此尚未将运行实例切换到 Terra；保持原 Sol 模型。服务器服务商是否提供同模型需独立核验。

## 容器文件

- Dockerfile：Python 3.12、Node 22、固定 Codex CLI 0.162.1 和锁定 npm 依赖；普通用户运行。
- compose.yaml：独立数据卷与 Codex 配置卷、只读根文件系统、临时目录、日志轮转、禁止提权。
- .dockerignore：白名单构建上下文，排除本机项目数据、虚拟环境、客户端配置及凭据。

Codex CLI 安装于镜像中；服务器既有配置按需在服务器内提供给独立配置卷。不得将凭据打进镜像或复制到 Mac。部署前只读核验配置的实际认证字段，再决定最小配置文件或环境变量注入方式；不能把“配置存在”当作容器已经能调用模型。

当前 Compose 为 Linux host 网络方案，以保留应用仅监听 127.0.0.1 的行为。应用无法通过普通桥接端口映射直接访问。若服务器使用 rootless Docker，必须核验其 host 网络是否能从宿主访问；不可直接认定可用。必要时改为容器监听地址配置加宿主 loopback 端口映射，并保持 Host/Origin 校验。

## SSH 恢复后执行

1. 核验 Docker context、Compose、磁盘、现有容器及服务端 Codex 认证结构，只投影非秘密字段。
2. 完成网络与配置注入适配，构建镜像并验证非 root 运行、认证、项目隔离及 PPTX 导出。
3. 使用独立空白项目验证最小 Codex 请求；不修改其他应用的 Codex 配置，不迁移本机项目。
4. 启动独立容器并核验原有服务保持。

初期通过 SSH 隧道使用，客户端与后端端口需同为 8766 以满足当前 Host/Origin 校验；Mac 现有 8766 服务需保留时应另选一致的新端口。

正式公网域名还需明确外部 origin、HTTPS Secure Cookie、稳定私有认证配置和独立反向代理路由。不得覆盖 ppt.bbstack.date 现有模板站。
