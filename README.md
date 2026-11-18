# Image Scaler

Aplikasi desktop untuk memperbesar gambar menggunakan model Real-ESRGAN x2 dan x4. Aplikasi berjalan secara lokal di Windows.

## Yang perlu diinstall

- **Git** untuk clone repository.
- **Python 3.12** (disarankan) untuk menjalankan aplikasi.
- **Node.js dan npm** untuk membuat ulang CSS Tailwind.
- **Microsoft Visual C++ Redistributable** mungkin diperlukan oleh beberapa dependency Python di Windows.

Upscaling dapat berjalan menggunakan CPU. NVIDIA GPU yang kompatibel dapat digunakan untuk pemrosesan yang lebih cepat; instalasi PyTorch di `requirements.txt` menggunakan paket CUDA 13.0.

## Persiapan setelah clone

Buka PowerShell di folder tempat project akan disimpan, lalu jalankan:

```powershell
git clone <URL-REPOSITORY>
cd "Image Scaller"

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

npm install
npx @tailwindcss/cli -i .\src\input.css -o .\src\output.css
```

Ganti `<URL-REPOSITORY>` dengan URL repository project. Perintah `npm install` dan pembuatan CSS diperlukan untuk menyiapkan tampilan aplikasi.

## Model Real-ESRGAN

Pastikan kedua file checkpoint tersedia di folder `models`:

- `models/RealESRGAN_x2plus.pth`
- `models/RealESRGAN_x4plus.pth`

File model diperlukan saat aplikasi memproses gambar. Jika file tersebut tidak disertakan di repository yang di-clone, salin atau unduh file model yang sesuai ke folder `models` sebelum menjalankan aplikasi.

## Menjalankan aplikasi

Dengan virtual environment aktif:

```powershell
python .\main.py
```

Aplikasi akan membuka jendela desktop. Hasil gambar disimpan ke folder `Pictures\ResultImg` pada direktori pengguna Windows.

## Catatan

- Python packages tercantum di `requirements.txt`; UI dependencies tercantum di `package.json`.
- Upscaling menggunakan CPU jika CUDA tidak tersedia. Pemrosesan di CPU bisa lebih lambat.
- Unggahan gambar dibatasi 20 MB dan 5 megapiksel.
