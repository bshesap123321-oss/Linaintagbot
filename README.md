# 🤖 AI Influencer Bot

Sanal bir karakter için her gün **kendi kendine** fotoğraf üretip Instagram'da paylaşan bot.
Bilgisayarınız kapalıyken de çalışır. GitHub'ın ücretsiz sunucularında, her gün sizin seçtiğiniz saatte.

```
 Fikir ajanı ──► Prompt ajanı ──► Görsel ajanı ──► Kontrol ajanı ──► Açıklama ajanı ──► Instagram
 (bugün ne?)     (sabit yüz)      (Gemini)         (beğenmezse       (karakterin        (AI etiketiyle
                                                    yeniden çizdirir)  ağzından)          paylaşır)
```

## Neler yapar?

- **Her gün farklı içerik:** Temaları ağırlığına göre seçer, son 20 paylaşımı tekrar etmez, mevsime uygun kıyafet seçer.
- **Hep aynı yüz:** Referans fotoğraflar ve sabit karakter tarifi her görselde kullanılır.
- **Kalite kontrolü:** Ayrı bir ajan her görseli puanlar. Yüz benzemiyorsa, el bozuksa ya da yazı veya logo varsa düzeltme talimatıyla yeniden ürettirir. Hiçbir görsel geçmezse o gün **paylaşım yapmaz**, kötü görsel asla yayınlanmaz.
- **Doğal açıklamalar:** Karakterin kişiliği ve ses tonuyla, fotoğrafa bakarak yazar. Hashtag'leri temizler, tekrarları ayıklar, Instagram sınırlarına uyar.
- **Şeffaflık:** Instagram'ın resmi "Yapay zekâ bilgisi" etiketini otomatik ekler ve açıklamaya not düşer.
- **Kayıt:** Her paylaşımın görseli, prompt'u, puanları ve açıklaması `posts/` klasöründe saklanır.
- **Bakım gerektirmez:** Instagram token'ı her ay otomatik yenilenir. Hata olursa GitHub size e-posta atar.
- **Başka karaktere uyarlanabilir:** Sadece `persona.yaml` dosyasını değiştirmeniz yeterli.

---

## Kurulum (yaklaşık 30 dakika, bir kez)

### 1. Instagram hesabını hazırla
1. Karakter için bir Instagram hesabı aç.
2. **Ayarlar → Hesap türü ve araçlar → Profesyonel hesaba geç** yolunu izle. "İçerik üreticisi" ya da "İşletme" seçebilirsin.

### 2. Instagram erişim anahtarını al
1. [developers.facebook.com](https://developers.facebook.com) adresinde **Uygulamalarım → Uygulama oluştur** de, tür olarak **İşletme** seç.
2. Uygulamaya **Instagram** ürününü ekle ve **API setup with Instagram login** bölümünü aç.
3. **Add account** ile karakterin Instagram hesabını bağla. Gerekirse Instagram'da *Ayarlar → Uygulamalar ve web siteleri* kısmından daveti kabul et.
4. **Generate token** ile token üret. Bu **60 gün geçerli** bir anahtardır; bot onu her ay kendisi yeniler.
5. Token'ı ve hesap kimliğini (Instagram user ID) bir kenara not et.

> Kendi hesaplarınız için uygulama incelemesi (App Review) gerekmez; uygulama "Geliştirme" modunda kalabilir.

### 3. Gemini API anahtarını al
1. [aistudio.google.com](https://aistudio.google.com) adresine git ve **Get API key → Create API key** de.
2. Görsel üretimi için Google Cloud'da **faturalandırmayı açman** gerekebilir. Güncel fiyatlara Google'ın fiyat sayfasından bak.

### 4. Referans fotoğrafı oluştur
Gemini uygulamasında aşağıdaki gibi bir prompt ile 5-10 deneme yap ve en beğendiğin 1-3 fotoğrafı `references/` klasörüne koy:

```
Photorealistic studio portrait of a 24-year-old woman, light olive skin, shoulder-length wavy
dark brown hair, hazel eyes, subtle freckles, natural makeup, elegant tall slim figure.
Front-facing, neutral expression, plain light grey background, soft even light, 85mm lens.
```
Karakterin yüzü artık bu fotoğraf. Sonradan değiştirmeyin.

### 5. GitHub'a yükle
1. [github.com](https://github.com) üzerinde **New repository** oluştur. **Public** seç (görseller Instagram'a buradan gider).
   Depoyu gizli tutmak istersen **Private** seç ve 7. adımdaki *imgbb* seçeneğini kullan.
2. **Add file → Upload files** ile bu klasördeki her şeyi sürükleyip bırak. `.github` klasörü de dahil olmalı.
3. **Settings → Actions → General → Workflow permissions** altında **Read and write permissions** seç ve kaydet.

### 6. Anahtarları ekle
**Settings → Secrets and variables → Actions → New repository secret:**

| Secret adı | Değer |
|---|---|
| `GEMINI_API_KEY` | 3. adımdaki anahtar |
| `IG_ACCESS_TOKEN` | 2. adımdaki token |
| `IG_USER_ID` | 2. adımdaki hesap kimliği (boş bırakılırsa otomatik bulunur) |
| `GH_PAT` | *Önerilir.* Token'ın otomatik yenilenmesi için, aşağıya bakın |

**`GH_PAT` nasıl alınır:** GitHub'da **Settings → Developer settings → Fine-grained tokens → Generate new token** yolunu izle. Sadece bu depoyu seç ve **Secrets: Read and write** iznini ver. Süreyi 1 yıl yap.

### 7. (İsteğe bağlı) Ayarlar
**Settings → Secrets and variables → Actions → Variables** sekmesi:

| Değişken | Ne işe yarar |
|---|---|
| `IMAGE_HOST` | `github` (varsayılan, public depo) veya `imgbb` (private depo; ayrıca `IMGBB_API_KEY` secret'ı ekleyin, [api.imgbb.com](https://api.imgbb.com) adresinden ücretsiz alınır) |
| `GEMINI_IMAGE_MODEL` | Görsel modeli. Varsayılan `gemini-3.1-flash-image` (Nano Banana 2). Daha kaliteli sonuç için AI Studio'daki model listesinden Nano Banana Pro'nun kimliğini yazın |
| `GEMINI_TEXT_MODEL` | Metin modeli. Varsayılan `gemini-flash-latest` |
| `DRY_RUN` | `true` yapılırsa üretir ama paylaşmaz |

### 8. İlk deneme
1. **Actions → Günlük paylaşım → Run workflow** yolunu izle. **Deneme modu** kutusunu işaretle ve çalıştır.
2. Bitince çalışmaya tıkla. Özet sayfasında üretilen açıklamayı ve puanları görürsün. Görsel `posts/` klasöründedir.
3. Sonuç iyiyse kutuyu işaretlemeden bir kez daha çalıştır. **İlk paylaşım yapılır** 🎉

Bundan sonra bot her gün **19:00'da (TR)** kendisi paylaşır.

---

## Özelleştirme

| Ne istiyorsunuz? | Nereyi değiştirin? |
|---|---|
| Karakterin kişiliği, temalar, ses tonu, hashtag'ler | `persona.yaml` |
| Paylaşım saati | `.github/workflows/daily-post.yml` → `cron` satırı (saat UTC'dir, TR = UTC+3) |
| Günde 2 paylaşım | Aynı dosyada `cron` satırının altına ikinci bir `- cron:` ekleyin |
| Daha katı ya da gevşek kalite kontrolü | `persona.yaml` → `review.min_score` |
| Başka bir karakter | `persona.yaml` + `references/` klasöründeki fotoğraflar |

## Sorun giderme

| Hata | Çözüm |
|---|---|
| `Eksik ayar: GEMINI_API_KEY` | Secret adı tam olarak böyle mi? |
| `Görsel URL'sine ulaşılamadı` | Depo **public** olmalı, ya da `IMAGE_HOST=imgbb` kullanın |
| `Instagram API hatası ... kod 190` | Token süresi dolmuş. Yeni token alıp `IG_ACCESS_TOKEN` secret'ını güncelleyin ve `GH_PAT` ekleyin |
| `3 denemede kaliteli görsel çıkmadı` | Normaldir, bot o gün paylaşmadı. Sık oluyorsa referans fotoğrafı iyileştirin veya `min_score` değerini 6 yapın |
| Gemini `429` / kota hatası | Faturalandırmanın açık olduğunu kontrol edin |

Kendi bilgisayarınızda test etmek için:
```bash
pip install -r requirements.txt
export GEMINI_API_KEY=... IG_ACCESS_TOKEN=... DRY_RUN=true
python -m influencer_bot check      # anahtarları ve ayarları doğrular
python -m influencer_bot generate   # bir taslak üretir (posts/ klasörüne)
python -m pytest -q                 # testler (internet gerektirmez)
```

## Önemli notlar
- Instagram hesap başına 24 saatte en fazla 50 API paylaşımına izin verir. Günde 1-3 paylaşım hem güvenli hem doğaldır.
- Gerçek kişilere benzeyen karakterler, marka logoları ve reşit olmayanlar `content_rules` ile engellenir. Bu kuralları kaldırmayın.
- Takipçi satın almak ya da otomatik beğeni/takip yapmak Instagram kurallarına aykırıdır ve hesabı kapattırabilir. Bu bot sadece içerik paylaşır.
