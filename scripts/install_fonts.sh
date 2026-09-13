#!/bin/bash
# install_fonts.sh - 安裝支援臺灣客語（擴展漢字）的字體
#
# 臺灣客語使用的漢字有些在 CJK 擴展區（Extension B/C/D/E/F），
# 一般字體不支援這些字符，會顯示為方塊（豆腐字）。

set -e

echo "================================================"
echo "安裝擴展漢字字體"
echo "================================================"
echo ""

# 檢查 brew 是否已安裝
if ! command -v brew &> /dev/null; then
    echo "錯誤：需要先安裝 Homebrew"
    echo ""
    echo "請執行："
    echo '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    exit 1
fi

echo "選擇要安裝的字體："
echo ""
echo "  1) 花園明朝 (HanaMin) - 支援最多漢字，適合臺灣客語"
echo "  2) 思源黑體 (Noto Sans CJK TC) - Google/Adobe 字體，較美觀"
echo "  3) 兩者都安裝"
echo ""
read -p "請輸入選項 [1/2/3，預設 1]: " choice
choice=${choice:-1}

install_hanamin() {
    echo ""
    echo "安裝花園明朝字體..."
    
    # 使用 Homebrew Cask 安裝
    if brew list --cask font-hanamin &> /dev/null; then
        echo "✓ 花園明朝已安裝"
    else
        brew install --cask font-hanamin
        echo "✓ 花園明朝安裝完成"
    fi
}

install_noto() {
    echo ""
    echo "安裝思源黑體..."
    
    if brew list --cask font-noto-sans-cjk-tc &> /dev/null; then
        echo "✓ 思源黑體已安裝"
    else
        brew install --cask font-noto-sans-cjk-tc
        echo "✓ 思源黑體安裝完成"
    fi
}

case $choice in
    1)
        install_hanamin
        FONT_NAME="HanaMinA"
        ;;
    2)
        install_noto
        FONT_NAME="Noto Sans CJK TC"
        ;;
    3)
        install_hanamin
        install_noto
        FONT_NAME="HanaMinA"
        ;;
    *)
        echo "無效的選項"
        exit 1
        ;;
esac

echo ""
echo "================================================"
echo "✓ 安裝完成！"
echo "================================================"
echo ""
echo "後續設定："
echo ""
echo "1. 終端機字體設定："
echo "   • iTerm2: Preferences → Profiles → Text → Font"
echo "   • Terminal.app: 偏好設定 → 描述檔 → 字體"
echo "   選擇 '$FONT_NAME'"
echo ""
echo "2. 字幕視窗使用此字體："
echo "   livestt --ui overlay --font-name '$FONT_NAME'"
echo ""
echo "3. 重新啟動終端機以套用新字體"
echo ""
