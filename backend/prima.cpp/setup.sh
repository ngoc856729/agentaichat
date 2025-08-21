cd models && orca-cli download mistral-small3.2 latest mistral.gguf .
docker build -t llama-server:latest .
docker run -d --name llama-server -v models:/models lama-server:latest --network default
