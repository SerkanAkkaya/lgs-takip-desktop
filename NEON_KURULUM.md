# Neon veritabanı bağlantısı

Uygulama Neon Postgres kullanır. EXE, çalışma anında `DATABASE_URL` değerini önce
Windows ortam değişkenlerinden, sonra EXE'nin bulunduğu klasördeki `.env.local`
veya `.env` dosyasından okur. `DATABASE_URL` olarak Neon'dan alınan **pooled**
bağlantı dizesini kullanın.

## Her bilgisayarda ilk kurulum

1. EXE'yi bilgisayara kopyalayın.
2. `.env.example` dosyasını `.env.local` adıyla EXE'nin yanına kopyalayın.
3. `DATABASE_URL` değerini Neon Console'dan alınan pooled bağlantı dizesiyle doldurun.
4. Uygulamayı açın. İnternet ve Neon erişimi gerekir.

Alternatif olarak `DATABASE_URL` Windows kullanıcı ortam değişkeni olarak
tanımlanabilir. Bağlantı dizesini herkese açık depoya veya dağıtım paketine
koymayın; bu bilgiler Neon veritabanına doğrudan erişim sağlar.

## Eski SQLite verisini Neon'a bir kez taşıma

Proje ortamında `.env.local` hazır ve `lgs_takip.db` kaynak dosyası mevcutken:

```powershell
.\.venv\Scripts\python.exe migrate_sqlite_to_neon.py
```

Aktarım, şema ve indexleri hazırlar; kaynak kayıt sayılarını çıktı verir ve
başarılı aktarımı `app_migrations` tablosuna kaydeder. Hedefte uygulama tabloları
önceden doluysa veri üzerine yazmamak için durur. Aktarımda ID değerleri korunur.
