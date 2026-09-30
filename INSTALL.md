# 安装说明（写给 Agent）

用户把这个仓库的链接发给你，让你帮忙安装「有条有理」时，照这份说明一步步做。这份说明在 **macOS 上的 Claude Code** 里完整走过；其他 Agent 或系统大体也能照做，遇到对不上的地方停下来告诉用户。

仓库地址：`https://github.com/NowhereMan-in-Galaxy/personal-assistant`

## 规则

- 每一步做之前，用一句话告诉用户你要做什么。需要用户点击、登录、授权的地方，停下来等用户做完。
- 装东西（uv、Claude in Chrome）之前先问用户同不同意。
- 不要把用户的任何个人信息写进仓库，也不要替用户提交（git commit / push）。
- 某一步报错，就把报错原文告诉用户，不要换别的办法硬装。

## 步骤

### 1. 检查 uv

运行 `uv --version`。

没有的话，问用户同意后运行（macOS / Linux）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows 用 `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`。

装完后当前终端可能还找不到 `uv`，用 `~/.local/bin/uv` 代替，或者请用户重开终端。uv 会自己准备 Python，不需要另外装。

### 2. 下载项目

问用户想放在哪，默认 `~/personal-assistant`。

有 git：

```bash
git clone https://github.com/NowhereMan-in-Galaxy/personal-assistant.git ~/personal-assistant
```

没有 git：

```bash
curl -L -o /tmp/youtiao.zip https://github.com/NowhereMan-in-Galaxy/personal-assistant/archive/refs/heads/main.zip
unzip -q /tmp/youtiao.zip -d ~ && mv ~/personal-assistant-main ~/personal-assistant
```

### 3. 装依赖并自检

```bash
cd ~/personal-assistant
uv sync
uv run python -m core.guides
```

最后一条命令的输出里全是 ✓ 就说明装好了。

### 4. 资料放在哪

问用户："你的材料（护照扫描件、流水这些）想放在哪？默认放在项目里的 `materials/` 文件夹；如果想多台电脑同步，可以放在 iCloud 或 Google Drive 里的一个文件夹。"

- 用默认位置：什么都不用做。
- 放在别处：把 `config.example.yaml` 复制成 `config.yaml`，把 `materials_root` 改成用户给的**绝对路径**。文件夹不存在就先建好。

### 5. 启动

```bash
cd ~/personal-assistant && uv run youtiao
```

这条命令会一直运行，并打开浏览器访问 <http://127.0.0.1:8000>。你可以在后台启动它，确认页面能打开，然后告诉用户：**以后每次用，在终端里运行这一行；关掉终端就停了。**

想先看效果，可以改用 `uv run youtiao --demo`，打开的是一套虚构资料，不会碰用户自己的数据。

### 6. 让 Claude Code 能用项目里的工具

项目里有给 Agent 用的工具（`.mcp.json`）和操作说明（`.claude/skills/`），只有**在项目文件夹里打开的** Claude Code 才会加载。告诉用户：

1. 新开一个终端，运行 `cd ~/personal-assistant && claude`；
2. Claude Code 问要不要启用 `personal-assistant` 这个 MCP 服务时，选**启用**（选错了可以输入 `/mcp` 重新打开）。

页面上的「让 Agent 整理」「新建攻略」「问 Agent」会自己调用 Claude Code，不需要额外设置，只要用户已经登录过 Claude Code。

### 7. 填表插件（要用户自己点）

Chrome 不允许程序替用户装插件。把下面三步发给用户，把路径换成实际的：

1. Chrome 地址栏打开 `chrome://extensions`，打开右上角的「开发者模式」；
2. 点「加载已解压的扩展程序」，选 `~/personal-assistant/extension` 文件夹；
3. 点工具栏上的插件图标打开侧边栏，到官网上点「填本页」。

### 8. 可选：读小红书帖子

「新建攻略」里让 Agent 读小红书帖子，需要 [Claude in Chrome](https://claude.ai/chrome) 扩展。问用户要不要装；不装的话，可以把帖子正文直接粘贴进去。

### 9. 带用户上手

装好后告诉用户：在第 6 步打开的 Claude Code 里说"**带我上手**"，或者在网页右下角「问 Agent」里点"带我上手"。它会问最近要办什么事，帮用户挑攻略、补基本信息、登记材料。

## 装好后给用户的总结

用三四行告诉用户：装在哪、资料放在哪、以后怎么启动（`cd ~/personal-assistant && uv run youtiao`）、插件装了没有。
