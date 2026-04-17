# 🖼️ Thumbnail Builder Pro

Web app Streamlit chuyên nghiệp để tạo thumbnail sản phẩm **600×600** hàng loạt từ file Excel + ảnh.

## ✨ Tính năng chính

- 📥 **Import Excel/CSV** (cột: `id`, `text1`, `text2`) + upload nhiều ảnh cùng lúc
- 🎯 **Tự khớp ảnh với id** qua tên file (VD: `SP001.png` khớp với `id=SP001`)
- 📐 **Smart-fit ảnh** về 600×600 — không méo, không mất chi tiết, không vỡ góc
- 🎯 **Căn giữa theo centroid** — sản phẩm bất đối xứng (chảo có cán, ấm...) vẫn cân hoàn hảo
- 🔍 **Zoom thủ công** — tinh chỉnh kích thước sản phẩm trong khung (0.5-1.3x)
- ✒️ **Text auto co giãn** — text ngắn giữ 20.4px (Montserrat), text dài tự shrink vừa pill
- 🎨 **Pill shadow đẹp** — vẽ bằng code, 2 pill ở góc trên trái không đè sản phẩm
- 🪄 **Tách nền trắng** tuỳ chọn (flood-fill, không cần AI)
- 👁️ **Preview grid live** — mọi chỉnh sửa ở sidebar thấy ngay
- 📦 **Xuất ZIP** + `cms.csv` + `cms.xlsx` sẵn sàng nạp CMS
- 🔐 **Username + Password** qua `st.secrets` — source public cũng không lộ
- 🎨 **UI tối ưu**: theme tím gradient, thống kê tức thì, 4 tab rõ ràng

## 📂 Cấu trúc dự án

```
thumbnail_app/
├── app.py                      # UI Streamlit chính
├── image_processor.py          # Core engine xử lý ảnh
├── auth.py                     # Login + rate-limit
├── requirements.txt            # Dependencies
├── assets/
│   └── background.png          # Ảnh nền mẫu (có shadow sản phẩm)
├── fonts/
│   ├── Montserrat.ttf          # Font chính (variable)
│   ├── Montserrat-Italic.ttf
│   └── OFL.txt                 # Giấy phép
└── .streamlit/
    ├── config.toml             # Theme + server config
    └── secrets.toml.example    # Mẫu mật khẩu (copy thành secrets.toml khi chạy local)
```

## 🚀 Cài đặt & chạy local

```bash
# 1. Clone repo
git clone <your-repo-url>
cd thumbnail_app

# 2. Tạo virtualenv (khuyến nghị)
python -m venv venv
source venv/bin/activate         # Linux/Mac
# venv\Scripts\activate          # Windows

# 3. Cài dependencies
pip install -r requirements.txt

# 4. (Tuỳ chọn) Đặt credentials — nếu không đặt sẽ dùng mặc định ducpro / 234766
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Mở file và đổi APP_USERNAME và APP_PASSWORD

# 5. Chạy
streamlit run app.py
```

Mở trình duyệt tại http://localhost:8501 → đăng nhập bằng **ducpro / 234766** (mặc định).

## ☁️ Deploy lên Streamlit Cloud (MIỄN PHÍ, ẨN SOURCE CODE)

### Bước 1 — Tạo GitHub repo **PRIVATE**

```bash
cd thumbnail_app
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/thumbnail-builder.git
git push -u origin main
```

⚠️ **Lưu ý:** Chọn **Private** khi tạo repo trên GitHub để người khác không thấy source.

### Bước 2 — Deploy trên Streamlit Cloud

1. Truy cập https://share.streamlit.io
2. Đăng nhập bằng tài khoản GitHub
3. Click **"New app"** → chọn repo private vừa tạo
4. **Main file path:** `app.py`
5. Click **"Advanced settings"** → tab **Secrets**, dán vào (hoặc bỏ qua để dùng mặc định ducpro/234766):
   ```toml
   APP_USERNAME = "ducpro"
   APP_PASSWORD = "234766"
   ```
6. Click **Deploy**

App sẽ có URL dạng `https://<tên-app>.streamlit.app`. Người dùng cuối:
- ✅ Chỉ thấy UI web, không thấy bất kỳ dòng code nào
- ✅ Cần nhập mật khẩu mới dùng được
- ✅ Source code của bạn nằm trong GitHub Private, hoàn toàn riêng tư

### Bước 3 — Cập nhật app

Chỉ cần `git push`, Streamlit Cloud tự động redeploy:
```bash
git add .
git commit -m "Update feature"
git push
```

## 📋 Hướng dẫn sử dụng app

### 1. Chuẩn bị Excel

| id    | text1            | text2           |
|-------|------------------|-----------------|
| SP001 | BLUETOOTH 5.4    | CỔNG SẠC TYPE-C |
| SP002 | CHỐNG NƯỚC IPX7  |                 |
| SP003 | PIN 30H          | SẠC NHANH       |

- Cột `id`: mã sản phẩm (cũng là tên file output)
- Cột `text1`: dòng trên (pill 1)
- Cột `text2`: dòng dưới (pill 2). Bỏ trống thì không hiển thị pill 2.

App hỗ trợ cả tên cột tiếng Việt: `masp`, `tt1`, `tt2`, `dong1`, `dong2`...

### 2. Chuẩn bị ảnh sản phẩm

- Tên file chứa **id** là được: `SP001.png`, `SP001_main.jpg`, `product_sp001.jpeg` đều khớp
- Không cần đúng kích thước 600×600 — app tự resize
- Ảnh nền trắng thì bật tính năng **"Tách nền trắng"** ở sidebar

### 3. Tinh chỉnh

Sidebar có đầy đủ tuỳ chỉnh:
- **Layout sản phẩm**: margin top (mặc định 36), bottom (148), padding 2 bên
- **Text & Font**: size 9-30 (mặc định 20.4), weight Regular→Black, màu chữ
- **Pill**: vị trí, kích thước 2 pill, shadow offset/blur/opacity
- **Tách nền**: none / flood-fill trắng / AI rembg
- **Định dạng xuất**: PNG hoặc JPG (có chỉnh quality)

### 4. Xuất

Tab **📦 Xuất ZIP** → click **Tạo ZIP**. File ZIP gồm:
```
thumbnails_20260417_143022.zip
├── thumbnails/
│   ├── SP001.png
│   ├── SP002.png
│   └── ...
├── cms.csv         # UTF-8 BOM, mở bằng Excel được
├── cms.xlsx
└── README.txt
```

File `cms.csv` chứa: `id, text1, text2, filename, font_sizes_used, shrunk, width, height` — nạp thẳng vào CMS sản phẩm.

## 🔧 Tuỳ chỉnh nâng cao

### Đổi font

Thay file `fonts/Montserrat.ttf` bằng font khác. Nếu dùng variable font, app tự nhận `wght` axis.

### Đổi background

Thay file `assets/background.png` (phải là 600×600). App sẽ resize nếu khác size.

### Tắt rate-limit login

Sửa `auth.py` dòng `if fail_count >= 5` lên số lớn hơn.

## 🐛 Troubleshooting

| Vấn đề | Giải pháp |
|---|---|
| `rembg` không cài được | Bỏ qua — chỉ ảnh hưởng tính năng "Tách AI", các chế độ khác vẫn chạy. Có thể xoá rembg/onnxruntime khỏi requirements.txt. |
| Font không hiển thị tiếng Việt | Kiểm tra file `fonts/Montserrat.ttf` đã có chưa. App fallback DejaVu Sans nếu không tìm thấy. |
| Ảnh output bị nhoè | Tăng quality JPG lên 95-100 hoặc xuất PNG. |
| Text bị lệch | Chỉnh lại `Pill 1 top`, `Shadow Y offset` ở sidebar cho khớp. |
| Deploy bị lỗi onnxruntime | Streamlit Cloud không hỗ trợ một số wheel. Thử thêm file `packages.txt` chứa `libgl1`. |

## 📄 License

- Code: MIT (tuỳ bạn)
- Font Montserrat: SIL Open Font License 1.1 (xem `fonts/OFL.txt`)
