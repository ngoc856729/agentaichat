#!/usr/bin/env bash
set -euo pipefail

# Nếu truyền tham số, dùng đó làm tên file zip, 
# ngược lại tự sinh tên theo thời gian
OUTPUT="${1:-archive_$(date +%Y%m%d_%H%M%S).zip}"

echo "Đang nén tất cả file trong thư mục hiện tại vào: $OUTPUT"

# -r: đệ quy
# . : thư mục hiện tại
# -x: loại trừ chính file zip đầu ra (để tránh vòng lặp)
zip -r "$OUTPUT" . -x "$OUTPUT"

echo "Hoàn tất! File đã tạo: $OUTPUT"
