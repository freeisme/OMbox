# GitHub Wiki 页面源文件

这里的 Markdown 是 GitHub Wiki 的**源文件**：Wiki 目前还没有页面（GitHub 需要先在网页上
点一次「Create the first page」才会创建对应的 `.wiki.git` 仓库），等它存在后按下述步骤推送。

## 首次创建 Wiki 仓库

在浏览器打开仓库的 Wiki 页，点「Create the first page」，标题填 `Home`，内容随意保存即可
（随后会被下面的推送覆盖）。这一步 GitHub 只允许在网页上做。

## 推送这些页面

```bash
git clone https://github.com/<owner>/<repo>.wiki.git
cp docs/wiki/*.md <wiki-clone>/          # 文件名即页面名，Home.md 是首页
cd <wiki-clone>
git add -A && git commit -m "docs: initial wiki" && git push
```

页面命名约定：`Home.md` 为首页，其余按主题命名（英文 + 连字符），
正文里用 `[标题](页面名)` 互相引用。

## 更新流程

1. 先改本目录的 Markdown（随代码一起提交、一起过脱敏扫描）；
2. 再把它同步到 Wiki 仓库；
3. Wiki 内容与 `docs/development/` 下的开发文档保持一致：
   开发文档面向改代码的人，Wiki 面向用系统的人。

## 脱敏

Wiki 是公开内容，禁止出现内网地址、本机绝对路径、账号口令、令牌与真实人员/设备编号；
示例一律使用占位符。推送前先跑 `python tools/scan_release_safety.py --rev HEAD`。
