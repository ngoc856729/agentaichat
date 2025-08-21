
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import col, delete, func, select

from app import crud
from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
import base64
import shlex
import subprocess
from fastapi import WebSocket, WebSocketDisconnect
from deep_translator import GoogleTranslator
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
import subprocess
subprocess.run(['git clone https://github.com/ngoc856729/pdf-coffe.git'], capture_output=True, text=True, check=True)

# from app.models import (
#     Item,
#     Message,
#     UpdatePassword,
#     User,
#     UserCreate,
#     UserPublic,
#     UserRegister,
#     UsersPublic,
#     UserUpdate,
#     UserUpdateMe,
# )
from app.utils import generate_new_account_email, send_email

router = APIRouter(prefix="/users", tags=["users"])
import os
import json
from typing import Any, Dict, List
from pathlib import Path

# --- Các thư viện cần thiết từ LangChain và Pydantic ---
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import PydanticOutputParser
from langchain.memory import ConversationBufferWindowMemory, ChatMessageHistory
from langchain_core.messages import HumanMessage, AIMessage
from pydantic import BaseModel, Field

# --- MỚI: Các thư viện để xử lý PDF và ChromaDB ---
from langchain_community.document_loaders import PyPDFDirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings # Hoặc dùng một embedding khác như HuggingFaceEmbeddings
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain
import torch
from transformers import pipeline
from transformers.utils import is_flash_attn_2_available


from langchain_openai import OpenAI
llm = OpenAI(base_url="http://127.0.0.1:8080/v1",api_key="")

from langchain_community.embeddings import LlamaCppEmbeddings
try:
    embeddings = LlamaCppEmbeddings(model_path="nomic_embed_text.gguf")
except:
    cmd = "orca-cli download nomic-embed-text latest nomic_embed_textl.gguf ."
    embeddings = LlamaCppEmbeddings(model_path="nomic_embed_text.gguf")

    # Dùng shlex.split để tách argv đúng cách
    args = shlex.split(cmd)

    try:
        # chạy lệnh, bắt stdout/stderr, và ném CalledProcessError nếu exit code != 0
        result = subprocess.run(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True  # để output là str thay vì bytes
        )
        print("=== STDOUT ===")
        print(result.stdout)
        print("Download completed successfully.")
    except subprocess.CalledProcessError as e:
        # Nếu lệnh trả về exit code khác 0, sẽ vào đây
        print("=== STDERR ===")
        print(e.stderr)
        print(f"Command failed with exit code {e.returncode}")



# Xử lý khóa API một cách an toàn
if "GROQ_API_KEY" not in os.environ:
    raise ValueError("Lỗi: Vui lòng thiết lập biến môi trường GROQ_API_KEY.")

# <<< MỚI: Định nghĩa các thư mục >>>
MEMORY_DIR = Path("roasting_memory")
PDF_DIR = Path("pdf-coffe")
VECTORSTORE_DIR = Path("chroma_db")

# ==============================================================================
# PHẦN 1: SCHEMA JSON ĐẦU RA (Giữ nguyên)
# ==============================================================================

class CoffeeRoastingOutput(BaseModel):
    """Schema cho các hành động điều khiển máy rang."""
    air_flow: int = Field(description="Giá trị điều chỉnh lưu lượng gió mới (%).")
    drum_speed: int = Field(description="Giá trị điều chỉnh tốc độ trống quay mới (vòng/phút).")
    gas: int = Field(description="Giá trị điều chỉnh mức gas mới (%).")
    button_air: bool = Field(description="Trạng thái nút điều khiển gió (true/false).")
    button_drum: bool = Field(description="Trạng thái nút điều khiển trống (true/false).")
    button_burner: bool = Field(description="Trạng thái nút điều khiển đầu đốt (true/false).")
    button_charge: bool = Field(description="Trạng thái nút nạp cà phê (true/false).")
    button_drop: bool = Field(description="Trạng thái nút xả cà phê (true/false).")

# ==============================================================================
# PHẦN 2: LOGIC & PROMPTS
# ==============================================================================

# --- MỚI: Prompt được cập nhật để nhận thêm ngữ cảnh từ PDF ---
realtime_control_prompt_template = """
Bạn là "RoastMaster-GPT", một AI chuyên gia đang vận hành một mẻ rang.
Nhiệm vụ của bạn là phân tích dữ liệu cảm biến và quyết định các thông số điều khiển TỨC THỜI.
Bạn PHẢI trả lời bằng một đối tượng JSON theo đúng định dạng được yêu cầu.

## QUY TRÌNH TƯ DUY ##
1.  **Phân tích Yêu cầu Người dùng:** Phân tích sâu từng từ khóa trong yêu cầu (ví dụ: "Arabica Cầu Đất", "pour-over", "hương hoa", "chua thanh", "đậm đà", "cho phin").
2.  **Tra cứu Kiến thức (PDF Context):** Tìm kiếm trong cơ sở tri thức các kỹ thuật, nhiệt độ nạp, hoặc chiến lược năng lượng phù hợp với loại hạt, phương pháp pha và hồ sơ hương vị được yêu cầu.
3.  **Tham khảo Lịch sử (Planning History):** Kiểm tra các cài đặt thành công trước đây cho các yêu cầu tương tự để đảm bảo tính nhất quán và học hỏi.
4.  **Xây dựng Lý luận (Reasoning):** Trong trường `reasoning`, hãy giải thích rõ ràng cách bạn liên kết yêu cầu của người dùng với các thông số bạn chọn. Ví dụ: "Vì người dùng muốn 'hương hoa' cho Arabica, tôi chọn nhiệt độ nạp thấp hơn để kéo dài giai đoạn làm khô và Maillard, bảo toàn các hợp chất hương thơm dễ bay hơi...".
5.  **Tạo Cài đặt JSON:** Dựa trên lý luận của bạn, tạo ra đối tượng JSON cuối cùng.

## TRI THỨC CHUYÊN SÂU TỪ TÀI LIỆU (PDF) ##
Dưới đây là các thông tin liên quan trích xuất từ cơ sở tri thức của bạn. Hãy ưu tiên sử dụng chúng để đưa ra quyết định chuyên môn:
<context>
{context}
</context>

## TRI THỨC VẬN HÀNH CỐT LÕI (CORE ROASTING KNOWLEDGE) ##
Đây là các nguyên tắc VÀNG mà bạn phải tuân thủ để điều khiển mẻ rang. Mục tiêu tổng thể là tạo ra một đường cong Tốc độ Tăng nhiệt (Rate of Rise - RoR) mượt mà, giảm dần, giống như một chiếc máy bay đang hạ cánh, không phải một chiếc tàu lượn siêu tốc.

---
### 1. GIAI ĐOẠN SẤY (DRYING PHASE): Từ TP -> ~150°C BT
*   **Mục Tiêu:** Loại bỏ độ ẩm bên trong hạt một cách đồng đều và xây dựng đủ năng lượng (đà nhiệt) cho các giai đoạn tiếp theo.
*   **Chiến Lược:**
    *   **Gas:** Áp dụng mức gas cao ban đầu (80-100%) để nhanh chóng đưa nhiệt vào hệ thống và hạt cà phê.
    *   **Airflow:** Giữ airflow ở mức thấp (20-30%) để tối đa hóa việc truyền nhiệt và giữ năng lượng trong lồng rang.
*   **Rủi Ro Cần Tránh:**
    *   Năng lượng quá thấp: Gây ra 'stall' (RoR giảm về 0 hoặc âm) sau này trong giai đoạn Maillard.
    *   Năng lượng quá cao/không đều: Có thể gây cháy xém (scorching/tipping) bề mặt hạt.

---
### 2. GIAI ĐOẠN MAILLARD (MAILLARD REACTION): ~150°C -> ~205°C BT (Bắt đầu ngả vàng)
*   **Mục Tiêu:** Phát triển các hợp chất đường và axit amin, tạo ra tiền chất cho hương thơm và vị ngọt. Đây là giai đoạn quan trọng nhất để kiểm soát "đà" của mẻ rang.
*   **Chiến Lược:**
    *   **Gas:** Bắt đầu giảm gas một cách CHỦ ĐỘNG và theo từng bước (ví dụ: giảm 10-15% tại 160°C, giảm thêm 10% tại 180°C). Đừng chờ RoR giảm rồi mới phản ứng. Mục tiêu là lái đường cong RoR giảm dần một cách mượt mà.
    *   **Airflow:** Tăng dần airflow (lên 40-60%) để giúp loại bỏ hơi nước và bắt đầu chuẩn bị loại bỏ vỏ lụa (chaff), giúp hương vị sạch hơn.
*   **Rủi Ro Cần Tránh:**
    *   **"RoR Crash"**: Giảm gas quá muộn hoặc quá đột ngột, khiến RoR giảm sâu trước khi vào Tiếng Nổ Đầu Tiên. Điều này gây ra hương vị "baked" (nhạt nhẽo, vị như bánh mì).

---
### 3. TIẾNG NỔ ĐẦU TIÊN (FIRST CRACK - FC): Bắt đầu khoảng ~205°C BT
*   **Mục Tiêu:** Quản lý an toàn phản ứng tỏa nhiệt mạnh mẽ của hạt cà phê. Đây là một sự kiện mang tính quyết định, cần hành động dứt khoát.
*   **Chiến Lược:**
    *   **Gas:** NGAY KHI nghe thấy tiếng nổ đầu tiên, PHẢI giảm gas một cách DỨT KHOÁT và ĐÁNG KỂ (xuống mức rất thấp, ví dụ 20-35%). Việc này để hấp thụ năng lượng tỏa ra từ hạt và tránh RoR tăng vọt mất kiểm soát.
    *   **Airflow:** Tăng mạnh airflow (lên 70-90%) để nhanh chóng loại bỏ lượng lớn khói và vỏ lụa được giải phóng, đảm bảo hương vị sạch và rõ ràng.
*   **Rủi Ro Cần Tránh:**
    *   **"Flick"**: Không giảm gas đủ nhanh/đủ nhiều, khiến RoR tăng vọt lên trong giây lát do phản ứng tỏa nhiệt. Điều này gây ra các nốt hương cháy, khét, hoặc vị rỗng (hollow).

---
### 4. GIAI ĐOẠN PHÁT TRIỂN (DEVELOPMENT PHASE): Từ khi bắt đầu FC -> Kết thúc rang
*   **Mục Tiêu:** Tinh chỉnh hương vị cuối cùng. Thời gian trong giai đoạn này (Development Time) quyết định sự cân bằng giữa độ chua (acidity), độ ngọt (sweetness), và độ đậm đà (body).
*   **Chiến Lược:**
    *   **RoR Control:** RoR PHẢI LUÔN trong xu hướng giảm dần. Không bao giờ để RoR đi ngang hoặc tăng lên trong giai đoạn này.
    *   **Gas:** Sử dụng các điều chỉnh gas CỰC NHỎ (thay đổi +/- 5%) để "lái" đường cong RoR theo quỹ đạo mong muốn. Mỗi thay đổi nhỏ đều có tác động lớn đến hương vị cuối cùng.
    *   **Development Time Ratio (DTR):** Tỷ lệ thời gian phát triển so với tổng thời gian rang sẽ quyết định phong cách rang:
        *   **Light Roast (Pour-over, hương hoa/trái cây):** DTR ngắn (15-18%). Kết thúc rang khi RoR vẫn còn dương đáng kể.
        *   **Medium Roast (Cân bằng, ngọt ngào):** DTR trung bình (18-22%). Kết thúc rang khi RoR tiến gần đến 0.
        *   **Dark Roast (Đậm đà, chocolatey):** DTR dài (>22%). Có thể kết thúc rang khi RoR đã bằng 0 trong một khoảng thời gian ngắn.
*   **Rủi Ro Cần Tránh:**
    *   RoR tăng trở lại: Gây ra vị cháy, khét.
    *   Kéo dài giai đoạn này với RoR quá thấp: Gây ra vị "baked".

## LỊCH SỬ MẺ RANG ##
{chat_history}

## QUAN SÁT HIỆN TẠI ##
{input}

## YÊU CẦU ĐỊNH DẠNG ĐẦU RA ##
{format_instructions}
"""

initial_settings_prompt_template = """
Bạn là "RoastInitiator-GPT", một AI chuyên gia trong việc thiết lập một mẻ rang cà phê từ mô tả.
Nhiệm vụ của bạn là nhận một mô tả yêu cầu từ người dùng và quyết định các thông số CÀI ĐẶT BAN ĐẦU.
Hành động cuối cùng của bạn phải là một đối tượng JSON duy nhất để khởi động mẻ rang.

## QUY TRÌNH TƯ DUY ##
1.  **Phân tích Yêu cầu Người dùng:** Phân tích sâu từng từ khóa trong yêu cầu (ví dụ: "Arabica Cầu Đất", "pour-over", "hương hoa", "chua thanh", "đậm đà", "cho phin").
2.  **Tra cứu Kiến thức (PDF Context):** Tìm kiếm trong cơ sở tri thức các kỹ thuật, nhiệt độ nạp, hoặc chiến lược năng lượng phù hợp với loại hạt, phương pháp pha và hồ sơ hương vị được yêu cầu.
3.  **Tham khảo Lịch sử (Planning History):** Kiểm tra các cài đặt thành công trước đây cho các yêu cầu tương tự để đảm bảo tính nhất quán và học hỏi.
4.  **Xây dựng Lý luận (Reasoning):** Trong trường `reasoning`, hãy giải thích rõ ràng cách bạn liên kết yêu cầu của người dùng với các thông số bạn chọn. Ví dụ: "Vì người dùng muốn 'hương hoa' cho Arabica, tôi chọn nhiệt độ nạp thấp hơn để kéo dài giai đoạn làm khô và Maillard, bảo toàn các hợp chất hương thơm dễ bay hơi...".
5.  **Tạo Cài đặt JSON:** Dựa trên lý luận của bạn, tạo ra đối tượng JSON cuối cùng.

## TRI THỨC CHUYÊN SÂU TỪ TÀI LIỆU (PDF) ##
Dựa vào những kiến thức chuyên sâu sau đây để đưa ra đề xuất tốt nhất:
<context>
{context}
</context>

## NGUYÊN TẮC THIẾT LẬP BAN ĐẦU (INITIAL CHARGE PROTOCOLS) ##
Đây là nền tảng của toàn bộ mẻ rang. Quyết định của bạn ở đây sẽ thiết lập "quỹ đạo năng lượng" cho cả quá trình. Một khởi đầu sai lầm rất khó để sửa chữa. Hãy phân tích cẩn thận dựa trên các yếu tố sau:

---
### 1. PHÂN TÍCH YẾU TỐ ĐẦU VÀO (INPUT ANALYSIS)

#### A. Đặc tính Hạt Cà Phê (Green Bean Characteristics):
Đây là yếu tố quan trọng nhất. Hạt cà phê không giống nhau.

*   **Mật độ (Density):**
    *   **Hạt Cứng/Mật độ cao (Hard Bean - trồng ở nơi cao, vd: Ethiopia, Kenya, Arabica Cầu Đất):** Cần nhiều năng lượng hơn để nhiệt xuyên vào lõi.
        *   **Chiến lược:** Nhiệt độ nạp (Charge Temp) cao hơn và/hoặc Gas ban đầu cao hơn.
    *   **Hạt Mềm/Mật độ thấp (Soft Bean - trồng ở nơi thấp):** Ít kháng nhiệt hơn, dễ bị cháy xém (scorching/tipping).
        *   **Chiến lược:** Nhiệt độ nạp thấp hơn để có một khởi đầu nhẹ nhàng.

*   **Phương pháp Sơ chế (Processing Method):**
    *   **Sơ chế Ướt (Washed):** Hạt sạch, ít đường trên bề mặt. Có thể chịu được nhiệt độ nạp cao hơn một chút.
        *   **Mục tiêu:** Làm nổi bật độ chua (acidity) và hương vị nguyên bản.
    *   **Sơ chế Tự nhiên/Khô (Natural/Dry):** Lớp đường quả khô lại trên bề mặt hạt. Rất dễ bị cháy xém nếu năng lượng ban đầu quá cao.
        *   **Chiến lược:** Nhiệt độ nạp thấp hơn đáng kể để tránh làm cháy lớp đường này ngay từ đầu.
    *   **Sơ chế Mật ong (Honey/Pulped Natural):** Nằm giữa Washed và Natural. Cần sự cân bằng, nhiệt độ nạp vừa phải.

*   **Độ ẩm (Moisture Content):**
    *   **Độ ẩm cao (>11.5%):** Cần nhiều năng lượng hơn ở giai đoạn đầu để làm bay hơi nước.
        *   **Chiến lược:** Cân nhắc tăng nhẹ nhiệt độ nạp hoặc gas ban đầu.
    *   **Độ ẩm thấp (<10%):** Hạt khô hơn, dễ hấp thụ nhiệt hơn và có nguy cơ bị rang quá nhanh.
        *   **Chiến lược:** Giảm nhiệt độ nạp để kiểm soát tốt hơn.

#### B. Hồ sơ Hương vị Mong muốn (Desired Flavor Profile):
Diễn giải yêu cầu của người dùng thành mục tiêu vật lý.

*   **"Hương hoa, Vị chua trái cây" (Floral, Acidic, Fruity):**
    *   **Mục tiêu vật lý:** Bảo toàn các axit hữu cơ và hợp chất thơm dễ bay hơi.
    *   **Chiến lược:** Kéo dài giai đoạn Maillard bằng cách sử dụng nhiệt độ nạp thấp hơn. Một khởi đầu nhẹ nhàng sẽ không "đốt cháy" những hương vị tinh tế này.
*   **"Ngọt ngào, Cân bằng, Body tốt" (Sweet, Balanced, Good Body):**
    *   **Mục tiêu vật lý:** Thúc đẩy phản ứng Caramel hóa một cách tối ưu.
    *   **Chiến lược:** Cần một cú hích năng lượng ban đầu đủ mạnh để xây dựng đà. Nhiệt độ nạp ở mức trung bình đến cao.
*   **"Đậm đà, Chocolate, Ít chua" (Bold, Chocolatey, Low Acidity):**
    *   **Mục tiêu vật lý:** Phát triển sâu các phản ứng Maillard và Caramel hóa, phá vỡ cấu trúc sợi cellulose.
    *   **Chiến lược:** Cần năng lượng ban đầu rất lớn. Nhiệt độ nạp cao và gas ở mức cao nhất.

---
### 2. BẢNG THAM CHIẾU CHIẾN LƯỢC NẠP (CHARGE STRATEGY REFERENCE)

| Hồ sơ Mục tiêu             | Loại hạt/Sơ chế điển hình                               | Nhiệt độ Nạp Đề xuất (BT) | Gas Ban đầu (%) | Lý do Chiến lược                                                                    |
| -------------------------- | -------------------------------------------------------- | --------------------------- | ---------------- | ----------------------------------------------------------------------------------- |
| **Light & Bright**         | Arabica Washed, mật độ cao (Kenya, Ethiopia)             | Thấp (195-205°C)            | 75-85%           | Bảo toàn hương thơm tinh tế, axit hữu cơ. Tránh "sốc nhiệt" cho hạt.               |
| **Sweet & Balanced**       | Arabica Honey/Natural (Brazil, C. Rica)                  | Trung bình (205-215°C)      | 85-95%           | Đủ năng lượng để thúc đẩy caramel hóa mà không làm cháy đường tự nhiên trên bề mặt. |
| **Rich & Bold**            | Robusta, hoặc Arabica Natural/Monsoon (India, Indo)      | Cao (215-225°C)             | 95-100%          | Cần năng lượng cực lớn để phá vỡ cấu trúc hạt dày đặc và phát triển vị đậm.       |

---
### 3. RÀNG BUỘC HỆ THỐNG (SYSTEM CONSTRAINTS)
Bất kể chiến lược nào, các thông số sau phải được tuân thủ tại thời điểm nạp cà phê:

-   `button_charge`: **PHẢI** là `true` (Đây là hành động chính).
-   `button_burner`: **PHẢI** là `true` (Đầu đốt phải đang hoạt động để cung cấp năng lượng).
-   `button_air`: **PHẢI** là `true` (Luồng gió phải bật, dù ở mức thấp, để đảm bảo lưu thông).
-   `button_drum`: **PHẢI** là `true` (Trống phải quay để đảo đều hạt).
-   `button_drop`: **PHẢI** là `false` (Không thể vừa nạp vừa xả).

## CÁC VÍ DỤ TRONG QUÁ KHỨ ##
Đây là những yêu cầu bạn đã xử lý trước đây. Hãy dùng chúng để học hỏi và giữ sự nhất quán:
{planning_history}

## YÊU CẦU HIỆN TẠI CỦA NGƯỜI DÙNG ##
{input}

## YÊU CẦU ĐỊNH DẠNG ĐẦU RA ##
Dựa vào phân tích của bạn, hãy tạo một đối tượng JSON duy nhất chứa lệnh điều khiển để BẮT ĐẦU mẻ rang.
{format_instructions}
"""

# --- MỚI: Logic tạo và tải Vector Store ---
def load_or_create_vector_store(pdf_folder: Path, vectorstore_folder: Path) -> Chroma:
    """Tải ChromaDB từ đĩa nếu có, nếu không thì tạo mới từ các file PDF."""
    # Chọn model embedding. Ollama là một lựa chọn tốt để chạy local.
    # Đảm bảo bạn đã cài đặt và chạy Ollama với một model (ví dụ: `ollama run mxbai-embed-large`)
    # embeddings = OllamaEmbeddings(model="mxbai-embed-large")

    if vectorstore_folder.exists():
        print(f"[VectorStore] Đang tải ChromaDB từ: {vectorstore_folder}")
        return Chroma(persist_directory=str(vectorstore_folder), embedding_function=embeddings)
    else:
        print(f"[VectorStore] Không tìm thấy DB, đang tạo mới từ các PDF trong: {pdf_folder}")
        if not pdf_folder.exists() or not any(pdf_folder.iterdir()):
             raise FileNotFoundError(f"Thư mục PDF '{pdf_folder}' không tồn tại hoặc trống.")

        # Tải tất cả file PDF
        loader = PyPDFDirectoryLoader(str(pdf_folder))
        docs = loader.load()

        # Chia nhỏ tài liệu
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)

        print(f"[VectorStore] Đã chia {len(docs)} tài liệu thành {len(splits)} đoạn. Bắt đầu tạo vector...")
        # Tạo và lưu vector store
        vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=embeddings,
            persist_directory=str(vectorstore_folder)
        )
        print(f"[VectorStore] Đã tạo và lưu ChromaDB thành công vào: {vectorstore_folder}")
        return vectorstore

# --- Logic cho Use Case 1 (Điều khiển thời gian thực) ---
SESSIONS: Dict[str, Any] = {}

def save_session_memory(session_id: str, memory: ConversationBufferWindowMemory):
    # (Giữ nguyên như cũ)
    memory_file = MEMORY_DIR / f"{session_id}.json"
    messages = [msg.dict() for msg in memory.chat_memory.messages]
    with open(memory_file, 'w', encoding='utf-8') as f:
        json.dump(messages, f, ensure_ascii=False, indent=4)
    print(f"[Memory] Đã lưu bộ nhớ cho session '{session_id}' vào tệp.")

def load_session_memory(session_id: str) -> ChatMessageHistory:
    # (Giữ nguyên như cũ)
    memory_file = MEMORY_DIR / f"{session_id}.json"
    if not memory_file.exists():
        return ChatMessageHistory()
    with open(memory_file, 'r', encoding='utf-8') as f:
        messages_data = json.load(f)
    messages = [HumanMessage(**msg['data']) if msg.get('type') == 'human' else AIMessage(**msg['data']) for msg in messages_data]
    print(f"[Memory] Đã tải bộ nhớ từ tệp cho session '{session_id}'.")
    return ChatMessageHistory(messages=messages)


def create_realtime_control_chain(session_id: str, vectorstore: Chroma):
    # llm = ChatGroq(model="llama3-70b-8192", temperature=0)
    parser = PydanticOutputParser(pydantic_object=CoffeeRoastingOutput)

    # Cập nhật prompt để nhận cả `input`, `chat_history` và `context` từ PDF
    prompt = PromptTemplate(
        template=realtime_control_prompt_template,
        input_variables=["input", "chat_history", "context"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    # Chain để nhồi context từ PDF vào prompt
    document_chain = create_stuff_documents_chain(llm, prompt)
    
    # Tải bộ nhớ từ file hoặc tạo mới
    chat_history = load_session_memory(session_id)
    memory = ConversationBufferWindowMemory(k=20, memory_key="chat_history", input_key="input", chat_memory=chat_history, return_messages=True)
    
    # Tạo retriever để tìm kiếm trong PDF
    retriever = vectorstore.as_retriever(search_kwargs={"k": 3}) # Tìm 3 kết quả liên quan nhất

    # Chain tổng hợp: Lấy lịch sử, tìm kiếm PDF, sau đó gọi LLM
    retrieval_chain = create_retrieval_chain(retriever, document_chain)

    def invoke_chain_with_memory(input_data):
        input_str = ", ".join([f"{key}: {value}" for key, value in input_data.items()])
        
        # Lấy lịch sử hội thoại cho lần gọi này
        memory_variables = memory.load_memory_variables({})
        
        # Gọi retrieval chain với đầy đủ thông tin
        response = retrieval_chain.invoke({
            "input": input_str,
            "chat_history": memory_variables['chat_history']
        })
        
        # Trích xuất và phân tích kết quả JSON
        ai_response_str = response['answer']
        pydantic_output = parser.parse(ai_response_str)
        
        # Lưu lại ngữ cảnh vào bộ nhớ
        memory.save_context({"input": input_str}, {"output": json.dumps(pydantic_output.model_dump())})
        save_session_memory(session_id, memory)
        
        return pydantic_output
        
    return invoke_chain_with_memory


def get_or_create_session(session_id: str, vectorstore: Chroma):
    if session_id not in SESSIONS:
        print(f"--- Đang tạo/tải session MỚI với ID: {session_id} ---")
        SESSIONS[session_id] = create_realtime_control_chain(session_id, vectorstore)
    return SESSIONS[session_id]

def run_roasting_step(session_id: str, sensor_data: Dict[str, Any], vectorstore: Chroma) -> str:
    roasting_chain = get_or_create_session(session_id, vectorstore)
    pydantic_output = roasting_chain(sensor_data)
    return pydantic_output.model_dump_json(indent=4)

# --- Logic cho Use Case 2 (Tạo cài đặt ban đầu) ---
PLANNING_HISTORY_FILE = MEMORY_DIR / "planning_history.json"

def load_planning_history() -> List[Dict]:
    # (Giữ nguyên như cũ)
    if not PLANNING_HISTORY_FILE.exists():
        return []
    with open(PLANNING_HISTORY_FILE, 'r', encoding='utf-8') as f:
        print("[Memory] Đã tải lịch sử các cài đặt đã tạo.")
        return json.load(f)

def save_planning_history(history: List[Dict]):
    # (Giữ nguyên như cũ)
    with open(PLANNING_HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, ensure_ascii=False, indent=4)
        print("[Memory] Đã cập nhật lịch sử cài đặt.")

def generate_initial_settings_from_description(description: str, vectorstore: Chroma) -> str:
    print("--- Đang tạo cài đặt ban đầu từ mô tả... ---")
    # llm = ChatGroq(model="llama3-70b-8192", temperature=0.2)

    parser = PydanticOutputParser(pydantic_object=CoffeeRoastingOutput)
    
    # Tải lịch sử và định dạng nó cho prompt
    history = load_planning_history()
    history_str = "\n".join([f"- Yêu cầu: \"{item['request']}\" -> Cài đặt: {item['settings']}" for item in history])
    if not history_str:
        history_str = "Chưa có ví dụ nào."

    # Cập nhật prompt để nhận context từ PDF
    prompt = PromptTemplate(
        template=initial_settings_prompt_template,
        input_variables=["input", "planning_history", "context"],
        partial_variables={"format_instructions": parser.get_format_instructions()}
    )
    
    # Tạo chain với khả năng tra cứu PDF
    document_chain = create_stuff_documents_chain(llm, prompt)
    retriever = vectorstore.as_retriever(search_kwargs={"k": 5}) # Tìm 5 kết quả liên quan
    retrieval_chain = create_retrieval_chain(retriever, document_chain)
    
    # Gọi chain
    response = retrieval_chain.invoke({
        "input": description,
        "planning_history": history_str
    })
    
    # Phân tích kết quả
    ai_response_str = response['answer']
    settings_output = parser.parse(ai_response_str)
    settings_dict = settings_output.model_dump()
    
    # Cập nhật và lưu lại lịch sử
    history.append({"request": description, "settings": settings_dict})
    save_planning_history(history)
    
    return json.dumps(settings_dict, indent=4, ensure_ascii=False)
    # Đảm bảo các thư mục cần thiết tồn tại
MEMORY_DIR.mkdir(exist_ok=True)
PDF_DIR.mkdir(exist_ok=True)
VECTORSTORE_DIR.mkdir(exist_ok=True)

# Lời nhắc: Thêm file PDF vào thư mục 'pdf_knowledge_base'
if not any(PDF_DIR.glob("*.pdf")):
    print("*"*70)
    print(f"!!! CẢNH BÁO: Thư mục '{PDF_DIR}' đang trống.")
    print("!!! Vui lòng thêm các file PDF chứa kiến thức rang cà phê vào đó.")
    print("*"*70)
    
# Tải hoặc tạo Vector Store từ PDF
vector_store = load_or_create_vector_store(PDF_DIR, VECTORSTORE_DIR)

def base64_to_audio(base64_str: str, output_path: str):
    """
    Chuyển chuỗi Base64 thành file âm thanh.

    Args:
      base64_str (str): Chuỗi Base64 (có thể bao gồm tiền tố "data:audio/xxx;base64,").
      output_path (str): Đường dẫn file đầu ra, ví dụ "output.mp3" hoặc "output.wav".
    """
    # Nếu có tiền tố dạng data URI, loại bỏ phần trước dấu phẩy
    if "," in base64_str:
        base64_str = base64_str.split(",", 1)[1]

    # Giải mã Base64
    audio_bytes = base64.b64decode(base64_str)

    # Ghi vào file
    with open(output_path, "wb") as f:
        f.write(audio_bytes)
    print(f"Đã tạo file âm thanh: {output_path}")

def chat_agent_audio(base_64_string):
     TEMP_FILE= "temp_file.wav"
     base64_to_audio(base_64_string, TEMP_FILE)
     pipe = pipeline(
            "automatic-speech-recognition",
            model="openai/whisper-large-v3", # select checkpoint from https://huggingface.co/openai/whisper-large-v3#model-details
            torch_dtype=torch.float16,
            device="cuda:0", # or mps for Mac devices
            model_kwargs={"attn_implementation": "flash_attention_2"} if is_flash_attn_2_available() else {"attn_implementation": "sdpa"},
        )

     outputs = pipe(
            TEMP_FILE,
            chunk_length_s=30,
            batch_size=24,
            return_timestamps=True,
        )
     translated = GoogleTranslator(source='auto', target='de').translate(outputs)  # output -> Weiter so, du bist großartig
     user_request_B = translated
     print(f"\nYêu cầu của người dùng:\n\"{user_request_B}\"")
     # Truyền vector_store vào hàm
     initial_settings_json = generate_initial_settings_from_description(user_request_B, vector_store)
     print("\n--- CÀI ĐẶT BAN ĐẦU ĐỀ XUẤT (OUTPUT JSON) ---")
     print(initial_settings_json)
     os.remove(TEMP_FILE)
     k= str(initial_settings_json)
     return k

def chat_agent_text(text):
     session_id_A = "batch_realtime_A"
     print(f"\nChạy lần đầu hoặc tiếp tục mẻ rang '{session_id_A}'...")
     
     data = json.loads(text)
     sensor_data_A1 = data
     # Truyền vector_store vào hàm
     json_output_A1 = run_roasting_step(session_id_A, sensor_data_A1, vector_store)
     print("\n--- OUTPUT JSON CHO BƯỚC 1 ---")
     print(json_output_A1)
     k= str(json_output_A1)
     return k

@router.websocket("/ws/audio_echo",dependencies=[Depends(get_current_active_superuser)])
async def websocket_audio_echo_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected to Audio Echo WebSocket.")
    try:
        while True:
            b64_audio_string = await websocket.receive_text()
            try:
                output= chat_agent_audio(b64_audio_string)
                await websocket.send_text(output)
                print("Audio Echo: Sent echoed audio back to client.")
            except Exception as e:
                print(f"Audio Echo: Base64 decoding error: {e}")
                continue
    except WebSocketDisconnect:
        print("Audio Echo client disconnected.")


@router.websocket("/ws/echo")
async def websocket_echo_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Client connected to Echo WebSocket.")
    try:
        while True:
            data = await websocket.receive_text()

            chat_agent_text(data)
            await websocket.send_text(f"{data}")
    except WebSocketDisconnect:
        print("Echo client disconnected.")





# ==============================================================================
# PHẦN 3: MÔ PHỎNG SỬ DỤNG
# ==============================================================================

# if __name__ == "__main__":
#     # Đảm bảo các thư mục cần thiết tồn tại
#     MEMORY_DIR.mkdir(exist_ok=True)
#     PDF_DIR.mkdir(exist_ok=True)
#     VECTORSTORE_DIR.mkdir(exist_ok=True)

#     # Lời nhắc: Thêm file PDF vào thư mục 'pdf_knowledge_base'
#     if not any(PDF_DIR.glob("*.pdf")):
#         print("*"*70)
#         print(f"!!! CẢNH BÁO: Thư mục '{PDF_DIR}' đang trống.")
#         print("!!! Vui lòng thêm các file PDF chứa kiến thức rang cà phê vào đó.")
#         print("*"*70)
        
#     # Tải hoặc tạo Vector Store từ PDF
#     vector_store = load_or_create_vector_store(PDF_DIR, VECTORSTORE_DIR)

#     print(f"\n{'#'*60}\n# TRƯỜNG HỢP SỬ DỤNG 1: ĐIỀU KHIỂN RANG THEO THỜI GIAN THỰC #\n{'#'*60}")
    
#     session_id_A = "batch_realtime_A"
#     print(f"\nChạy lần đầu hoặc tiếp tục mẻ rang '{session_id_A}'...")
#     sensor_data_A1 = {"et": 200.0, "bt": 198.0, "ct": 215.0, "air_flow": 50, "drum_speed": 75, "gas": 85}
#     # Truyền vector_store vào hàm
#     json_output_A1 = run_roasting_step(session_id_A, sensor_data_A1, vector_store)
#     print("\n--- OUTPUT JSON CHO BƯỚC 1 ---")
#     print(json_output_A1)
    
#     print(f"\n{'#'*60}\n# TRƯỜNG HỢP SỬ DỤNG 2: TẠO CÀI ĐẶT BAN ĐẦU TỪ MÔ TẢ #\n{'#'*60}")
    
#     user_request_B = "Tôi cần rang 1 mẻ Arabica Cầu Đất cho pour-over. Tôi muốn làm nổi bật hương hoa và vị chua nhẹ của trái cây."
#     print(f"\nYêu cầu của người dùng:\n\"{user_request_B}\"")
#     # Truyền vector_store vào hàm
#     initial_settings_json = generate_initial_settings_from_description(user_request_B, vector_store)
#     print("\n--- CÀI ĐẶT BAN ĐẦU ĐỀ XUẤT (OUTPUT JSON) ---")
#     print(initial_settings_json)
    
#     # Thêm một yêu cầu nữa để thấy AI học từ lịch sử
#     print("\n--- Yêu cầu thứ hai để kiểm tra bộ nhớ dài hạn ---")
#     user_request_C = "Lần này rang Robusta cho phin, cần đậm đà, không chua."
#     print(f"\nYêu cầu của người dùng:\n\"{user_request_C}\"")
#     # Truyền vector_store vào hàm
#     initial_settings_json_2 = generate_initial_settings_from_description(user_request_C, vector_store)
#     print("\n--- CÀI ĐẶT BAN ĐẦU ĐỀ XUẤT (OUTPUT JSON) ---")
#     print(initial_settings_json_2)
#     print("--------------------------------------------\n")

# @router.get(
#     "/",
#     dependencies=[Depends(get_current_active_superuser)],
#     response_model=UsersPublic,
# )
# def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
#     """
#     Retrieve users.
#     """

#     count_statement = select(func.count()).select_from(User)
#     count = session.exec(count_statement).one()

#     statement = select(User).offset(skip).limit(limit)
#     users = session.exec(statement).all()

#     return UsersPublic(data=users, count=count)



