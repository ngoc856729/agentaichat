# Sử dụng image cơ bản Python
FROM python:3.10-slim

# Thiết lập working directory
WORKDIR /app

# Cài đặt thư viện hệ thống (nếu cần)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
    && rm -rf /var/lib/apt/lists/*

# Cài đặt llama-server
RUN pip install --no-cache-dir llama-server

# Tạo thư mục chứa mô hình
RUN mkdir -p /models

# Mô tả volume để mount thư mục chứa file .gguf
VOLUME ["/models"]

# Expose cổng
EXPOSE 8080

# Thiết lập biến môi trường (nếu muốn thay đổi dễ dàng)
ENV MODEL_PATH=/models/mistral.gguf \
    CONTEXT_SIZE=1024 \
    WORLD_SIZE=2 \
    RANK=0 \
    MASTER_ADDR=192.168.1.2 \
    NEXT_ADDR=192.168.1.3 \
    HOST=0.0.0.0 \
    PORT=8080

# Entry point
ENTRYPOINT ["llama-server"]
CMD [
  "-m", "${MODEL_PATH}",
  "-c", "${CONTEXT_SIZE}",
  "--world", "${WORLD_SIZE}",
  "--rank", "${RANK}",
  "--master", "${MASTER_ADDR}",
  "--next", "${NEXT_ADDR}",
  "--prefetch",
  "--host", "${HOST}",
  "--port", "${PORT}"
]