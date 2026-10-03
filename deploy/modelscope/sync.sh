#!/usr/bin/env bash
# 把项目代码推送到魔搭创空间仓库（用魔搭专用的 Dockerfile / README 覆盖根目录同名文件）。
#
# 需要环境变量：
#   MS_SPACE  —— 形如 <用户名>/<空间名>，例如 zhangsan/ai-daily-brief
#   MS_TOKEN  —— 魔搭访问令牌（个人中心 → 访问令牌 → 新建）
# DRY_RUN=1 时只组装目录、打印内容，不推送（本地验证用，推荐先跑这个）。
#
# 用法（在 Git Bash 里）：
#   DRY_RUN=1 MS_SPACE=you/ai-daily-brief bash deploy/modelscope/sync.sh
#   MS_SPACE=you/ai-daily-brief MS_TOKEN=xxx bash deploy/modelscope/sync.sh
set -euo pipefail

: "${MS_SPACE:?需要 MS_SPACE，形如 user/space-name}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

work="$(mktemp -d)"
# Windows Git Bash 的 mktemp 返回带盘符的路径（C:\...），
# GNU tar 会把 C: 误解析成远程主机、rm 也会被安全策略拦；统一转成 /c/... 形式
if command -v cygpath >/dev/null 2>&1; then
  work="$(cygpath -u "$work")"
fi
trap 'rm -rf "$work"' EXIT

# 1) 主体用 git archive：只导出「已追踪」的文件，自动排除 .coverage / .pt_* /
#    htmlcov / 各种缓存等未追踪的临时产物，保证推上去的仓库干净。
cd "$PROJ_ROOT"
git archive HEAD | tar -x -C "$work"

# 2) deploy/modelscope/ 用「工作区最新版」覆盖：
#    git archive 只含已提交内容，而这套部署文件可能刚写好还没 commit，
#    所以单独复制工作区版本，保证未提交的最新改动也能生效。
mkdir -p "$work/deploy/modelscope"
for f in Dockerfile start.sh README.md sync.sh; do
  cp "$SCRIPT_DIR/$f" "$work/deploy/modelscope/$f"
done

# 3) 根目录用魔搭专用的 Dockerfile / README（仓库根那份是给 HF/本地的，端口 8000）
cp "$SCRIPT_DIR/Dockerfile" "$work/Dockerfile"
cp "$SCRIPT_DIR/README.md"  "$work/README.md"

# 提醒：只看「已追踪但被修改」的文件（未追踪的临时产物本来就不该推），
# 若 deploy/modelscope 之外还有改动，git archive 取的是上次提交的版本
if [ -n "$(git status --porcelain --untracked-files=no -- . ':!deploy/modelscope')" ]; then
  echo "[提示] 检测到部署文件之外有已修改未提交的代码 —— 这些会以「上次提交」的版本推送，建议先 commit"
fi

echo "===== 待推送的创空间仓库内容（顶层） ====="
ls -la "$work"
echo "===== 目标创空间: ${MS_SPACE} ====="

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "[dry-run] 不执行推送"
  exit 0
fi

: "${MS_TOKEN:?需要 MS_TOKEN}"

# 3) 克隆创空间仓库 → 用组装好的内容整体覆盖 → 普通推送。
#    注意：不能全新 git init + force push —— 创空间创建时自带初始提交，
#    且 master 是保护分支，force push 会被 GitLab pre-receive 钩子拒绝。
#    在远端历史之上提交即可走普通推送。
repo="$(mktemp -d)"
if command -v cygpath >/dev/null 2>&1; then
  repo="$(cygpath -u "$repo")"
fi
git clone -q "https://oauth2:${MS_TOKEN}@www.modelscope.cn/studios/${MS_SPACE}.git" "$repo"
# 清空远端旧内容（保留 .git），再铺入我们组装的文件
find "$repo" -mindepth 1 -maxdepth 1 -not -name .git -exec rm -rf {} +
cp -r "$work"/. "$repo"/

cd "$repo"
git config user.name  "workbuddy-deploy"
git config user.email "deploy@local"
git add -A
if git diff --cached --quiet; then
  echo "[提示] 内容与远端一致，无需推送"
else
  git commit -qm "deploy: modelscope studio"
  git push origin HEAD
fi
rm -rf "$repo"

echo ""
echo "已推送到 https://www.modelscope.cn/studios/${MS_SPACE}"
echo "下一步：到创空间页面点「重新部署」，并在部署设置里确认"
echo "  ① 运行环境 = Docker   ② 云资源 = 免费 CPU   ③ 端口 = 7860"
