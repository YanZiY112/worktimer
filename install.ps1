# Licensed under the MIT license
# <LICENSE-MIT or https://opensource.org/licenses/MIT>, at your
# option. This file may not be copied, modified, or distributed
# except according to those terms.

# 安装脚本 for 时间提醒助手
# 用于安装必要的Python依赖和准备运行环境

Write-Host "=== 时间提醒助手安装脚本 ===" -ForegroundColor Cyan
Write-Host "正在检查Python环境..."

# 检查Python是否已安装
try {
    $pythonVersion = python --version
    Write-Host "✓ 已发现Python: $pythonVersion" -ForegroundColor Green
}
catch {
    Write-Host "✗ 未找到Python，请安装Python 3.7+后重试" -ForegroundColor Red
    exit
}

# 检查pip是否可用
try {
    $pipVersion = pip --version
    Write-Host "✓ 已发现pip: $pipVersion" -ForegroundColor Green
}
catch {
    Write-Host "✗ 未找到pip，请确保pip已安装" -ForegroundColor Red
    exit
}

Write-Host "正在安装所需依赖..."

# 安装必要的依赖包
pip install pygame pillow

# 确保sounds文件夹存在
if (-Not (Test-Path -Path ".\sounds")) {
    Write-Host "创建sounds文件夹..."
    New-Item -ItemType Directory -Path ".\sounds"
}

# 检查声音文件
$soundFiles = @(
    ".\sounds\reminder.wav",
    ".\sounds\start.mp3",
    ".\sounds\stop.mp3"
)

foreach ($file in $soundFiles) {
    if (-Not (Test-Path -Path $file)) {
        Write-Host "警告: 未找到声音文件 $file" -ForegroundColor Yellow
    }
}

Write-Host "`n安装完成!" -ForegroundColor Green
Write-Host "----------------------------"
Write-Host "运行方法: python time_reminder_wrapper.py"
Write-Host "或双击time_reminder_wrapper.py文件启动程序"
Write-Host "`n这个包装器脚本会自动修复原始程序中的问题并运行。"
Write-Host "`n如果程序启动有问题，请参考README.md中的说明。" -ForegroundColor Cyan
