# client.py - FULLY CORRECTED CODE
import asyncio
import websockets
import base64
import os

SERVER_URL = "ws://localhost:8000"

async def chat_audio_endpoint(input_filename="sound.wav"):
    """Mã hóa file audio sang Base64, gửi đi, nhận lại, và lưu kết quả."""
    uri = f"{SERVER_URL}/ws/audio_echo"
    output_filename = f"echoed_{input_filename}"
    print("\n--- [START] Testing Base64 Audio Echo Endpoint ---")
    if not os.path.exists(input_filename):
        print(f"Error: Input file '{input_filename}' not found.")
        print("--- [FAIL] Audio Echo Test ---\n")
        return
    try:
        with open(input_filename, "rb") as f: audio_bytes = f.read()
        b64_string = base64.b64encode(audio_bytes).decode('utf-8')
        print(f"Client: Read {len(audio_bytes)} bytes from '{input_filename}'.")
        async with websockets.connect(uri) as websocket:
            print("Client: Sending Base64 audio to server...")
            await websocket.send(b64_string)
            response_b64_string = await websocket.recv()
            print(f"Client: Received Base64 response.")
            response_bytes = base64.b64decode(response_b64_string)
            with open(output_filename, "wb") as f: f.write(response_bytes)
            print(f"Success! Echoed audio saved to '{output_filename}'")
            print("--- [SUCCESS] Audio Echo Test ---\n")
            return output_filename
    except Exception as e:
        print(f"Audio Echo Test Failed: {e}")

async def chat_text_endpoint(message):
    """Gửi một tin nhắn và nhận lại phản hồi."""
    uri = f"{SERVER_URL}/ws/echo"
    print("\n--- [START] Testing Echo Endpoint ---")
    try:
        async with websockets.connect(uri) as websocket:
            msg = message
            await websocket.send(msg)
            response = await websocket.recv()
            print(f"Client Sent: '{msg}' | Server Responded: '{response}'")
            print("--- [SUCCESS] Echo Test ---\n")
            return response
    except Exception as e:
        print(f"Echo Test Failed: {e}")

async def main():
    """Hàm chính để chạy tất cả các bài test."""
    print("==============================================")
    print("     STARTING WEBSOCKET CLIENT TESTS")
    print("==============================================")
    
    await chat_audio_endpoint(input_filename="sound.wav")
    await chat_text_endpoint("Chào buổi sáng Việt Nam")

    
    print("==============================================")
    print("           ALL TESTS COMPLETED")
    print("==============================================")

if __name__ == "__main__":
    asyncio.run(main())